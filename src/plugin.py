###############################################################################
#
#    MovieArchiver
#    Copyright (C) 2013 by svox
#
#    In case of reuse of this source code please do not remove this copyright.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    For more information on the GNU General Public License see:
#    <http://www.gnu.org/licenses/>.
#
###############################################################################

# PYTHON IMPORTS
from collections import deque
from os import makedirs, listdir, walk, access, stat, statvfs, W_OK
from os.path import (
    getmtime,
    join,
    basename,
    isfile,
    isdir,
    ismount,
    islink,
    dirname,
    realpath,
    exists,
    splitext,
    getsize,
)
from pipes import quote
from six import iteritems
from sys import exc_info, stdout
from time import time
from traceback import print_exception

# ENIGMA IMPORTS
from enigma import (
    getDesktop,
    eConsoleAppContainer,
    eTimer,
)
from Components.ActionMap import ActionMap
from Components.config import (
    config,
    configfile,
    getConfigListEntry,
)
from Components.ConfigList import ConfigListScreen
from Components.FileList import MultiFileSelectList
from Components.Sources.StaticText import StaticText
from Screens.LocationBox import MovieLocationBox
from Screens.MessageBox import MessageBox
from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Tools import Notifications
import NavigationInstance

# PLUGIN IMPORTS
from . import (
    printToConsole,
    getSourcePathValue,
    getTargetPathValue,
    getSourcePath,
    getTargetPath,
    _,
)


class MAglobs():
    handler = []
    notificationController = None
    MAX_TRIES = 50  # max tries (movies to move) after startArchiving recursion will end
    INFO_MSG = "showAlert"  # show message window: body is msg, timeout
    QUEUE_FINISHED = "queueFinished"
    SECONDS_NEXT_RECORD = 600  # if in 10 mins (=600 secs) a record starts, dont archive movies
    MOVIE_EXTENSION_TO_ARCHIVE = (".ts", ".avi", ".mkv", ".mp4", ".iso")  # file extension to archive or backup
    DEFAULT_EXCLUDED_DIRNAMES = [".Trash", "trashcan"]
    RECORD_FINISHED = "recordFinished"

    def hasEventListener(self, eventType, function):
        for e in self.handler:
            if e[0] == eventType and e[1] == function:
                return True
        return False

    def addEventListener(self, eventType, function):
        if self.hasEventListener(eventType, function) is False:
            self.handler.append([eventType, function])

    def removeEventListener(self, eventType, function):
        for e in self.handler:
            if e[0] == eventType and e[1] == function:
                self.handler.remove(e)

    def dispatchEvent(self, eventType, *arg):
        for e in self.handler:
            if e[0] == eventType:
                if (arg is not None and len(arg) > 0):
                    e[1](*arg)
                else:
                    e[1]()

    def getOldestFile(self, mediapath, fileExtensions=None):
        files = self.getFilesFromPath(mediapath)  # get oldest file from folder fileExtensions as tuple. example: ('.txt', '.png')
        if files:
            files = self.__filterFileListByFileExtension(files, fileExtensions)
            return min(files, key=getmtime) if files else None  # oldestFile

    def getFiles(self, mediapath, fileExtensions=None):
        files = self.getFilesFromPath(mediapath)  # get file list as an array   sorted by date. The oldest first fileExtensions as tuple. example: ('.txt', '.png')
        if not files:
            files = self.__filterFileListByFileExtension(files, fileExtensions)
            if files:
                files.sort(key=lambda s: getmtime(join(mediapath, s)))
        return files

    def getFilesFromPath(self, mediapath):
        return [join(mediapath, fname) for fname in listdir(mediapath)]

    def getFilesWithNameKey(self, mediapath, excludedDirNames=None, excludeDirs=None):
        rs = {}  # get recursive all files from given path
        for dirPath, dirNames, fileNames in walk(mediapath):
            for fileName in fileNames:
                if excludedDirNames is not None and basename(dirPath) in excludedDirNames:  # skip, if dirname is found in excludedDirNames
                    continue
                fullFilePath = join(dirPath, fileName)
                skipFile = False
                pathToCheck = dirPath if dirPath.endswith("/") else f"{dirPath}/"
                if excludeDirs is not None:  # skip, if path found in excludeDirs
                    for excludeDir in excludeDirs:
                        if pathToCheck[:len(excludeDir)] == excludeDir:
                            skipFile = True
                            break
                if skipFile is True:
                    continue
                rs[join(dirPath.replace(mediapath, ""), fileName)] = fullFilePath
        return rs

    def pathIsWriteable(self, mediapath):
        if isfile(mediapath):
            mediapath = dirname(mediapath)
        return True if isdir(mediapath) and self.ismounted(mediapath) and access(mediapath, W_OK) else False

    def ismounted(self, mediapath):
        return isdir(self.mountpoint(mediapath))

    def mountpoint(self, mediapath, first=True):
        if first:
            mediapath = realpath(mediapath)
        return mediapath if ismount(mediapath) or len(mediapath) == 0 else self.mountpoint(dirname(mediapath), False)

    def removeSymbolicLinks(self, pathList):
        tmpExcludedDirs = []
        for folder in pathList:
            if islink(folder) is False:
                tmpExcludedDirs.append(folder)
        return tmpExcludedDirs

    def getFreeDiskspace(self, mediapath):
        if exists(mediapath):  # Check free space on path
            stat = statvfs(mediapath)
            free = (stat.f_bavail if stat.f_bavail != 0 else stat.f_bfree) * stat.f_bsize // 1024 // 1024  # MB
            return free
        return 0  # maybe call exception

    def getFreeDiskspaceText(self, mediapath):
        free = self.getFreeDiskspace(mediapath)
        return f"{free} GB"if free >= 10 * 1024 else f"{free} MB" % (free)  # MB

    def reachedLimit(self, mediapath, limit):
        free = self.getFreeDiskspace(mediapath)
        return True if limit > (free // 1024) else False  # GB

    def checkReachedLimitIfMoveFile(self, mediapath, limit, moviesFileSize):
        freeDiskSpace = self.getFreeDiskspace(mediapath)
        return True if (freeDiskSpace + moviesFileSize) >= limit * 1024 else False

    def getFileHash(self, file, factor=10, sizeToSkip=104857600):
        # factor, if size is higher, it is faster but need more ram sizeToSkip 104857600 = 100mb
        # currently, we check only the fileSize because opening files and creating hash are to slow
        return str(stat(file).st_size)

    def __filterFileListByFileExtension(self, files, fileExtensions):  # Private Methods
        # fileExtensions as tuple. example: ('.txt', '.png')
        # files = filter(lambda s: s.endswith(fileExtension), files)
        files = filter(lambda s: s.lower().endswith(fileExtensions), files) if fileExtensions is not None else files


class RecordNotification(MAglobs):
    def __init__(self):
        self.forceBindRecordTimer = None

    def startTimer(self):
        self.forceBindRecordTimer = eTimer()
        self.forceBindRecordTimer.callback.append(self.__begin)
        if os.path.exists('/var/lib/dpkg/info'):
            self.forceBindRecordTimer_conn = self.forceBindRecordTimer.timeout.connect(self.load_getcl(data))
        else:
            self.forceBindRecordTimer.callback.append(self.load_getcl(data))

        if self.isActive():
            self.forceBindRecordTimer.stop()
        self.forceBindRecordTimer.start(50, True)
        printToConsole("[RecordNotification] startTimer")

    def stopTimer(self):
        self.__end()
        if self.forceBindRecordTimer is not None:
            self.forceBindRecordTimer.stop()
            self.forceBindRecordTimer.callback.remove(self.__begin)
            self.forceBindRecordTimer = None
        printToConsole("[RecordNotification] stopTimer")

    def isActive(self):
        if self.forceBindRecordTimer is not None and self.forceBindRecordTimer.isActive():
            return True
        return False

    def __begin(self):  # Private Methods
        if NavigationInstance.instance:
            if self.__onRecordEvent not in NavigationInstance.instance.RecordTimer.on_state_change:
                printToConsole("add RecordNotification")
                NavigationInstance.instance.RecordTimer.on_state_change.append(self.__onRecordEvent)  # Append callback function
        elif self.forceBindRecordTimer:
            self.forceBindRecordTimer.startLongTimer(1)  # Try again later

    def __end(self):
        if NavigationInstance.instance:
            if self.__onRecordEvent in NavigationInstance.instance.RecordTimer.on_state_change:  # Remove callback function
                printToConsole("remove RecordNotification")
                NavigationInstance.instance.RecordTimer.on_state_change.remove(self.__onRecordEvent)

    def __onRecordEvent(self, timer):
        if timer.justplay:
            pass
        elif timer.state == timer.StatePrepared:
            pass
        elif timer.state == timer.StateRunning:
            pass
        elif timer.state == timer.StateEnded or timer.repeated and timer.state == timer.StateWaiting:  # Finished repeating timer will report the state StateEnded+1 or StateWaiting
            printToConsole("[RecordNotification] record end!")
            self.dispatchEvent(self.RECORD_FINISHED)  # del timer


class NotificationController(MAglobs, object):  # classdocs
    instance = None

    def __init__(self):  # Constructor
        self.view = None
        self.showUIMessage = None
        self.movieManager = MovieManager()
        self.recordNotification = RecordNotification()

    @staticmethod
    def getInstance():
        if NotificationController.instance is None:
            NotificationController.instance = NotificationController()
        return NotificationController.instance

    def setView(self, view):
        self.view = view

    def getView(self):
        return self.view

    def start(self):
        if config.plugins.MovieArchiver.enabled.value and self.recordNotification.isActive() is False:
            self.addEventListener(self.RECORD_FINISHED, self.__recordFinishedHandler)
            self.recordNotification.startTimer()

    def stop(self):
        self.removeEventListener(self.RECORD_FINISHED, self.__recordFinishedHandler)
        self.recordNotification.stopTimer()

    def startArchiving(self, showUIMessage=False):
        self.showUIMessage = showUIMessage
        if self.showUIMessage is True:
            self.addEventListener(self.QUEUE_FINISHED, self.__queueFinishedHandler)
        else:
            self.removeEventListener(self.QUEUE_FINISHED, self.__queueFinishedHandler)
        self.addEventListener(self.INFO_MSG, self.__infoMsgHandler)
        self.movieManager.startArchiving()

    def stopArchiving(self):
        self.movieManager.stopArchiving()
        self.showMessage(_("MovieArchiver: Stop Archiving."), 5)

    def isArchiving(self):
        return self.movieManager.running()  # returns true if currently archiving or backup is running

    def showMessage(self, msg, timeout=10):
        if self.view is not None:
            self.view.session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout)
        else:
            Notifications.AddNotification(MessageBox, msg, type=MessageBox.TYPE_INFO, timeout=timeout)

    def __recordFinishedHandler(self):  # Private Methods
        printToConsole("recordFinished")
        self.startArchiving()

    def __queueFinishedHandler(self, hasArchiveMovies):
        if hasArchiveMovies is True:
            self.showMessage(_("MovieArchiver: Archiving finished."), 5)
        else:
            self.showMessage(_("MovieArchiver: Movies already archived."), 5)

    def __infoMsgHandler(self, msg, timeout=10):
        if self.showUIMessage is True:
            self.showMessage(msg, timeout)
        else:
            printToConsole(msg)


class MovieManager(MAglobs, object):  # classdocs
    def __init__(self):  # Constructor
        self.execCommand = ""
        self.executionQueueList = deque()
        self.executionQueueListInProgress = False
        self.console = eConsoleAppContainer()
        self.console.appClosed.append(self.__runFinished)

    def running(self):
        return self.executionQueueListInProgress

    def startArchiving(self):
        if self.mountpoint(getSourcePathValue()) == self.mountpoint(getTargetPathValue()):
            self.dispatchEvent(self.INFO_MSG, _("Stop archiving!\nCan't archive movies to the same hard drive!!\nPlease change the paths in the MovieArchiver settings."), 10)
            return

        if config.plugins.MovieArchiver.skipDuringRecords.getValue() and self.isRecordingStartInNextTime():
            self.dispatchEvent(self.INFO_MSG, _("Skip archiving!\nA record is running or start in the next minutes."), 10)
            return

        if self.reachedLimit(getTargetPathValue(), config.plugins.MovieArchiver.targetLimit.getValue()):
            msg = _("Stop archiving!\nCan't archive movie because archive-harddisk limit reached!")
            printToConsole(msg)
            if config.plugins.MovieArchiver.showLimitReachedNotification.getValue():
                self.dispatchEvent(self.INFO_MSG, msg, 20)
            return

        if config.plugins.MovieArchiver.backup.getValue():
            self.backupFiles(getSourcePathValue(), getTargetPathValue())
        else:
            self.archiveMovies()

    def stopArchiving(self):
        if self.running():  # current move or copy process doesnt canceled. only queue is cleared
            self.__clearExecutionQueueList()

    def archiveMovies(self):
        tries = 0  # archiving movies
        moviesFileSize = 0
        if self.reachedLimit(getSourcePathValue(), config.plugins.MovieArchiver.sourceLimit.getValue()):
            files = self.getFiles(getSourcePathValue(), self.MOVIE_EXTENSION_TO_ARCHIVE)
            if files:
                for file in files:
                    moviesFileSize += getsize(file) // 1024 // 1024
                    # Source Disk: check if its enough that we move only this file
                    breakMoveNext = self.checkReachedLimitIfMoveFile(getSourcePathValue(), config.plugins.MovieArchiver.sourceLimit.getValue(), moviesFileSize)
                    self.addMovieToArchiveQueue(file)
                    if breakMoveNext or tries > self.MAX_TRIES:
                        break
                    # Target Disk: check if limit is reached if we move this file
                    breakMoveNext = self.checkReachedLimitIfMoveFile(getTargetPathValue(), config.plugins.MovieArchiver.targetLimit.getValue(), moviesFileSize)
                    if breakMoveNext is False:
                        break
                    tries += 1
                self.dispatchEvent(self.INFO_MSG, _("Start archiving."), 5)
                self.execQueue()
        else:
            self.dispatchEvent(self.INFO_MSG, _("limit not reached. Wait for next Event."), 5)

    def backupFiles(self, sourcePath, targetPath):
        if self.pathIsWriteable(targetPath) is False:  # sync files, check if target path is writable
            self.dispatchEvent(self.INFO_MSG, _("Backup Target Folder is not writable.\nPlease check the permission."), 10)
            return
        # check if some files to archive available
        sourceFiles = self.getFilesWithNameKey(sourcePath, excludedDirNames=self.DEFAULT_EXCLUDED_DIRNAMES, excludeDirs=config.plugins.MovieArchiver.excludeDirs.getValue())
        if sourceFiles is None:
            self.dispatchEvent(self.INFO_MSG, _("No files for backup found."), 10)
            return
        self.dispatchEvent(self.INFO_MSG, _("Backup Archive. Synchronization started"), 5)
        targetFiles = self.getFilesWithNameKey(targetPath, excludedDirNames=self.DEFAULT_EXCLUDED_DIRNAMES)
        for sFileName, sFile in iteritems(sourceFiles):  # determine movies to sync and add to queue
            if sFileName not in targetFiles:
                printToConsole("file is new. Add To Archive: " + sFile)
                self.addFileToBackupQueue(sFile)
            else:
                tFile = targetFiles[sFileName]
                if self.getFileHash(tFile) != self.getFileHash(sFile):
                    printToConsole("file is different. Add to Archive: " + sFile)
                    self.addFileToBackupQueue(sFile)
        if len(self.executionQueueList) < 1:
            self.dispatchEvent(self.QUEUE_FINISHED, False)
        else:
            self.execQueue()

    def addFileToBackupQueue(self, sourceFile):
        targetPath = getTargetPathValue()
        if isdir(targetPath) and dirname(sourceFile) != targetPath and self.pathIsWriteable(targetPath):
            subFolderPath = sourceFile.replace(getSourcePathValue(), "")
            targetPathWithSubFolder = join(targetPath, subFolderPath)
            newExecCommand = 'cp "' + sourceFile + '" "' + targetPathWithSubFolder + '"'
            folder = dirname(targetPathWithSubFolder)  # create folders if doesnt exists
            if exists(folder) is False:
                makedirs(folder)
            self.__addExecCommandToArchiveQueue(newExecCommand)

    def addMovieToArchiveQueue(self, sourceMovie):
        targetPath = getTargetPathValue()
        if isdir(targetPath) and dirname(sourceMovie) != targetPath and self.pathIsWriteable(targetPath):
            fileNameWithoutExtension = splitext(sourceMovie)[0]
            newExecCommand = 'mv "' + fileNameWithoutExtension + '."* "' + targetPath + '"'
            self.__addExecCommandToArchiveQueue(newExecCommand)

    def execQueue(self):
        try:
            if len(self.executionQueueList) > 0:
                self.executionQueueListInProgress = True
                self.execCommand = self.executionQueueList.popleft()
                self.console.execute("sh -c " + self.execCommand)
                printToConsole("execQueue: Move Movie '" + self.execCommand + "'")
        except Exception as e:
            self.__clearExecutionQueueList()
            printToConsole("execQueue exception:\n" + str(e))

    def isRecordingStartInNextTime(self):
        recordings = len(NavigationInstance.instance.getRecordings())
        nextRecordingTime = NavigationInstance.instance.RecordTimer.getNextRecordingTime()
        return False if not recordings and (((nextRecordingTime - time()) > self.SECONDS_NEXT_RECORD) or nextRecordingTime < 0) else True

    def __clearExecutionQueueList(self):  # Private Methods
        self.execCommand = ""
        self.executionQueueList = deque()
        self.executionQueueListInProgress = False

    def __runFinished(self, retval=None):
        try:
            self.execCommand = ""
            if len(self.executionQueueList) > 0:
                self.execQueue()
            else:
                printToConsole("Queue finished!")
                self.executionQueueListInProgress = False
                self.dispatchEvent(self.QUEUE_FINISHED, True)
        except Exception as e:
            self.__clearExecutionQueueList()
            printToConsole("runFinished exception:\n" + str(e))

    def __addExecCommandToArchiveQueue(self, execCommandToAdd):
        # add ExecCommand to executionQueueList if not in list
        # if self.execCommand != execCommandToAdd and self.executionQueueList.count(execCommandToAdd) == 0:
        if self.execCommand != execCommandToAdd and execCommandToAdd not in self.executionQueueList:
            self.executionQueueList.append(quote(execCommandToAdd))


class ExcludeDirsView(Screen):
    skin = """
        <screen name="ExcludeDirsView" position="center,center" size="560,400" resolution="1280,720" title="Select folders to exclude">
            <widget name="excludeDirList" position="5,0" size="550,320" transparent="1" scrollbarMode="showOnDemand" />
            <widget source="key_red" render="Label" font="Regular; 20" foregroundColor="unffffff" backgroundColor="#20000000" halign="left" position="20,365" size="250,33" transparent="1" />
            <widget source="key_green" render="Label" font="Regular; 20" foregroundColor="unffffff" backgroundColor="#20000000" halign="left" position="185,365" size="250,33" transparent="1" />
            <widget source="key_yellow" render="Label" font="Regular; 20" foregroundColor="unffffff" backgroundColor="#20000000" halign="left" position="335,365" size="250,33" transparent="1" />
            <eLabel position="5,360" size="5,40" backgroundColor="#e61700" />
            <eLabel position="170,360" size="5,40" backgroundColor="#61e500" />
            <eLabel position="320,360" size="5,40" backgroundColor="#e5dd00" />
        </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self["key_red"] = StaticText(_("Cancel"))
        self["key_green"] = StaticText(_("Save"))
        self["key_yellow"] = StaticText()
        self.excludedDirs = config.plugins.MovieArchiver.excludeDirs.getValue()
        self.dirList = MultiFileSelectList(self.excludedDirs, getSourcePathValue(), showFiles=False)
        self["excludeDirList"] = self.dirList
        self["actions"] = ActionMap(["DirectionActions", "OkCancelActions", "ShortcutActions"],
                                    {
                                        "cancel": self.exit,
                                        "red": self.exit,
                                        "yellow": self.changeSelectionState,
                                        "green": self.saveSelection,
                                        "ok": self.okClicked,
                                        "left": self.left,
                                        "right": self.right,
                                        "down": self.down,
                                        "up": self.up
                                    }, -1)
        if self.selectionChanged not in self["excludeDirList"].onSelectionChanged:
            self["excludeDirList"].onSelectionChanged.append(self.selectionChanged)
        self.onLayoutFinish.append(self.layoutFinished)

    def layoutFinished(self):
        idx = 0
        self["excludeDirList"].moveToIndex(idx)
        self.setWindowTitle()
        self.selectionChanged()

    def setWindowTitle(self):
        self.setTitle(_("Select Exclude Dirs"))

    def selectionChanged(self):
        current = self["excludeDirList"].getCurrent()[0]
        self["key_yellow"].setText(_("Deselect") if current[2] is True else _("Select"))

    def up(self):
        self["excludeDirList"].up()

    def down(self):
        self["excludeDirList"].down()

    def left(self):
        self["excludeDirList"].pageUp()

    def right(self):
        self["excludeDirList"].pageDown()

    def changeSelectionState(self):
        self["excludeDirList"].changeSelectionState()
        self.excludedDirs = self["excludeDirList"].getSelectedList()

    def saveSelection(self):
        self.excludedDirs = self["excludeDirList"].getSelectedList()
        self.excludedDirs = self.removeSymbolicLinks(self.excludedDirs)
        config.plugins.MovieArchiver.excludeDirs.setValue(self.excludedDirs)
        config.plugins.MovieArchiver.excludeDirs.save()
        config.plugins.MovieArchiver.save()
        config.save()
        self.close(None)

    def exit(self):
        self.close(None)

    def okClicked(self):
        if self.dirList.canDescent():
            self.dirList.descent()


class MovieArchiverView(ConfigListScreen, Screen):
    skin = """
        <screen name="MovieArchiver-Setup" position="center,center" size="1000,500" resolution="1280,720" flags="wfNoBorder" backgroundColor="#90000000">
            <eLabel name="new eLabel" position="0,0" zPosition="-2" size="630,500" backgroundColor="#20000000" transparent="0" />
            <eLabel font="Regular;20" foregroundColor="unffffff" backgroundColor="#20000000" halign="left" position="37,465" size="250,33" text="Cancel" transparent="1" />
            <eLabel font="Regular;20" foregroundColor="unffffff" backgroundColor="#20000000" halign="left" position="235,465" size="250,33" text="Save" transparent="1" />
            <widget source="archiveButton" render="Label" font="Regular;20" foregroundColor="unffffff" backgroundColor="#20000000" halign="left" position="432,465" size="250,33" transparent="1" />
            <widget name="config" position="21,74" size="590,360" font="Regular;20" scrollbarMode="showOnDemand" transparent="1" />
            <eLabel name="new eLabel" position="640,0" zPosition="-2" size="360,500" backgroundColor="#20000000" transparent="0" />
            <widget source="help" render="Label" position="660,74" size="320,460" font="Regular;20" />
            <eLabel position="660,15" size="360,50" text="Help" font="Regular;40" valign="center" transparent="1" backgroundColor="#20000000" />
            <eLabel position="20,15" size="348,50" text="MovieArchiver" font="Regular;40" valign="center" transparent="1" backgroundColor="#20000000" />
            <eLabel position="303,18" size="349,50" text="Setup" foregroundColor="unffffff" font="Regular;30" valign="center" backgroundColor="#20000000" transparent="1" halign="left" />
            <eLabel position="415,460" size="5,40" backgroundColor="#e5dd00" />
            <eLabel position="220,460" size="5,40" backgroundColor="#61e500" />
            <eLabel position="20,460" size="5,40" backgroundColor="#e61700" />
            <eLabel text="by svox" position="42,8" size="540,25" zPosition="1" font="Regular;15" halign="right" valign="top" backgroundColor="#20000000" transparent="1" />
        </screen>"""

    def __init__(self, session, args=None):
        Screen.__init__(self, session)
        getSourcePath().addNotifier(self.checkReadWriteDir, initial_call=False, immediate_feedback=False)
        getTargetPath().addNotifier(self.checkReadWriteDir, initial_call=False, immediate_feedback=False)
        self.onChangedEntry = []
        ConfigListScreen.__init__(self, self.getMenuItemList(), session=session, on_change=self.__changedEntry)
        self["help"] = StaticText()
        self["archiveButton"] = StaticText()
        self.notificationController = NotificationController.getInstance()
        self.notificationController.setView(self)
        self["actions"] = ActionMap(["SetupActions",
                                     "OkCancelActions",
                                     "ColorActions"], {"cancel": self.cancel,
                                                       "save": self.save,
                                                       "ok": self.ok,
                                                       "yellow": self.yellow,
                                                       }, -2)
        self.onLayoutFinish.append(self.onLayoutFinished)

    def onLayoutFinished(self):
        try:
            if self.selectionChanged not in self["config"].onSelectionChanged:
                self["config"].onSelectionChanged.append(self.__updateHelp)
        except Exception:
            self["config"].onSelectionChanged.append(self.__updateHelp)
        self['config'].l.setItemHeight(int(30 * 1.5 if getDesktop(0).size().height() > 720 else 1.0))
        self.__updateArchiveNowButtonText()
        if self.notificationController.isArchiving() is True:
            self.addEventListener(self.QUEUE_FINISHED, self.__archiveFinished)
        self.onClose.append(self.__onClose)

    def getMenuItemList(self):
        menuList = []
        menuList.append(getConfigListEntry(_("Archive automatically"), config.plugins.MovieArchiver.enabled, _("If yes, the MovieArchiver automatically moved or copied (if 'Backup Movies' is on) movies to archive folder if limit is reached")))
        menuList.append(getConfigListEntry(_("Backup Movies instead of Archive"), config.plugins.MovieArchiver.backup, _("If yes, the movies will only be copy to the archive movie folder and not moved.\n\nCurrently for synchronize, it comparing only fileName and fileSize."), 'BACKUP'))
        menuList.append(getConfigListEntry(_("Skip archiving during records"), config.plugins.MovieArchiver.skipDuringRecords, _("If a record is in progress or start in the next minutes after a record, the archiver skipped till the next record")))
        menuList.append(getConfigListEntry(_("Show notification if archive limit reached"), config.plugins.MovieArchiver.showLimitReachedNotification, _("Show notification window message if 'Archive Movie Folder Limit' is reached")))
        menuList.append(getConfigListEntry(_("-------------------------------------------------------------"), ))
        menuList.append(getConfigListEntry(_("Movie Folder"), getSourcePath(), _("Source folder / HDD\n\nPress 'Ok' to open path selection view")))
        menuList.append(getConfigListEntry(_("Movie Folder Limit (in GB)"), config.plugins.MovieArchiver.sourceLimit, _("Movie Folder free diskspace limit in GB. If free diskspace reach under this limit, the MovieArchiver will move old records to the archive")))
        if config.plugins.MovieArchiver.backup.getValue() is True:
            menuList.append(getConfigListEntry(_("Exclude folders"), config.plugins.MovieArchiver.excludeDirs, _("Selected Directories wont be backuped.")))
        menuList.append(getConfigListEntry(_("-------------------------------------------------------------"), ))
        menuList.append(getConfigListEntry(_("Archive Folder"), getTargetPath(), _("Target folder / HDD where the movies will moved or backuped.\n\nPress 'Ok' to open path selection view")))
        menuList.append(getConfigListEntry(_("Archive Folder Limit (in GB)"), config.plugins.MovieArchiver.targetLimit, _("If limit is reach, no movies will anymore moved to the archive")))
        return menuList

    def checkReadWriteDir(self, configElement):  # callback for path-browser
        if self.pathIsWriteable(configElement.getValue()):
            configElement.lastValue = configElement.getValue()
            return True
        else:
            dirName = configElement.getValue()
            configElement.value = configElement.lastValue
            self.session.open(MessageBox, _("The directory %s is not writable.\nMake sure you select a writable directory instead.") % dirName, MessageBox.TYPE_ERROR)
            return False

    def yellow(self):
        if self.notificationController.isArchiving() is True:
            self.notificationController.stopArchiving()
        else:
            self.notificationController.startArchiving(True)
        self.__updateArchiveNowButtonText()

    def excludedDirsChoosen(self, ret):
        config.plugins.MovieArchiver.excludeDirs.save()
        config.plugins.MovieArchiver.save()
        # config.save()

    def ok(self):
        cur = self.getCurrent()
        if cur == getSourcePath() or cur == getTargetPath():
            self.chooseDestination()
        elif cur == config.plugins.MovieArchiver.excludeDirs:
            self.session.openWithCallback(self.excludedDirsChoosen, ExcludeDirsView)
        else:
            ConfigListScreen.keyOK(self)

    def cancel(self):
        self.clean()

        for x in self["config"].list:
            if len(x) > 1:
                x[1].cancel()
        self.close()

    def save(self):
        self.clean()

        for x in self["config"].list:
            if len(x) > 1:
                # skip ConfigLocations because it doesnt accept default = None
                # All other forms override default and force to save values that wasn't changed by user
                # if isinstance(x[1], ConfigLocations) is False:
                #   x[1].default = None
                x[1].save_forced = True
                x[1].save()

        if config.plugins.MovieArchiver.enabled.getValue():
            self.notificationController.start()
        else:
            self.notificationController.stop()

        configfile.save()
        self.close()

    def clean(self):
        getSourcePath().clearNotifiers()
        getTargetPath().clearNotifiers()

    def getCurrent(self):
        cur = self["config"].getCurrent()
        cur = cur and cur[1]
        return cur

    def pathSelected(self, res):
        if res is not None:
            pathInput = self.getCurrent()
            pathInput.setValue(res)

    def chooseDestination(self):
        self.session.openWithCallback(self.pathSelected, MovieLocationBox, _("Choose folder"), self.getCurrent().getValue(), minFree=100)

    def __updateArchiveNowButtonText(self):  # Private Methods
        if self.notificationController.isArchiving() is True:
            archiveButtonText = _("Stop Backup") if config.plugins.MovieArchiver.backup.getValue() is True else _("Stop archiving")
        else:
            archiveButtonText = _("Backup now!") if config.plugins.MovieArchiver.backup.getValue() is True else _("Archive now!")
        self["archiveButton"].setText(archiveButtonText)

    def __archiveFinished(self):
        self.__updateArchiveNowButtonText()

    def __updateHelp(self):
        cur = self["config"].getCurrent()
        if cur:
            self["help"].text = cur[2]

    def __changedEntry(self):
        cur = self["config"].getCurrent()
        cur = cur and len(cur) > 3 and cur[3]
        if cur == "BACKUP":  # change if type is BACKUP
            self["config"].setList(self.getMenuItemList())

    def __onClose(self):
        self.notificationController.setView(None)


def autostart(reason, **kwargs):  # Autostart
    global notificationController
    if reason == 0:  # Startup
        try:
            notificationController = NotificationController.getInstance()
            notificationController.start()
        except Exception as e:
            printToConsole("Autostart exception " + str(e))
            exc_type, exc_value, exc_traceback = exc_info()
            print_exception(exc_type, exc_value, exc_traceback, file=stdout)
    elif reason == 1:  # Shutdown
        if MAglobs.notificationController is not None:  # Stop NotificationController
            MAglobs.notificationController.stop()
            notificationController = None


def main(session, **kwargs):
    session.open(MovieArchiverView)


def Plugins(**kwargs):
    pluginList = [PluginDescriptor(where=PluginDescriptor.WHERE_AUTOSTART, fnc=autostart, needsRestart=False),
                  PluginDescriptor(name="MovieArchiver", description=_("Archive or backup your movies"), where=PluginDescriptor.WHERE_PLUGINMENU, icon="plugin.png", fnc=main, needsRestart=False)]
    return pluginList
