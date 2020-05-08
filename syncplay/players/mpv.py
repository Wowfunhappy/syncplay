# coding:utf8
import os
import re
import sys
import time
import subprocess
import threading
import ast

from syncplay import constants
from syncplay.messages import getMessage
from syncplay.utils import isURL, findResourcePath
from syncplay.utils import isMacOS, isWindows

from syncplay.players.basePlayer import BasePlayer


class MpvPlayer(BasePlayer):
    RE_VERSION = re.compile(r'.*mpv (\d+)\.(\d+)\.\d+.*')
    osdMessageSeparator = "\\n"
    osdMessageSeparator = "; "  # TODO: Make conditional
    POSITION_QUERY = 'time-pos'
    OSD_QUERY = 'show_text'
    RE_ANSWER = re.compile(constants.MPLAYER_ANSWER_REGEX)
    lastResetTime = None
    lastMPVPositionUpdate = None
    alertOSDSupported = True
    chatOSDSupported = True
    speedSupported = True
    customOpenDialog = False

    @staticmethod
    def run(client, playerPath, filePath, args):
        try:
            ver = MpvPlayer.RE_VERSION.search(subprocess.check_output([playerPath, '--version']).decode('utf-8'))
        except:
            ver = None
        constants.MPV_NEW_VERSION = ver is None or int(ver.group(1)) > 0 or int(ver.group(2)) >= 17
        if not constants.MPV_NEW_VERSION:
            from twisted.internet import reactor
            the_reactor = reactor
            the_reactor.callFromThread(client.ui.showErrorMessage,
                                        "This version of mpv is not compatible with Syncplay. "
                                        "Please use mpv >=0.17.0.", True)
            the_reactor.callFromThread(client.stop)
            return

        constants.MPV_OSC_VISIBILITY_CHANGE_VERSION = False if ver is None else int(ver.group(1)) > 0 or int(ver.group(2)) >= 28
        if not constants.MPV_OSC_VISIBILITY_CHANGE_VERSION:
            client.ui.showDebugMessage(
                "This version of mpv is not known to be compatible with changing the OSC visibility. "
                "Please use mpv >=0.28.0.")
        return MpvPlayer(client, MpvPlayer.getExpandedPath(playerPath), filePath, args)

    @staticmethod
    def getStartupArgs(path, userArgs):
        args = constants.MPV_ARGS
        if userArgs:
            args.extend(userArgs)
        args.extend(constants.MPV_SLAVE_ARGS)
        if constants.MPV_NEW_VERSION:
            args.extend(constants.MPV_SLAVE_ARGS_NEW)
            args.extend(["--script={}".format(findResourcePath("syncplayintf.lua"))])
        return args

    @staticmethod
    def getDefaultPlayerPathsList():
        l = []
        for path in constants.MPV_PATHS:
            p = MpvPlayer.getExpandedPath(path)
            if p:
                l.append(p)
        return l

    @staticmethod
    def isValidPlayerPath(path):
        if "mpv" in path and "mpvnet" not in path and MpvPlayer.getExpandedPath(path):
            return True
        return False

    @staticmethod
    def getExpandedPath(playerPath):
        if not os.path.isfile(playerPath):
            if os.path.isfile(playerPath + "mpv.exe"):
                playerPath += "mpv.exe"
                return playerPath
            elif os.path.isfile(playerPath + "\\mpv.exe"):
                playerPath += "\\mpv.exe"
                return playerPath
        if os.access(playerPath, os.X_OK):
            return playerPath
        for path in os.environ['PATH'].split(':'):
            path = os.path.join(os.path.realpath(path), playerPath)
            if os.access(path, os.X_OK):
                return path

    @staticmethod
    def getIconPath(path):
        return constants.MPV_ICONPATH

    @staticmethod
    def getPlayerPathErrors(playerPath, filePath):
        return None

    def _setProperty(self, property_, value):
        self._listener.sendLine("no-osd set {} {}".format(property_, value))

    def mpvErrorCheck(self, line):
        if "Error parsing option" in line or "Error parsing commandline option" in line:
            self.quitReason = getMessage("mpv-version-error")

        elif "Could not open pipe at '/dev/stdin'" in line:
            self.reactor.callFromThread(self._client.ui.showErrorMessage, getMessage("mpv-version-error"), True)
            self.drop()

        if constants and any(errormsg in line for errormsg in constants.MPV_ERROR_MESSAGES_TO_REPEAT):
            self._client.ui.showErrorMessage(line)


    def oldDisplayMessage(
                self, message,
                duration=(constants.OSD_DURATION * 1000), OSDType=constants.OSD_NOTIFICATION,
                mood=constants.MESSAGE_NEUTRAL
        ):
            messageString = self._sanitizeText(message.replace("\\n", "<NEWLINE>")).replace("<NEWLINE>", "\\n")
            self._listener.sendLine('{} "{!s}" {} {}'.format(
                self.OSD_QUERY, messageString, duration, constants.MPLAYER_OSD_LEVEL))

    def displayMessage(self, message, duration=(constants.OSD_DURATION * 1000), OSDType=constants.OSD_NOTIFICATION,
                       mood=constants.MESSAGE_NEUTRAL):
        if not self._client._config["chatOutputEnabled"]:
            self.oldDisplayMessage(self, message=message, duration=duration, OSDType=OSDType, mood=mood)
            return
        messageString = self._sanitizeText(message.replace("\\n", "<NEWLINE>")).replace(
            "\\\\", constants.MPV_INPUT_BACKSLASH_SUBSTITUTE_CHARACTER).replace("<NEWLINE>", "\\n")
        self._listener.sendLine('script-message-to syncplayintf {}-osd-{} "{}"'.format(OSDType, mood, messageString))

    def displayChatMessage(self, username, message):
        if not self._client._config["chatOutputEnabled"]:
            messageString = "<{}> {}".format(username, message)
            messageString = self._sanitizeText(messageString.replace("\\n", "<NEWLINE>")).replace("<NEWLINE>", "\\n")
            duration = int(constants.OSD_DURATION * 1000)
            self._listener.sendLine('{} "{!s}" {} {}'.format(
                self.OSD_QUERY, messageString, duration, constants.MPLAYER_OSD_LEVEL))
            return
        username = self._sanitizeText(username.replace("\\", constants.MPV_INPUT_BACKSLASH_SUBSTITUTE_CHARACTER))
        message = self._sanitizeText(message.replace("\\", constants.MPV_INPUT_BACKSLASH_SUBSTITUTE_CHARACTER))
        messageString = "<{}> {}".format(username, message)
        self._listener.sendLine('script-message-to syncplayintf chat "{}"'.format(messageString))

    def setSpeed(self, value):
        self._setProperty('speed', "{:.2f}".format(value))

    def setPaused(self, value):
        if self._paused == value:
            self._client.ui.showDebugMessage("Not sending setPaused to mpv as state is already {}".format(value))
            return
        pauseValue = "yes" if value else "no"
        self._setProperty("pause", pauseValue)
        self._paused = value
        if value == False:
            self.lastMPVPositionUpdate = time.time()

    def _getFilename(self):
        self._getProperty('filename')

    def _getLength(self):
        self._getProperty('length')

    def _getFilepath(self):
        self._getProperty('path')

    def _getProperty(self, property_):
        floatProperties = ['time-pos']
        if property_ in floatProperties:
            propertyID = "={}".format(property_)
        elif property_ == 'length':
            propertyID = '=duration:${=length:0}'
        else:
            propertyID = property_
        self._listener.sendLine("print_text ""ANS_{}=${{{}}}""".format(property_, propertyID))

    def getCalculatedPosition(self):
        if self.fileLoaded == False:
            self._client.ui.showDebugMessage(
                "File not loaded so using GlobalPosition for getCalculatedPosition({})".format(
                    self._client.getGlobalPosition()))
            return self._client.getGlobalPosition()

        if self.lastMPVPositionUpdate is None:
            self._client.ui.showDebugMessage(
                "MPV not updated position so using GlobalPosition for getCalculatedPosition ({})".format(
                    self._client.getGlobalPosition()))
            return self._client.getGlobalPosition()

        if self._recentlyReset():
            self._client.ui.showDebugMessage(
                "Recently reset so using self.position for getCalculatedPosition ({})".format(
                    self._position))
            return self._position

        diff = time.time() - self.lastMPVPositionUpdate

        if diff > constants.MPV_UNRESPONSIVE_THRESHOLD:
            self.reactor.callFromThread(
                self._client.ui.showErrorMessage, getMessage("mpv-unresponsive-error").format(int(diff)), True)
            self.drop()
        if diff > constants.PLAYER_ASK_DELAY and not self._paused:
            self._client.ui.showDebugMessage(
                "mpv did not response in time, so assuming position is {} ({}+{})".format(
                    self._position + diff, self._position, diff))
            return self._position + diff
        else:
            return self._position

    def _storePosition(self, value):
        if self._client.isPlayingMusic() and self._paused == False and self._position == value and abs(self._position-self._position) < 0.5:
            self._client.ui.showDebugMessage("EOF DETECTED!")
            self._position = 0
            self.setPosition(0)
        self.lastMPVPositionUpdate = time.time()
        if self._recentlyReset():
            self._client.ui.showDebugMessage("Recently reset, so storing position as 0")
            self._position = 0
        elif self._fileIsLoaded() or (value < constants.MPV_NEWFILE_IGNORE_TIME and self._fileIsLoaded(ignoreDelay=True)):
            self._position = max(value, 0)
        else:
            self._client.ui.showDebugMessage(
                "No file loaded so storing position as GlobalPosition ({})".format(self._client.getGlobalPosition()))
            self._position = self._client.getGlobalPosition()

    def _storePauseState(self, value):
        if self._fileIsLoaded():
            self._paused = value
        else:
            self._paused = self._client.getGlobalPaused()

    def lineReceived(self, line):
        if line:
            self._client.ui.showDebugMessage("player << {}".format(line))
            line = line.replace("[cplayer] ", "")  # -v workaround
            line = line.replace("[term-msg] ", "")  # -v workaround
            line = line.replace("   cplayer: ", "")  # --msg-module workaround
            line = line.replace("  term-msg: ", "")
        if (
            "Failed to get value of property" in line or
            "=(unavailable)" in line or
            line == "ANS_filename=" or
            line == "ANS_length=" or
            line == "ANS_path="
        ):
            if "filename" in line:
                self._getFilename()
            elif "length" in line:
                self._getLength()
            elif "path" in line:
                self._getFilepath()
            return
        match = self.RE_ANSWER.match(line)
        if not match:
            self._handleUnknownLine(line)
            return

        name, value = [m for m in match.groups() if m]
        name = name.lower()

        if name == self.POSITION_QUERY:
            self._storePosition(float(value))
            self._positionAsk.set()
        elif name == "pause":
            self._storePauseState(bool(value == 'yes'))
            self._pausedAsk.set()
        elif name == "length":
            try:
                self._duration = float(value)
            except:
                self._duration = 0
            self._durationAsk.set()
        elif name == "path":
            self._filepath = value
            self._pathAsk.set()
        elif name == "filename":
            self._filename = value
            self._filenameAsk.set()
        elif name == "exiting":
            if value != 'Quit':
                if self.quitReason is None:
                    self.quitReason = getMessage("media-player-error").format(value)
                self.reactor.callFromThread(self._client.ui.showErrorMessage, self.quitReason, True)
            self.drop()

    def askForStatus(self):
        self._positionAsk.clear()
        self._pausedAsk.clear()
        if not self._listener.isReadyForSend:
            self._client.ui.showDebugMessage("mpv not ready for update")
            return

        self._getPausedAndPosition()
        self._positionAsk.wait(constants.MPV_LOCK_WAIT_TIME)
        self._pausedAsk.wait(constants.MPV_LOCK_WAIT_TIME)
        self._client.updatePlayerStatus(
            self._paused if self.fileLoaded else self._client.getGlobalPaused(), self.getCalculatedPosition())

    def drop(self):
        self._listener.sendLine('quit')
        self._takeLocksDown()
        self.reactor.callFromThread(self._client.stop, False)

    def _takeLocksDown(self):
        self._durationAsk.set()
        self._filenameAsk.set()
        self._pathAsk.set()
        self._positionAsk.set()
        self._pausedAsk.set()


    def _getPausedAndPosition(self):
        self._listener.sendLine("print_text ANS_pause=${pause}\r\nprint_text ANS_time-pos=${=time-pos}")

    def _getPaused(self):
        self._getProperty('pause')

    def _getPosition(self):
        self._getProperty(self.POSITION_QUERY)

    def _sanitizeText(self, text):
        text = text.replace("\r", "")
        text = text.replace("\n", "")
        text = text.replace("\\\"", "<SYNCPLAY_QUOTE>")
        text = text.replace("\"", "<SYNCPLAY_QUOTE>")
        text = text.replace("%", "%%")
        text = text.replace("\\", "\\\\")
        text = text.replace("{", "\\\\{")
        text = text.replace("}", "\\\\}")
        text = text.replace("<SYNCPLAY_QUOTE>", "\\\"")
        return text

    def _quoteArg(self, arg):
        arg = arg.replace('\\', '\\\\')
        arg = arg.replace("'", "\\'")
        arg = arg.replace('"', '\\"')
        arg = arg.replace("\r", "")
        arg = arg.replace("\n", "")
        return '"{}"'.format(arg)

    def _preparePlayer(self):
        if self.delayedFilePath:
            self.openFile(self.delayedFilePath)
        self.setPaused(True)
        self.reactor.callLater(0, self._client.initPlayer, self)

    def _clearFileLoaded(self):
        self.fileLoaded = False
        self.lastLoadedTime = None

    def _loadFile(self, filePath):
        self._clearFileLoaded()
        self._listener.sendLine('loadfile {}'.format(self._quoteArg(filePath)), notReadyAfterThis=True)

    def setFeatures(self, featureList):
        self.sendMpvOptions()

    def setPosition(self, value):
        if value < constants.DO_NOT_RESET_POSITION_THRESHOLD and self._recentlyReset():
            self._client.ui.showDebugMessage(
                "Did not seek as recently reset and {} below 'do not reset position' threshold".format(value))
            return
        self._position = max(value, 0)
        self._setProperty(self.POSITION_QUERY, "{}".format(value))
        time.sleep(0.03)
        self.lastMPVPositionUpdate = time.time()

    def openFile(self, filePath, resetPosition=False):
        self._client.ui.showDebugMessage("openFile, resetPosition=={}".format(resetPosition))
        if resetPosition:
            self.lastResetTime = time.time()
            if isURL(filePath):
                self.lastResetTime += constants.STREAM_ADDITIONAL_IGNORE_TIME
        self._loadFile(filePath)
        if self._paused != self._client.getGlobalPaused():
            self._client.ui.showDebugMessage("Want to set paused to {}".format(self._client.getGlobalPaused()))
        else:
            self._client.ui.showDebugMessage("Don't want to set paused to {}".format(self._client.getGlobalPaused()))
        if resetPosition == False:
            self.setPosition(self._client.getGlobalPosition())
        else:
            self._storePosition(0)

    def sendMpvOptions(self):
        options = []
        for option in constants.MPV_SYNCPLAYINTF_OPTIONS_TO_SEND:
            options.append("{}={}".format(option, self._client._config[option]))
        for option in constants.MPV_SYNCPLAYINTF_CONSTANTS_TO_SEND:
            options.append(option)
        for option in constants.MPV_SYNCPLAYINTF_LANGUAGE_TO_SEND:
            options.append("{}={}".format(option, getMessage(option)))
        options.append("OscVisibilityChangeCompatible={}".format(constants.MPV_OSC_VISIBILITY_CHANGE_VERSION))
        options_string = ", ".join(options)
        self._listener.sendLine('script-message-to syncplayintf set_syncplayintf_options "{}"'.format(options_string))
        self._setOSDPosition()

    def _handleUnknownLine(self, line):
        self.mpvErrorCheck(line)

        if "<chat>" in line:
            line = line.replace(constants.MPV_INPUT_BACKSLASH_SUBSTITUTE_CHARACTER, "\\")
            self._listener.sendChat(line[6:-7])

        if "<get_syncplayintf_options>" in line:
            self.sendMpvOptions()

        if line == "<SyncplayUpdateFile>" or "Playing:" in line:
            self._listener.setReadyToSend(False)
            self._clearFileLoaded()

        elif line == "</SyncplayUpdateFile>":
            self._onFileUpdate()
            self._listener.setReadyToSend(True)

        elif "Failed" in line or "failed" in line or "No video or audio streams selected" in line or "error" in line:
            self._listener.setReadyToSend(True)

    def _setOSDPosition(self):
        if (
            self._client._config['chatMoveOSD'] and (
                self._client._config['chatOutputEnabled'] or (
                    self._client._config['chatInputEnabled'] and
                    self._client._config['chatInputPosition'] == constants.INPUT_POSITION_TOP
                )
            )
        ):
            self._setProperty("osd-align-y", "bottom")
            self._setProperty("osd-margin-y", int(self._client._config['chatOSDMargin']))

    def _recentlyReset(self):
        if not self.lastResetTime:
            return False
        elif time.time() < self.lastResetTime + constants.MPV_NEWFILE_IGNORE_TIME:
            return True
        else:
            return False

    def _onFileUpdate(self):
        self.fileLoaded = True
        self.lastLoadedTime = time.time()
        self.reactor.callFromThread(self._client.updateFile, self._filename, self._duration, self._filepath)
        if not (self._recentlyReset()):
            self.reactor.callFromThread(self.setPosition, self._client.getGlobalPosition())
        if self._paused != self._client.getGlobalPaused():
            self.reactor.callFromThread(self._client.getGlobalPaused)

    def _fileIsLoaded(self, ignoreDelay=False):
        if ignoreDelay:
            self._client.ui.showDebugMessage("Ignoring _fileIsLoaded MPV_NEWFILE delay")
            return bool(self.fileLoaded)

        return (
            self.fileLoaded and self.lastLoadedTime is not None and
            time.time() > (self.lastLoadedTime + constants.MPV_NEWFILE_IGNORE_TIME)
        )


    def __init__(self, client, playerPath, filePath, args):
        from twisted.internet import reactor
        self.reactor = reactor
        self._client = client
        self._paused = None
        self._position = 0.0
        self._duration = None
        self._filename = None
        self._filepath = None
        self.quitReason = None
        self.lastLoadedTime = None
        self.fileLoaded = False
        self.delayedFilePath = None
        try:
            self._listener = self.__Listener(self, playerPath, filePath, args)
        except ValueError:
            self._client.ui.showMessage(getMessage("mplayer-file-required-notification"))
            self._client.ui.showMessage(getMessage("mplayer-file-required-notification/example"))
            self.drop()
            return
        self._listener.setDaemon(True)
        self._listener.start()

        self._durationAsk = threading.Event()
        self._filenameAsk = threading.Event()
        self._pathAsk = threading.Event()

        self._positionAsk = threading.Event()
        self._pausedAsk = threading.Event()

        self._preparePlayer()

    def _fileUpdateClearEvents(self):
        self._durationAsk.clear()
        self._filenameAsk.clear()
        self._pathAsk.clear()

    def _fileUpdateWaitEvents(self):
        self._durationAsk.wait()
        self._filenameAsk.wait()
        self._pathAsk.wait()

    class __Listener(threading.Thread):
        def __init__(self, playerController, playerPath, filePath, args):
            self.sendQueue = []
            self.readyToSend = True
            self.lastSendTime = None
            self.lastNotReadyTime = None
            self.__playerController = playerController
            if not self.__playerController._client._config["chatOutputEnabled"]:
                self.__playerController.alertOSDSupported = False
                self.__playerController.chatOSDSupported = False
            if self.__playerController.getPlayerPathErrors(playerPath, filePath):
                raise ValueError()
            if filePath and '://' not in filePath:
                if not os.path.isfile(filePath) and 'PWD' in os.environ:
                    filePath = os.environ['PWD'] + os.path.sep + filePath
                filePath = os.path.realpath(filePath)

            call = [playerPath]
            if filePath:
                if isWindows() and not utils.isASCII(filePath):
                    self.__playerController.delayedFilePath = filePath
                    filePath = None
                else:
                    call.extend([filePath])
            call.extend(playerController.getStartupArgs(playerPath, args))
            # At least mpv may output escape sequences which result in syncplay
            # trying to parse something like
            # "\x1b[?1l\x1b>ANS_filename=blah.mkv". Work around this by
            # unsetting TERM.
            env = os.environ.copy()
            if 'TERM' in env:
                del env['TERM']
            # On macOS, youtube-dl requires system python to run. Set the environment
            # to allow that version of python to be executed in the mpv subprocess.
            if isMacOS():
                try:
                    pythonLibs = subprocess.check_output(['/usr/bin/python', '-E', '-c',
                                                          'import sys; print(sys.path)'],
                                                          text=True, env=dict())
                    pythonLibs = ast.literal_eval(pythonLibs)
                    pythonPath = ':'.join(pythonLibs[1:])
                except:
                    pythonPath = None
                if pythonPath is not None:
                    env['PATH'] = '/usr/bin:/usr/local/bin'
                    env['PYTHONPATH'] = pythonPath
            if filePath:
                self.__process = subprocess.Popen(
                    call, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.STDOUT,
                    cwd=self.__getCwd(filePath, env), env=env, bufsize=0)
            else:
                self.__process = subprocess.Popen(
                    call, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env=env, bufsize=0)
            threading.Thread.__init__(self, name="MPV Listener")

        def __getCwd(self, filePath, env):
            if not filePath:
                return None
            if os.path.isfile(filePath):
                cwd = os.path.dirname(filePath)
            elif 'HOME' in env:
                cwd = env['HOME']
            elif 'APPDATA' in env:
                cwd = env['APPDATA']
            else:
                cwd = None
            return cwd

        def run(self):
            line = self.__process.stdout.readline()
            line = line.decode('utf-8')
            line = line.rstrip("\r\n")
            self.__playerController.lineReceived(line)
            while self.__process.poll() is None:
                line = self.__process.stdout.readline()
                line = line.decode('utf-8')
                line = line.rstrip("\r\n")
                self.__playerController.lineReceived(line)
            self.__playerController.drop()

        def sendChat(self, message):
            if message:
                if message[:1] == "/" and message != "/":
                    command = message[1:]
                    if command and command[:1] == "/":
                        message = message[1:]
                    else:
                        self.__playerController.reactor.callFromThread(
                            self.__playerController._client.ui.executeCommand, command)
                        return
                self.__playerController.reactor.callFromThread(self.__playerController._client.sendChat, message)

        def isReadyForSend(self):
            self.checkForReadinessOverride()
            return self.readyToSend

        def setReadyToSend(self, newReadyState):
            oldState = self.readyToSend
            self.readyToSend = newReadyState
            self.lastNotReadyTime = time.time() if newReadyState == False else None
            if self.readyToSend == True:
                self.__playerController._client.ui.showDebugMessage("<mpv> Ready to send: True")
            else:
                self.__playerController._client.ui.showDebugMessage("<mpv> Ready to send: False")
            if self.readyToSend == True and oldState == False:
                self.processSendQueue()

        def checkForReadinessOverride(self):
            if self.lastNotReadyTime and time.time() - self.lastNotReadyTime > constants.MPV_MAX_NEWFILE_COOLDOWN_TIME:
                self.setReadyToSend(True)

        def sendLine(self, line, notReadyAfterThis=None):
            self.checkForReadinessOverride()
            if self.readyToSend == False and "print_text ANS_pause" in line:
                self.__playerController._client.ui.showDebugMessage("<mpv> Not ready to get status update, so skipping")
                return
            try:
                if self.sendQueue:
                    if constants.MPV_SUPERSEDE_IF_DUPLICATE_COMMANDS:
                        for command in constants.MPV_SUPERSEDE_IF_DUPLICATE_COMMANDS:
                            if line.startswith(command):
                                for itemID, deletionCandidate in enumerate(self.sendQueue):
                                    if deletionCandidate.startswith(command):
                                        self.__playerController._client.ui.showDebugMessage(
                                            "<mpv> Remove duplicate (supersede): {}".format(self.sendQueue[itemID]))
                                        try:
                                            self.sendQueue.remove(self.sendQueue[itemID])
                                        except UnicodeWarning:
                                            self.__playerController._client.ui.showDebugMessage(
                                                "<mpv> Unicode mismatch occured when trying to remove duplicate")
                                            # TODO: Prevent this from being triggered
                                            pass
                                        break
                            break
                    if constants.MPV_REMOVE_BOTH_IF_DUPLICATE_COMMANDS:
                        for command in constants.MPV_REMOVE_BOTH_IF_DUPLICATE_COMMANDS:
                            if line == command:
                                for itemID, deletionCandidate in enumerate(self.sendQueue):
                                    if deletionCandidate == command:
                                        self.__playerController._client.ui.showDebugMessage(
                                            "<mpv> Remove duplicate (delete both): {}".format(self.sendQueue[itemID]))
                                        self.__playerController._client.ui.showDebugMessage(self.sendQueue[itemID])
                                        return
            except:
                self.__playerController._client.ui.showDebugMessage("<mpv> Problem removing duplicates, etc")
            self.sendQueue.append(line)
            self.processSendQueue()
            if notReadyAfterThis:
                self.setReadyToSend(False)

        def processSendQueue(self):
            while self.sendQueue and self.readyToSend:
                if self.lastSendTime and time.time() - self.lastSendTime < constants.MPV_SENDMESSAGE_COOLDOWN_TIME:
                    self.__playerController._client.ui.showDebugMessage(
                        "<mpv> Throttling message send, so sleeping for {}".format(
                            constants.MPV_SENDMESSAGE_COOLDOWN_TIME))
                    time.sleep(constants.MPV_SENDMESSAGE_COOLDOWN_TIME)
                try:
                    lineToSend = self.sendQueue.pop()
                    if lineToSend:
                        self.lastSendTime = time.time()
                        self.actuallySendLine(lineToSend)
                except IndexError:
                    pass

        def actuallySendLine(self, line):
            try:
                # if not isinstance(line, str):
                    # line = line.decode('utf8')
                line = line + "\n"
                self.__playerController._client.ui.showDebugMessage("player >> {}".format(line))
                line = line.encode('utf-8')
                self.__process.stdin.write(line)
            except IOError:
                pass
