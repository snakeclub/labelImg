#!/usr/bin/env python
# -*- coding: utf-8 -*-
import codecs
import distutils.spawn
import os.path
import platform
import re
import sys
import subprocess
import json

from functools import partial
from collections import defaultdict

try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
except ImportError:
    # needed for py3+qt4
    # Ref:
    # http://pyqt.sourceforge.net/Docs/PyQt4/incompatible_apis.html
    # http://stackoverflow.com/questions/21217399/pyqt4-qtcore-qvariant-object-instead-of-a-string
    if sys.version_info.major >= 3:
        import sip
        sip.setapi('QVariant', 2)
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

from combobox import ComboBox
from libs.resources import *
from libs.constants import *
from libs.utils import *
from libs.settings import Settings
from libs.shape import Shape, DEFAULT_LINE_COLOR, DEFAULT_FILL_COLOR
from libs.stringBundle import StringBundle
from libs.canvas import Canvas
from libs.zoomWidget import ZoomWidget
from libs.labelDialog import LabelDialog
from libs.colorDialog import ColorDialog
from libs.labelFile import LabelFile, LabelFileError
from libs.toolBar import ToolBar
from libs.pascal_voc_io import PascalVocReader
from libs.pascal_voc_io import XML_EXT
from libs.yolo_io import YoloReader
from libs.yolo_io import TXT_EXT
from libs.ustr import ustr
from libs.hashableQListWidgetItem import HashableQListWidgetItem

# 扩展专用的类库
import copy
from libs.extend import ExtendLib, TFRecordCreater, TFObjectDetect
from libs.cclib import CommonLib
from HiveNetLib.base_tools.run_tool import RunTool
from HiveNetLib.base_tools.file_tool import FileTool

__appname__ = 'labelImg - Extend by Li Huijian'


class WindowMixin(object):

    def menu(self, title, actions=None):
        menu = self.menuBar().addMenu(title)
        if actions:
            addActions(menu, actions)
        return menu

    def toolbar(self, title, actions=None):
        toolbar = ToolBar(title)
        toolbar.setObjectName(u'%sToolBar' % title)
        # toolbar.setOrientation(Qt.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        if actions:
            addActions(toolbar, actions)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        return toolbar


class MainWindow(QMainWindow, WindowMixin):
    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = list(range(3))

    def __init__(self, defaultFilename=None, defaultPrefdefClassFile=None, defaultSaveDir=None):
        super(MainWindow, self).__init__()
        self.setWindowTitle(__appname__)

        # Load setting in the main thread
        self.settings = Settings()
        self.settings.load()
        settings = self.settings

        # Load string bundle for i18n
        # 替换这个为使用中文
        # self.stringBundle = StringBundle.getBundle()
        self.stringBundle = StringBundle.getBundle('zh-CN')
        def getStr(strId): return self.stringBundle.getString(strId)

        # 映射字典
        self.mapping = self.get_mapping_dict()

        # 自动标注配置
        self.auto_label = self.get_tf_auto_label()
        self.auto_label_tool = TFObjectDetect(
            self.auto_label, self.mapping, os.path.split(__file__)[0]
        )

        # Save as Pascal voc xml
        self.defaultSaveDir = defaultSaveDir
        self.usingPascalVocFormat = True
        self.usingYoloFormat = False

        # For loading all image under a directory
        self.mImgList = []
        self.dirname = None
        self.labelHist = []
        self.lastOpenDir = None

        # Whether we need to save or not.
        self.dirty = False

        self._noSelectionSlot = False
        self._beginner = True
        self.screencastViewer = self.getAvailableScreencastViewer()
        self.screencast = "https://youtu.be/p0nR2YsCY_U"

        # Load predefined classes to the list
        self.loadPredefinedClasses(defaultPrefdefClassFile)

        # Main widgets and related state.
        self.labelDialog = LabelDialog(parent=self, listItem=self.labelHist)

        self.itemsToShapes = {}
        self.shapesToItems = {}
        self.prevLabelText = ''

        listLayout = QVBoxLayout()
        listLayout.setContentsMargins(0, 0, 0, 0)

        # Create a widget for using default label
        self.useDefaultLabelCheckbox = QCheckBox(getStr('useDefaultLabel'))
        self.useDefaultLabelCheckbox.setChecked(True)  # 默认选中使用默认Label
        self.defaultLabelTextLine = QLineEdit()
        self.defaultLabelTextLine.setText(self.mapping.get('defalut_class', ''))
        useDefaultLabelQHBoxLayout = QHBoxLayout()
        useDefaultLabelQHBoxLayout.addWidget(self.useDefaultLabelCheckbox)
        useDefaultLabelQHBoxLayout.addWidget(self.defaultLabelTextLine)
        useDefaultLabelContainer = QWidget()
        useDefaultLabelContainer.setLayout(useDefaultLabelQHBoxLayout)

        # Create a widget for edit and diffc button
        self.diffcButton = QCheckBox(getStr('useDifficult'))
        self.diffcButton.setChecked(False)
        self.diffcButton.stateChanged.connect(self.btnstate)
        self.editButton = QToolButton()
        self.editButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        # 添加一个删除是否提示的checkbox
        self.deleteWarningButton = QCheckBox('删除对象告警提示')
        self.deleteWarningButton.setChecked(True)

        # 添加新增信息文件的按钮
        self.newSelfInfoButton = QPushButton('添加独有信息文件')
        self.newInfoButton = QPushButton('添加公共信息文件')
        self.newSelfInfoButton.clicked.connect(self.newSelfInfoButton_click)
        self.newInfoButton.clicked.connect(self.newInfoButton_click)

        # Add some of widgets to listLayout
        listLayout.addWidget(self.editButton)
        listLayout.addWidget(self.diffcButton)
        listLayout.addWidget(self.deleteWarningButton)
        listLayout.addWidget(useDefaultLabelContainer)
        listLayout.addWidget(self.newSelfInfoButton)
        listLayout.addWidget(self.newInfoButton)

        # Create and add combobox for showing unique labels in group
        self.comboBox = ComboBox(self)
        listLayout.addWidget(self.comboBox)

        # 添加自定义的商品信息展示表格
        self.productInfo = QListWidget()
        self.productInfo.doubleClicked.connect(self.product_item_double_clicked)
        listLayout.addWidget(self.productInfo)

        # Create and add a widget for showing current label items
        self.labelList = QListWidget()
        labelListContainer = QWidget()
        labelListContainer.setLayout(listLayout)
        self.labelList.itemActivated.connect(self.labelSelectionChanged)
        self.labelList.itemSelectionChanged.connect(self.labelSelectionChanged)
        self.labelList.itemDoubleClicked.connect(self.editLabel)
        # Connect to itemChanged to detect checkbox changes.
        self.labelList.itemChanged.connect(self.labelItemChanged)
        listLayout.addWidget(self.labelList)

        self.dock = QDockWidget(getStr('boxLabelText'), self)
        self.dock.setObjectName(getStr('labels'))
        self.dock.setWidget(labelListContainer)

        self.fileListWidget = QListWidget()
        self.fileListWidget.itemDoubleClicked.connect(self.fileitemDoubleClicked)
        filelistLayout = QVBoxLayout()
        filelistLayout.setContentsMargins(0, 0, 0, 0)
        filelistLayout.addWidget(self.fileListWidget)
        fileListContainer = QWidget()
        fileListContainer.setLayout(filelistLayout)
        self.filedock = QDockWidget(getStr('fileList'), self)
        self.filedock.setObjectName(getStr('files'))
        self.filedock.setWidget(fileListContainer)

        self.zoomWidget = ZoomWidget()
        self.colorDialog = ColorDialog(parent=self)

        self.canvas = Canvas(parent=self)
        self.canvas.zoomRequest.connect(self.zoomRequest)
        self.canvas.setDrawingShapeToSquare(settings.get(SETTING_DRAW_SQUARE, False))

        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        self.scrollBars = {
            Qt.Vertical: scroll.verticalScrollBar(),
            Qt.Horizontal: scroll.horizontalScrollBar()
        }
        self.scrollArea = scroll
        self.canvas.scrollRequest.connect(self.scrollRequest)

        self.canvas.newShape.connect(self.newShape)
        self.canvas.shapeMoved.connect(self.setDirty)
        self.canvas.selectionChanged.connect(self.shapeSelectionChanged)
        self.canvas.drawingPolygon.connect(self.toggleDrawingSensitive)
        # 与画布的方法关联
        self.canvas.openPrevDir.connect(self.openPrevDir)
        self.canvas.openNextDir.connect(self.openNextDir)
        self.canvas.openPrevImg.connect(self.openPrevImg)
        self.canvas.openNextImg.connect(self.openNextImg)
        self.canvas.deleteCurrentFile.connect(self.deleteCurrentFile)

        self.setCentralWidget(scroll)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.filedock)
        self.filedock.setFeatures(QDockWidget.DockWidgetFloatable)

        self.dockFeatures = QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetFloatable
        self.dock.setFeatures(self.dock.features() ^ self.dockFeatures)

        # Actions
        action = partial(newAction, self)

        # 添加扩展菜单
        imageDeal = action('处理图片', self.imageDeal, '',
                           'imageDeal', '处理图片,包括转换格式和删除非RGB格式图片')

        imageRename = action('批量重命名', self.imageRename, '',
                             'imageRename', '批量重命名文件夹中的图片')

        imageCropByTag = action('按标注截图', self.imageCropByTag, '',
                                'imageCropByTag', '根据图像标注截图保存，如果没有标注则复制完整文件')

        copyFlagsPics = action('按标注复制文件', self.copyFlagsPics, '',
                               'copyFlagsPics', '按标注将文件复制到指定文件夹')

        countFlags = action('标注统计', self.countFlags, '',
                            'countFlags', '统计指定目录中的labelimg标记对应标签的数量')

        createPbtxt = action('生成labelmap.pbtxt文件', self.createPbtxt, '',
                             'createPbtxt', '根据mapping.json文件生成对应的labelmap.pbtxt文件')

        labelimgToTFRecord = action('LabelImg生成TFRecord', self.labelimg_to_tfrecord, '',
                                    'labelimgToTFRecord', '将LabelImg的标注生成TFRecord文件')

        # 添加CC自定义菜单
        # getDomTag = action('解析商品信息', self.dealDomFile, '',
        #                    'getDomTag', '将解析当前文件清单的Dom文件生成商品信息')

        # createProductXls = action('生成商品信息汇总', self.create_info_xls_file, '',
        #                           'createProductXls', '将当前目录的产品信息生成excel汇总文件')

        # cleanProductFiles = action('清理商品文件', self.clean_product_files, '',
        #                            'cleanProductFiles', '清理商品文件内容')

        quit = action(getStr('quit'), self.close,
                      'Ctrl+Q', 'quit', getStr('quitApp'))

        open = action(getStr('openFile'), self.openFile,
                      'Ctrl+O', 'open', getStr('openFileDetail'))

        opendir = action(getStr('openDir'), self.openDirDialog,
                         'Ctrl+u', 'open', getStr('openDir'))

        changeSavedir = action(getStr('changeSaveDir'), self.changeSavedirDialog,
                               'Ctrl+r', 'open', getStr('changeSavedAnnotationDir'))

        openAnnotation = action(getStr('openAnnotation'), self.openAnnotationDialog,
                                'Ctrl+Shift+O', 'open', getStr('openAnnotationDetail'))

        openNextImg = action(getStr('nextImg'), self.openNextImg,
                             'd', 'next', getStr('nextImgDetail'))

        openPrevImg = action(getStr('prevImg'), self.openPrevImg,
                             'a', 'prev', getStr('prevImgDetail'))

        verify = action(getStr('verifyImg'), self.verifyImg,
                        'space', 'verify', getStr('verifyImgDetail'))

        save = action(getStr('save'), self.saveFile,
                      'Ctrl+S', 'save', getStr('saveDetail'), enabled=False)

        save_format = action('&PascalVOC', self.change_format,
                             'Ctrl+', 'format_voc', getStr('changeSaveFormat'), enabled=True)

        saveAs = action(getStr('saveAs'), self.saveFileAs,
                        'Ctrl+Shift+S', 'save-as', getStr('saveAsDetail'), enabled=False)

        close = action(getStr('closeCur'), self.closeFile,
                       'Ctrl+W', 'close', getStr('closeCurDetail'))

        resetAll = action(getStr('resetAll'), self.resetAll, None,
                          'resetall', getStr('resetAllDetail'))

        color1 = action(getStr('boxLineColor'), self.chooseColor1,
                        'Ctrl+L', 'color_line', getStr('boxLineColorDetail'))

        createMode = action(getStr('crtBox'), self.setCreateMode,
                            'w', 'new', getStr('crtBoxDetail'), enabled=False)
        editMode = action('&Edit\nRectBox', self.setEditMode,
                          'Ctrl+J', 'edit', u'Move and edit Boxs', enabled=False)

        create = action(getStr('crtBox'), self.createShape,
                        'w', 'new', getStr('crtBoxDetail'), enabled=False)
        delete = action(getStr('delBox'), self.deleteSelectedShape,
                        'Delete', 'delete', getStr('delBoxDetail'), enabled=False)

        # 标注列表框右键增加添加自动标注的功能
        add_auto = action('添加当前自动标注', self.addSelectedAutoShape,
                          'Add_auto', 'add_auto', '将当前选中的自动标注添加为标注', enabled=True)

        add_auto_all = action('添加所有勾选自动标注', self.addAllSelectedAutoShape,
                              'Add_auto_all', 'add_auto_all', '将当前勾选的所有自动标注添加为标注', enabled=True)

        copy = action(getStr('dupBox'), self.copySelectedShape,
                      'Ctrl+D', 'copy', getStr('dupBoxDetail'),
                      enabled=False)

        advancedMode = action(getStr('advancedMode'), self.toggleAdvancedMode,
                              'Ctrl+Shift+A', 'expert', getStr('advancedModeDetail'),
                              checkable=True)

        hideAll = action('&Hide\nRectBox', partial(self.togglePolygons, False),
                         'Ctrl+H', 'hide', getStr('hideAllBoxDetail'),
                         enabled=False)
        showAll = action('&Show\nRectBox', partial(self.togglePolygons, True),
                         'Ctrl+A', 'hide', getStr('showAllBoxDetail'),
                         enabled=False)

        help = action(getStr('tutorial'), self.showTutorialDialog,
                      None, 'help', getStr('tutorialDetail'))
        showInfo = action(getStr('info'), self.showInfoDialog, None, 'help', getStr('info'))

        zoom = QWidgetAction(self)
        zoom.setDefaultWidget(self.zoomWidget)
        self.zoomWidget.setWhatsThis(
            u"Zoom in or out of the image. Also accessible with"
            " %s and %s from the canvas." % (fmtShortcut("Ctrl+[-+]"),
                                             fmtShortcut("Ctrl+Wheel")))
        self.zoomWidget.setEnabled(False)

        zoomIn = action(getStr('zoomin'), partial(self.addZoom, 10),
                        'Ctrl++', 'zoom-in', getStr('zoominDetail'), enabled=False)
        zoomOut = action(getStr('zoomout'), partial(self.addZoom, -10),
                         'Ctrl+-', 'zoom-out', getStr('zoomoutDetail'), enabled=False)
        zoomOrg = action(getStr('originalsize'), partial(self.setZoom, 100),
                         'Ctrl+=', 'zoom', getStr('originalsizeDetail'), enabled=False)
        fitWindow = action(getStr('fitWin'), self.setFitWindow,
                           'Ctrl+F', 'fit-window', getStr('fitWinDetail'),
                           checkable=True, enabled=False)
        fitWidth = action(getStr('fitWidth'), self.setFitWidth,
                          'Ctrl+Shift+F', 'fit-width', getStr('fitWidthDetail'),
                          checkable=True, enabled=False)
        # Group zoom controls into a list for easier toggling.
        zoomActions = (self.zoomWidget, zoomIn, zoomOut,
                       zoomOrg, fitWindow, fitWidth)
        self.zoomMode = self.MANUAL_ZOOM
        self.scalers = {
            self.FIT_WINDOW: self.scaleFitWindow,
            self.FIT_WIDTH: self.scaleFitWidth,
            # Set to one to scale to 100% when loading files.
            self.MANUAL_ZOOM: lambda: 1,
        }

        edit = action(getStr('editLabel'), self.editLabel,
                      'Ctrl+E', 'edit', getStr('editLabelDetail'),
                      enabled=False)
        self.editButton.setDefaultAction(edit)

        shapeLineColor = action(getStr('shapeLineColor'), self.chshapeLineColor,
                                icon='color_line', tip=getStr('shapeLineColorDetail'),
                                enabled=False)
        shapeFillColor = action(getStr('shapeFillColor'), self.chshapeFillColor,
                                icon='color', tip=getStr('shapeFillColorDetail'),
                                enabled=False)

        labels = self.dock.toggleViewAction()
        labels.setText(getStr('showHide'))
        labels.setShortcut('Ctrl+Shift+L')

        # Label list context menu.
        labelMenu = QMenu()
        addActions(labelMenu, (edit, delete, add_auto, add_auto_all))
        self.labelList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.labelList.customContextMenuRequested.connect(
            self.popLabelListMenu)

        # Draw squares/rectangles
        self.drawSquaresOption = QAction('Draw Squares', self)
        self.drawSquaresOption.setShortcut('Ctrl+Shift+R')
        self.drawSquaresOption.setCheckable(True)
        self.drawSquaresOption.setChecked(settings.get(SETTING_DRAW_SQUARE, False))
        self.drawSquaresOption.triggered.connect(self.toogleDrawSquare)

        # Store actions for further handling.
        self.actions = struct(save=save, save_format=save_format, saveAs=saveAs, open=open, close=close, resetAll=resetAll,
                              lineColor=color1, create=create, delete=delete, edit=edit, copy=copy,
                              createMode=createMode, editMode=editMode, advancedMode=advancedMode,
                              shapeLineColor=shapeLineColor, shapeFillColor=shapeFillColor,
                              zoom=zoom, zoomIn=zoomIn, zoomOut=zoomOut, zoomOrg=zoomOrg,
                              fitWindow=fitWindow, fitWidth=fitWidth,
                              zoomActions=zoomActions,
                              fileMenuActions=(
                                  open, opendir, save, saveAs, close, resetAll, quit),
                              beginner=(), advanced=(),
                              editMenu=(edit, copy, delete,
                                        None, color1, self.drawSquaresOption),
                              beginnerContext=(create, edit, copy, delete),
                              advancedContext=(createMode, editMode, edit, copy,
                                               delete, shapeLineColor, shapeFillColor),
                              onLoadActive=(
                                  close, create, createMode, editMode),
                              onShapesPresent=(saveAs, hideAll, showAll))

        # 添加一级菜单
        self.menus = struct(
            file=self.menu('&File'),
            edit=self.menu('&Edit'),
            view=self.menu('&View'),
            extend=self.menu('&Extend'),
            # cc=self.menu('&CC'),
            help=self.menu('&Help'),
            recentFiles=QMenu('Open &Recent'),
            labelList=labelMenu)

        # Auto saving : Enable auto saving if pressing next
        self.autoSaving = QAction(getStr('autoSaveMode'), self)
        self.autoSaving.setCheckable(True)
        self.autoSaving.setChecked(settings.get(SETTING_AUTO_SAVE, False))
        # Sync single class mode from PR#106
        self.singleClassMode = QAction(getStr('singleClsMode'), self)
        self.singleClassMode.setShortcut("Ctrl+Shift+S")
        self.singleClassMode.setCheckable(True)
        self.singleClassMode.setChecked(settings.get(SETTING_SINGLE_CLASS, False))
        self.lastLabel = None
        # Add option to enable/disable labels being displayed at the top of bounding boxes
        self.displayLabelOption = QAction(getStr('displayLabel'), self)
        self.displayLabelOption.setShortcut("Ctrl+Shift+P")
        self.displayLabelOption.setCheckable(True)
        self.displayLabelOption.setChecked(settings.get(SETTING_PAINT_LABEL, False))
        self.displayLabelOption.triggered.connect(self.togglePaintLabelsOption)

        # 添加子菜单
        addActions(self.menus.file,
                   (open, opendir, changeSavedir, openAnnotation, self.menus.recentFiles, save, save_format, saveAs, close, resetAll, quit))
        addActions(self.menus.help, (help, showInfo))
        addActions(self.menus.view, (
            self.autoSaving,
            self.singleClassMode,
            self.displayLabelOption,
            labels, advancedMode, None,
            hideAll, showAll, None,
            zoomIn, zoomOut, zoomOrg, None,
            fitWindow, fitWidth))

        # 扩展子菜单
        addActions(
            self.menus.extend,
            (imageDeal, imageRename, imageCropByTag, copyFlagsPics,
             countFlags, createPbtxt, labelimgToTFRecord,)
        )

        # addActions(
        #     self.menus.cc,
        #     (getDomTag, createProductXls, cleanProductFiles,)
        # )

        self.menus.file.aboutToShow.connect(self.updateFileMenu)

        # Custom context menu for the canvas widget:
        addActions(self.canvas.menus[0], self.actions.beginnerContext)
        addActions(self.canvas.menus[1], (
            action('&Copy here', self.copyShape),
            action('&Move here', self.moveShape)))

        self.tools = self.toolbar('Tools')
        self.actions.beginner = (
            open, opendir, changeSavedir, openNextImg, openPrevImg, verify, save, save_format, None, create, copy, delete, None,
            zoomIn, zoom, zoomOut, fitWindow, fitWidth)

        self.actions.advanced = (
            open, opendir, changeSavedir, openNextImg, openPrevImg, save, save_format, None,
            createMode, editMode, None,
            hideAll, showAll)

        self.statusBar().showMessage('%s started.' % __appname__)
        self.statusBar().show()

        # Application state.
        self.image = QImage()
        self.filePath = ustr(defaultFilename)
        self.recentFiles = []
        self.maxRecent = 7
        self.lineColor = None
        self.fillColor = None
        self.zoom_level = 100
        self.fit_window = False
        # Add Chris
        self.difficult = False

        # Fix the compatible issue for qt4 and qt5. Convert the QStringList to python list
        if settings.get(SETTING_RECENT_FILES):
            if have_qstring():
                recentFileQStringList = settings.get(SETTING_RECENT_FILES)
                self.recentFiles = [ustr(i) for i in recentFileQStringList]
            else:
                self.recentFiles = recentFileQStringList = settings.get(SETTING_RECENT_FILES)

        size = settings.get(SETTING_WIN_SIZE, QSize(600, 500))
        position = QPoint(0, 0)
        saved_position = settings.get(SETTING_WIN_POSE, position)
        # Fix the multiple monitors issue
        for i in range(QApplication.desktop().screenCount()):
            if QApplication.desktop().availableGeometry(i).contains(saved_position):
                position = saved_position
                break
        self.resize(size)
        self.move(position)
        # 不允许设置saveDir，声明文件统一在当前文件夹内
        # saveDir = ustr(settings.get(SETTING_SAVE_DIR, None))
        saveDir = None
        self.lastOpenDir = ustr(settings.get(SETTING_LAST_OPEN_DIR, None))
        if self.defaultSaveDir is None and saveDir is not None and os.path.exists(saveDir):
            self.defaultSaveDir = saveDir
            self.statusBar().showMessage('%s started. Annotation will be saved to %s' %
                                         (__appname__, self.defaultSaveDir))
            self.statusBar().show()

        self.restoreState(settings.get(SETTING_WIN_STATE, QByteArray()))
        Shape.line_color = self.lineColor = QColor(
            settings.get(SETTING_LINE_COLOR, DEFAULT_LINE_COLOR))
        Shape.fill_color = self.fillColor = QColor(
            settings.get(SETTING_FILL_COLOR, DEFAULT_FILL_COLOR))
        self.canvas.setDrawingColor(self.lineColor)
        # Add chris
        Shape.difficult = self.difficult

        def xbool(x):
            if isinstance(x, QVariant):
                return x.toBool()
            return bool(x)

        if xbool(settings.get(SETTING_ADVANCE_MODE, False)):
            self.actions.advancedMode.setChecked(True)
            self.toggleAdvancedMode()

        # Populate the File menu dynamically.
        self.updateFileMenu()

        # Since loading the file may take some time, make sure it runs in the background.
        if self.filePath and os.path.isdir(self.filePath):
            self.queueEvent(partial(self.importDirImages, self.filePath or ""))
        elif self.filePath:
            self.queueEvent(partial(self.loadFile, self.filePath or ""))

        # Callbacks:
        self.zoomWidget.valueChanged.connect(self.paintCanvas)

        self.populateModeActions()

        # Display cursor coordinates at the right of status bar
        self.labelCoordinates = QLabel('')
        self.statusBar().addPermanentWidget(self.labelCoordinates)

        # Open Dir if deafult file
        if self.filePath and os.path.isdir(self.filePath):
            self.openDirDialog(dirpath=self.filePath, silent=True)

    def get_mapping_dict(self):
        """
        获取预定义的映射字典
        """
        _json_file = os.path.join(os.path.split(__file__)[0], 'data', 'mapping.json')
        with open(_json_file, 'r', encoding='utf-8') as fp:
            _mapping = json.loads(fp.read())

        # 设置默认的mapping值
        for _key in _mapping[_mapping['enable_mapping']].keys():
            _mapping[_key] = _mapping[_mapping['enable_mapping']][_key]

        # 返回值
        return _mapping

    def get_tf_auto_label(self):
        """
        获取自动标注配置
        """
        _json_file = os.path.join(os.path.split(__file__)[0], 'data', 'tf_auto_label.json')
        with open(_json_file, 'r', encoding='utf-8') as fp:
            return json.loads(fp.read())

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Control:
            self.canvas.setDrawingShapeToSquare(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Control:
            # Draw rectangle if Ctrl is pressed
            self.canvas.setDrawingShapeToSquare(True)

    ## Support Functions ##

    def newSelfInfoButton_click(self):
        """
        点击新增自有信息文件（添加文件自有的信息文件）
        """
        if self.filePath is None or self.filePath == "":
            QMessageBox.warning(self, "告警", "没有打开图像文件", QMessageBox.Yes)
            return

        _path = os.path.split(self.filePath)[0]
        _file_no_ext = FileTool.get_file_name_no_ext(self.filePath)
        _info_file = os.path.join(_path, _file_no_ext + ".info")
        if os.path.exists(_info_file):
            QMessageBox.warning(self, "告警", "图像信息文件已存在", QMessageBox.Yes)
            return

        _count = self.productInfo.count()
        if _count > 0:
            _info_dict = dict()
            for _row in range(_count):
                _item = self.productInfo.item(_row)
                _value = _item.text()
                _index = _value.find('】')
                _propname = _value[0:_index].strip('【】')
                _propvalue = _value[_index + 2:]  # 加上一个空格
                _info_dict[_propname] = _propvalue
        else:
            _info_dict = copy.deepcopy(self.mapping.get('info_key_dict', {}))

        _json = str(_info_dict)
        with open(_info_file, 'wb') as f:
            f.write(str.encode(_json, encoding='utf-8'))

        # 重新加载图像
        self.loadFile(filePath=self.filePath)
        QMessageBox.information(self, u'Information', "处理成功")

    def newInfoButton_click(self):
        """
        点击新增公共信息文件按钮（添加文件夹公共的信息文件）
        """
        if self.filePath is None or self.filePath == "":
            QMessageBox.warning(self, "告警", "没有打开图像文件", QMessageBox.Yes)
            return

        _path = os.path.split(self.filePath)[0]
        _info_file = os.path.join(_path, 'info.json')
        if os.path.exists(_info_file):
            QMessageBox.warning(self, "告警", "文件夹信息文件已存在", QMessageBox.Yes)
            return

        _count = self.productInfo.count()
        if _count > 0:
            _info_dict = dict()
            for _row in range(_count):
                _item = self.productInfo.item(_row)
                _value = _item.text()
                _index = _value.find('】')
                _propname = _value[0:_index].strip('【】')
                _propvalue = _value[_index + 2:]  # 加上一个空格
                _info_dict[_propname] = _propvalue
        else:
            _info_dict = copy.deepcopy(self.mapping.get('info_key_dict', {}))

        _json = str(_info_dict)
        with open(_info_file, 'wb') as f:
            f.write(str.encode(_json, encoding='utf-8'))

        # 重新加载图像
        self.loadFile(filePath=self.filePath)
        QMessageBox.information(self, u'Information', "处理成功")

    def set_format(self, save_format):
        if save_format == FORMAT_PASCALVOC:
            self.actions.save_format.setText(FORMAT_PASCALVOC)
            self.actions.save_format.setIcon(newIcon("format_voc"))
            self.usingPascalVocFormat = True
            self.usingYoloFormat = False
            LabelFile.suffix = XML_EXT

        elif save_format == FORMAT_YOLO:
            self.actions.save_format.setText(FORMAT_YOLO)
            self.actions.save_format.setIcon(newIcon("format_yolo"))
            self.usingPascalVocFormat = False
            self.usingYoloFormat = True
            LabelFile.suffix = TXT_EXT

    def change_format(self):
        if self.usingPascalVocFormat:
            self.set_format(FORMAT_YOLO)
        elif self.usingYoloFormat:
            self.set_format(FORMAT_PASCALVOC)

    def noShapes(self):
        return not self.itemsToShapes

    def toggleAdvancedMode(self, value=True):
        self._beginner = not value
        self.canvas.setEditing(True)
        self.populateModeActions()
        self.editButton.setVisible(not value)
        if value:
            self.actions.createMode.setEnabled(True)
            self.actions.editMode.setEnabled(False)
            self.dock.setFeatures(self.dock.features() | self.dockFeatures)
        else:
            self.dock.setFeatures(self.dock.features() ^ self.dockFeatures)

    def populateModeActions(self):
        if self.beginner():
            tool, menu = self.actions.beginner, self.actions.beginnerContext
        else:
            tool, menu = self.actions.advanced, self.actions.advancedContext
        self.tools.clear()
        addActions(self.tools, tool)
        self.canvas.menus[0].clear()
        addActions(self.canvas.menus[0], menu)
        self.menus.edit.clear()
        actions = (self.actions.create,) if self.beginner()\
            else (self.actions.createMode, self.actions.editMode)
        addActions(self.menus.edit, actions + self.actions.editMenu)

    def setBeginner(self):
        self.tools.clear()
        addActions(self.tools, self.actions.beginner)

    def setAdvanced(self):
        self.tools.clear()
        addActions(self.tools, self.actions.advanced)

    def setDirty(self):
        self.dirty = True
        self.actions.save.setEnabled(True)

    def setClean(self):
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.create.setEnabled(True)

    def toggleActions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        for z in self.actions.zoomActions:
            z.setEnabled(value)
        for action in self.actions.onLoadActive:
            action.setEnabled(value)

    def queueEvent(self, function):
        QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.statusBar().showMessage(message, delay)

    def resetState(self):
        self.itemsToShapes.clear()
        self.shapesToItems.clear()
        self.labelList.clear()
        self.filePath = None
        self.imageData = None
        self.labelFile = None
        self.canvas.resetState()
        self.labelCoordinates.clear()
        self.comboBox.cb.clear()

    def currentItem(self):
        items = self.labelList.selectedItems()
        if items:
            return items[0]
        return None

    def addRecentFile(self, filePath):
        if filePath in self.recentFiles:
            self.recentFiles.remove(filePath)
        elif len(self.recentFiles) >= self.maxRecent:
            self.recentFiles.pop()
        self.recentFiles.insert(0, filePath)

    def beginner(self):
        return self._beginner

    def advanced(self):
        return not self.beginner()

    def getAvailableScreencastViewer(self):
        osName = platform.system()

        if osName == 'Windows':
            return ['C:\\Program Files\\Internet Explorer\\iexplore.exe']
        elif osName == 'Linux':
            return ['xdg-open']
        elif osName == 'Darwin':
            return ['open']

    ## Callbacks ##
    def showTutorialDialog(self):
        subprocess.Popen(self.screencastViewer + [self.screencast])

    def showInfoDialog(self):
        msg = u'Name:{0} \nApp Version:{1} \n{2} '.format(
            __appname__, __version__, sys.version_info)
        QMessageBox.information(self, u'Information', msg)

    def createShape(self):
        assert self.beginner()
        self.canvas.setEditing(False)
        self.actions.create.setEnabled(False)

    def toggleDrawingSensitive(self, drawing=True):
        """In the middle of drawing, toggling between modes should be disabled."""
        self.actions.editMode.setEnabled(not drawing)
        if not drawing and self.beginner():
            # Cancel creation.
            print('Cancel creation.')
            self.canvas.setEditing(True)
            self.canvas.restoreCursor()
            self.actions.create.setEnabled(True)

    def toggleDrawMode(self, edit=True):
        self.canvas.setEditing(edit)
        self.actions.createMode.setEnabled(edit)
        self.actions.editMode.setEnabled(not edit)

    def setCreateMode(self):
        assert self.advanced()
        self.toggleDrawMode(False)

    def setEditMode(self):
        assert self.advanced()
        self.toggleDrawMode(True)
        self.labelSelectionChanged()

    def updateFileMenu(self):
        currFilePath = self.filePath

        def exists(filename):
            return os.path.exists(filename)
        menu = self.menus.recentFiles
        menu.clear()
        files = [f for f in self.recentFiles if f !=
                 currFilePath and exists(f)]
        for i, f in enumerate(files):
            icon = newIcon('labels')
            action = QAction(
                icon, '&%d %s' % (i + 1, QFileInfo(f).fileName()), self)
            action.triggered.connect(partial(self.loadRecent, f))
            menu.addAction(action)

    def popLabelListMenu(self, point):
        self.menus.labelList.exec_(self.labelList.mapToGlobal(point))

    def editLabel(self):
        if not self.canvas.editing():
            return
        item = self.currentItem()
        if not item:
            return
        text = self.labelDialog.popUp(item.text())
        if text is not None:
            item.setText(text)
            item.setBackground(generateColorByText(text))
            self.setDirty()
            self.updateComboBox()

    # Tzutalin 20160906 : Add file list and dock to move faster
    def fileitemDoubleClicked(self, item=None):
        currIndex = self.mImgList.index(ustr(item.text()))
        if currIndex < len(self.mImgList):
            filename = self.mImgList[currIndex]
            if filename:
                self.loadFile(filename)

    # Add chris
    def btnstate(self, item=None):
        """ Function to handle difficult examples
        Update on each object """
        if not self.canvas.editing():
            return

        item = self.currentItem()
        if not item:  # If not selected Item, take the first one
            item = self.labelList.item(self.labelList.count() - 1)

        difficult = self.diffcButton.isChecked()

        try:
            shape = self.itemsToShapes[item]
        except:
            pass
        # Checked and Update
        try:
            if difficult != shape.difficult:
                shape.difficult = difficult
                self.setDirty()
            else:  # User probably changed item visibility
                self.canvas.setShapeVisible(shape, item.checkState() == Qt.Checked)
        except:
            pass

    # React to canvas signals.
    def shapeSelectionChanged(self, selected=False):
        if self._noSelectionSlot:
            self._noSelectionSlot = False
        else:
            shape = self.canvas.selectedShape
            if shape:
                self.shapesToItems[shape].setSelected(True)
            else:
                self.labelList.clearSelection()
        self.actions.delete.setEnabled(selected)
        self.actions.copy.setEnabled(selected)
        self.actions.edit.setEnabled(selected)
        self.actions.shapeLineColor.setEnabled(selected)
        self.actions.shapeFillColor.setEnabled(selected)

    def addLabel(self, shape):
        shape.paintLabel = self.displayLabelOption.isChecked()
        item = HashableQListWidgetItem(shape.label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        item.setBackground(generateColorByText(shape.label))
        self.itemsToShapes[item] = shape
        self.shapesToItems[shape] = item
        self.labelList.addItem(item)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)
        self.updateComboBox()

    def remLabel(self, shape):
        if shape is None:
            # print('rm empty label')
            return
        item = self.shapesToItems[shape]
        self.labelList.takeItem(self.labelList.row(item))
        del self.shapesToItems[shape]
        del self.itemsToShapes[item]
        self.updateComboBox()

    def loadLabels(self, shapes):
        s = []
        for label, points, line_color, fill_color, difficult in shapes:
            shape = Shape(label=label)
            for x, y in points:

                # Ensure the labels are within the bounds of the image. If not, fix them.
                x, y, snapped = self.canvas.snapPointToCanvas(x, y)
                if snapped:
                    self.setDirty()

                shape.addPoint(QPointF(x, y))
            shape.difficult = difficult
            shape.close()
            s.append(shape)

            if line_color:
                shape.line_color = QColor(*line_color)
            else:
                shape.line_color = generateColorByText(label)

            if fill_color:
                shape.fill_color = QColor(*fill_color)
            else:
                shape.fill_color = generateColorByText(label)

            self.addLabel(shape)
        self.updateComboBox()
        self.canvas.loadShapes(s)

    def updateComboBox(self):
        # Get the unique labels and add them to the Combobox.
        itemsTextList = [str(self.labelList.item(i).text()) for i in range(self.labelList.count())]

        uniqueTextList = list(set(itemsTextList))
        # Add a null row for showing all the labels
        uniqueTextList.append("")
        uniqueTextList.sort()

        self.comboBox.update_items(uniqueTextList)

    def saveLabels(self, annotationFilePath):
        annotationFilePath = ustr(annotationFilePath)
        if self.labelFile is None:
            self.labelFile = LabelFile()
            self.labelFile.verified = self.canvas.verified

        def format_shape(s):
            return dict(label=s.label,
                        line_color=s.line_color.getRgb(),
                        fill_color=s.fill_color.getRgb(),
                        points=[(p.x(), p.y()) for p in s.points],
                        # add chris
                        difficult=s.difficult)

        # 仅保存非auto_开头的标注
        # shapes = [format_shape(shape) for shape in self.canvas.shapes]
        shapes = list()
        for shape in self.canvas.shapes:
            if not shape.label.startswith('auto_'):
                shapes.append(format_shape(shape))

        # Can add differrent annotation formats here
        try:
            if self.usingPascalVocFormat is True:
                if annotationFilePath[-4:].lower() != ".xml":
                    annotationFilePath += XML_EXT
                self.labelFile.savePascalVocFormat(annotationFilePath, shapes, self.filePath, self.imageData,
                                                   self.lineColor.getRgb(), self.fillColor.getRgb())
            elif self.usingYoloFormat is True:
                if annotationFilePath[-4:].lower() != ".txt":
                    annotationFilePath += TXT_EXT
                self.labelFile.saveYoloFormat(annotationFilePath, shapes, self.filePath, self.imageData, self.labelHist,
                                              self.lineColor.getRgb(), self.fillColor.getRgb())
            else:
                self.labelFile.save(annotationFilePath, shapes, self.filePath, self.imageData,
                                    self.lineColor.getRgb(), self.fillColor.getRgb())
            print('Image:{0} -> Annotation:{1}'.format(self.filePath, annotationFilePath))
            return True
        except LabelFileError as e:
            self.errorMessage(u'Error saving label data', u'<b>%s</b>' % e)
            return False

    def copySelectedShape(self):
        self.addLabel(self.canvas.copySelectedShape())
        # fix copy and delete
        self.shapeSelectionChanged(True)

    def comboSelectionChanged(self, index):
        text = self.comboBox.cb.itemText(index)
        for i in range(self.labelList.count()):
            if text == "":
                self.labelList.item(i).setCheckState(2)
            elif text != self.labelList.item(i).text():
                self.labelList.item(i).setCheckState(0)
            else:
                self.labelList.item(i).setCheckState(2)

    def labelSelectionChanged(self):
        item = self.currentItem()
        if item and self.canvas.editing():
            self._noSelectionSlot = True
            self.canvas.selectShape(self.itemsToShapes[item])
            shape = self.itemsToShapes[item]
            # Add Chris
            self.diffcButton.setChecked(shape.difficult)

    def labelItemChanged(self, item):
        shape = self.itemsToShapes[item]
        label = item.text()
        if label != shape.label:
            shape.label = item.text()
            shape.line_color = generateColorByText(shape.label)
            self.setDirty()
        else:  # User probably changed item visibility
            self.canvas.setShapeVisible(shape, item.checkState() == Qt.Checked)

    # Callback functions:
    def newShape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        if not self.useDefaultLabelCheckbox.isChecked() or not self.defaultLabelTextLine.text():
            if len(self.labelHist) > 0:
                self.labelDialog = LabelDialog(
                    parent=self, listItem=self.labelHist)

            # Sync single class mode from PR#106
            if self.singleClassMode.isChecked() and self.lastLabel:
                text = self.lastLabel
            else:
                text = self.labelDialog.popUp(text=self.prevLabelText)
                self.lastLabel = text
        else:
            text = self.defaultLabelTextLine.text()

        # Add Chris
        self.diffcButton.setChecked(False)
        if text is not None:
            self.prevLabelText = text
            generate_color = generateColorByText(text)
            shape = self.canvas.setLastLabel(text, generate_color, generate_color)
            self.addLabel(shape)
            if self.beginner():  # Switch to edit mode.
                self.canvas.setEditing(True)
                self.actions.create.setEnabled(True)
            else:
                self.actions.editMode.setEnabled(True)
            self.setDirty()

            if text not in self.labelHist:
                self.labelHist.append(text)
        else:
            # self.canvas.undoLastLine()
            self.canvas.resetAllLines()

    def scrollRequest(self, delta, orientation):
        units = - delta / (8 * 15)
        bar = self.scrollBars[orientation]
        bar.setValue(bar.value() + bar.singleStep() * units)

    def setZoom(self, value):
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.MANUAL_ZOOM
        self.zoomWidget.setValue(value)

    def addZoom(self, increment=10):
        self.setZoom(self.zoomWidget.value() + increment)

    def zoomRequest(self, delta):
        # get the current scrollbar positions
        # calculate the percentages ~ coordinates
        h_bar = self.scrollBars[Qt.Horizontal]
        v_bar = self.scrollBars[Qt.Vertical]

        # get the current maximum, to know the difference after zooming
        h_bar_max = h_bar.maximum()
        v_bar_max = v_bar.maximum()

        # get the cursor position and canvas size
        # calculate the desired movement from 0 to 1
        # where 0 = move left
        #       1 = move right
        # up and down analogous
        cursor = QCursor()
        pos = cursor.pos()
        relative_pos = QWidget.mapFromGlobal(self, pos)

        cursor_x = relative_pos.x()
        cursor_y = relative_pos.y()

        w = self.scrollArea.width()
        h = self.scrollArea.height()

        # the scaling from 0 to 1 has some padding
        # you don't have to hit the very leftmost pixel for a maximum-left movement
        margin = 0.1
        move_x = (cursor_x - margin * w) / (w - 2 * margin * w)
        move_y = (cursor_y - margin * h) / (h - 2 * margin * h)

        # clamp the values from 0 to 1
        move_x = min(max(move_x, 0), 1)
        move_y = min(max(move_y, 0), 1)

        # zoom in
        units = delta / (8 * 15)
        scale = 10
        self.addZoom(scale * units)

        # get the difference in scrollbar values
        # this is how far we can move
        d_h_bar_max = h_bar.maximum() - h_bar_max
        d_v_bar_max = v_bar.maximum() - v_bar_max

        # get the new scrollbar values
        new_h_bar_value = h_bar.value() + move_x * d_h_bar_max
        new_v_bar_value = v_bar.value() + move_y * d_v_bar_max

        h_bar.setValue(new_h_bar_value)
        v_bar.setValue(new_v_bar_value)

    def setFitWindow(self, value=True):
        if value:
            self.actions.fitWidth.setChecked(False)
        self.zoomMode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjustScale()

    def setFitWidth(self, value=True):
        if value:
            self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjustScale()

    def togglePolygons(self, value):
        for item, shape in self.itemsToShapes.items():
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def loadFile(self, filePath=None):
        """Load the specified file, or the last opened file if None."""
        # 自动保存
        if self.autoSaving.isChecked():
            if self.dirty is True:
                self.saveFile()

        self.resetState()
        self.canvas.setEnabled(False)
        if filePath is None:
            filePath = self.settings.get(SETTING_FILENAME)

        # Make sure that filePath is a regular python string, rather than QString
        filePath = ustr(filePath)

        # Fix bug: An  index error after select a directory when open a new file.
        unicodeFilePath = ustr(filePath)
        unicodeFilePath = os.path.abspath(unicodeFilePath)
        # Tzutalin 20160906 : Add file list and dock to move faster
        # Highlight the file item
        if unicodeFilePath and self.fileListWidget.count() > 0:
            if unicodeFilePath in self.mImgList:
                index = self.mImgList.index(unicodeFilePath)
                fileWidgetItem = self.fileListWidget.item(index)
                fileWidgetItem.setSelected(True)
            else:
                self.fileListWidget.clear()
                self.mImgList.clear()

        if unicodeFilePath and os.path.exists(unicodeFilePath):
            if LabelFile.isLabelFile(unicodeFilePath):
                try:
                    self.labelFile = LabelFile(unicodeFilePath)
                except LabelFileError as e:
                    self.errorMessage(u'Error opening file',
                                      (u"<p><b>%s</b></p>"
                                       u"<p>Make sure <i>%s</i> is a valid label file.")
                                      % (e, unicodeFilePath))
                    self.status("Error reading %s" % unicodeFilePath)
                    return False
                self.imageData = self.labelFile.imageData
                self.lineColor = QColor(*self.labelFile.lineColor)
                self.fillColor = QColor(*self.labelFile.fillColor)
                self.canvas.verified = self.labelFile.verified
            else:
                # Load image:
                # read data first and store for saving into label file.
                self.imageData = read(unicodeFilePath, None)
                self.labelFile = None
                self.canvas.verified = False

            image = QImage.fromData(self.imageData)
            if image.isNull():
                self.errorMessage(u'Error opening file',
                                  u"<p>Make sure <i>%s</i> is a valid image file." % unicodeFilePath)
                self.status("Error reading %s" % unicodeFilePath)
                return False
            self.status("Loaded %s" % os.path.basename(unicodeFilePath))
            self.image = image
            self.filePath = unicodeFilePath
            self.canvas.loadPixmap(QPixmap.fromImage(image))
            if self.labelFile:
                self.loadLabels(self.labelFile.shapes)
            self.setClean()
            self.canvas.setEnabled(True)
            self.adjustScale(initial=True)
            self.paintCanvas()
            self.addRecentFile(self.filePath)
            self.toggleActions(True)

            # Label xml file and show bound box according to its filename
            # if self.usingPascalVocFormat is True:
            if self.defaultSaveDir is not None:
                basename = os.path.basename(
                    os.path.splitext(self.filePath)[0])
                xmlPath = os.path.join(self.defaultSaveDir, basename + XML_EXT)
                txtPath = os.path.join(self.defaultSaveDir, basename + TXT_EXT)

                """Annotation file priority:
                PascalXML > YOLO
                """
                if os.path.isfile(xmlPath):
                    self.loadPascalXMLByFilename(xmlPath)
                elif os.path.isfile(txtPath):
                    self.loadYOLOTXTByFilename(txtPath)
                else:
                    shapes = self.auto_label_tool.detect_object(
                        self.filePath, []
                    )
                    self.loadLabels(shapes)
            else:
                xmlPath = os.path.splitext(filePath)[0] + XML_EXT
                txtPath = os.path.splitext(filePath)[0] + TXT_EXT
                if os.path.isfile(xmlPath):
                    self.loadPascalXMLByFilename(xmlPath)
                elif os.path.isfile(txtPath):
                    self.loadYOLOTXTByFilename(txtPath)
                else:
                    shapes = self.auto_label_tool.detect_object(
                        self.filePath, [],
                    )
                    self.loadLabels(shapes)

            self.setWindowTitle(__appname__ + ' ' + filePath)

            # 补充获取图片的商品信息

            _info = ExtendLib.get_info_dict(filePath, self.mapping.get('info_key_dict', {}))
            self.productInfo.clear()
            for _key in _info.keys():
                self.productInfo.addItem('【%s】 %s' % (_key, _info[_key]))

            # Default : select last item if there is at least one item
            if self.labelList.count():
                # 这里屏蔽了自动选中标签
                pass
                # self.labelList.setCurrentItem(self.labelList.item(self.labelList.count() - 1))
                # self.labelList.item(self.labelList.count() - 1).setSelected(True)

            self.canvas.setFocus(True)
            return True
        return False

    def resizeEvent(self, event):
        if self.canvas and not self.image.isNull()\
           and self.zoomMode != self.MANUAL_ZOOM:
            self.adjustScale()
        super(MainWindow, self).resizeEvent(event)

    def paintCanvas(self):
        assert not self.image.isNull(), "cannot paint null image"
        self.canvas.scale = 0.01 * self.zoomWidget.value()
        self.canvas.adjustSize()
        self.canvas.update()

    def adjustScale(self, initial=False):
        value = self.scalers[self.FIT_WINDOW if initial else self.zoomMode]()
        self.zoomWidget.setValue(int(100 * value))

    def scaleFitWindow(self):
        """Figure out the size of the pixmap in order to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.centralWidget().width() - e
        h1 = self.centralWidget().height() - e
        a1 = w1 / h1
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        a2 = w2 / h2
        return w1 / w2 if a2 >= a1 else h1 / h2

    def scaleFitWidth(self):
        # The epsilon does not seem to work too well here.
        w = self.centralWidget().width() - 2.0
        return w / self.canvas.pixmap.width()

    def closeEvent(self, event):
        if not self.mayContinue():
            event.ignore()
        settings = self.settings
        # If it loads images from dir, don't load it at the begining
        if self.dirname is None:
            settings[SETTING_FILENAME] = self.filePath if self.filePath else ''
        else:
            settings[SETTING_FILENAME] = ''

        settings[SETTING_WIN_SIZE] = self.size()
        settings[SETTING_WIN_POSE] = self.pos()
        settings[SETTING_WIN_STATE] = self.saveState()
        settings[SETTING_LINE_COLOR] = self.lineColor
        settings[SETTING_FILL_COLOR] = self.fillColor
        settings[SETTING_RECENT_FILES] = self.recentFiles
        settings[SETTING_ADVANCE_MODE] = not self._beginner
        if self.defaultSaveDir and os.path.exists(self.defaultSaveDir):
            settings[SETTING_SAVE_DIR] = ustr(self.defaultSaveDir)
        else:
            settings[SETTING_SAVE_DIR] = ''

        if self.lastOpenDir and os.path.exists(self.lastOpenDir):
            settings[SETTING_LAST_OPEN_DIR] = self.lastOpenDir
        else:
            settings[SETTING_LAST_OPEN_DIR] = ''

        settings[SETTING_AUTO_SAVE] = self.autoSaving.isChecked()
        settings[SETTING_SINGLE_CLASS] = self.singleClassMode.isChecked()
        settings[SETTING_PAINT_LABEL] = self.displayLabelOption.isChecked()
        settings[SETTING_DRAW_SQUARE] = self.drawSquaresOption.isChecked()
        settings.save()

    def loadRecent(self, filename):
        if self.mayContinue():
            self.loadFile(filename)

    def scanAllImages(self, folderPath):
        extensions = ['.%s' % fmt.data().decode("ascii").lower()
                      for fmt in QImageReader.supportedImageFormats()]
        images = []

        for root, dirs, files in os.walk(folderPath):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    relativePath = os.path.join(root, file)
                    path = ustr(os.path.abspath(relativePath))
                    images.append(path)
        natural_sort(images, key=lambda x: x.lower())
        return images

    def changeSavedirDialog(self, _value=False):
        if self.defaultSaveDir is not None:
            path = ustr(self.defaultSaveDir)
        else:
            path = '.'

        dirpath = ustr(QFileDialog.getExistingDirectory(self,
                                                        '%s - Save annotations to the directory' % __appname__, path, QFileDialog.ShowDirsOnly
                                                        | QFileDialog.DontResolveSymlinks))

        if dirpath is not None and len(dirpath) > 1:
            self.defaultSaveDir = dirpath

        self.statusBar().showMessage('%s . Annotation will be saved to %s' %
                                     ('Change saved folder', self.defaultSaveDir))
        self.statusBar().show()

    def openAnnotationDialog(self, _value=False):
        if self.filePath is None:
            self.statusBar().showMessage('Please select image first')
            self.statusBar().show()
            return

        path = os.path.dirname(ustr(self.filePath))\
            if self.filePath else '.'
        if self.usingPascalVocFormat:
            filters = "Open Annotation XML file (%s)" % ' '.join(['*.xml'])
            filename = ustr(QFileDialog.getOpenFileName(
                self, '%s - Choose a xml file' % __appname__, path, filters))
            if filename:
                if isinstance(filename, (tuple, list)):
                    filename = filename[0]
            self.loadPascalXMLByFilename(filename)

    def openDirDialog(self, _value=False, dirpath=None, silent=False):
        if not self.mayContinue():
            return

        defaultOpenDirPath = dirpath if dirpath else '.'
        if self.lastOpenDir and os.path.exists(self.lastOpenDir):
            defaultOpenDirPath = self.lastOpenDir
        else:
            defaultOpenDirPath = os.path.dirname(self.filePath) if self.filePath else '.'
        if silent != True:
            targetDirPath = ustr(QFileDialog.getExistingDirectory(self,
                                                                  '%s - Open Directory' % __appname__, defaultOpenDirPath,
                                                                  QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks))
        else:
            targetDirPath = ustr(defaultOpenDirPath)

        self.importDirImages(targetDirPath)

    def importDirImages(self, dirpath):
        if not self.mayContinue() or not dirpath:
            return

        self.lastOpenDir = dirpath
        self.dirname = dirpath
        self.filePath = None
        self.fileListWidget.clear()
        self.mImgList = self.scanAllImages(dirpath)
        self.openNextImg()
        for imgPath in self.mImgList:
            item = QListWidgetItem(imgPath)
            self.fileListWidget.addItem(item)

    def verifyImg(self, _value=False):
        # Proceding next image without dialog if having any label
        if self.filePath is not None:
            try:
                self.labelFile.toggleVerify()
            except AttributeError:
                # If the labelling file does not exist yet, create if and
                # re-save it with the verified attribute.
                self.saveFile()
                if self.labelFile != None:
                    self.labelFile.toggleVerify()
                else:
                    return

            self.canvas.verified = self.labelFile.verified
            self.paintCanvas()
            self.saveFile()

    def openPrevImg(self, _value=False):
        # Proceding prev image without dialog if having any label
        if self.autoSaving.isChecked():
            # 直接保存，不设置默认目录
            if self.dirty is True:
                self.saveFile()
            # if self.defaultSaveDir is not None:
            #     if self.dirty is True:
            #         self.saveFile()
            # else:
            #     self.changeSavedirDialog()
            #     return

        if not self.mayContinue():
            return

        if len(self.mImgList) <= 0:
            return

        if self.filePath is None:
            return

        currIndex = self.mImgList.index(self.filePath)
        if currIndex - 1 >= 0:
            filename = self.mImgList[currIndex - 1]
            if filename:
                self.loadFile(filename)

    def openNextImg(self, _value=False):
        # Proceding prev image without dialog if having any label
        if self.autoSaving.isChecked():
            if self.dirty is True:
                self.saveFile()
            # if self.defaultSaveDir is not None:
            #     if self.dirty is True:
            #         self.saveFile()
            # else:
            #     self.changeSavedirDialog()
            #     return

        if not self.mayContinue():
            return

        if len(self.mImgList) <= 0:
            return

        filename = None
        if self.filePath is None:
            filename = self.mImgList[0]
        else:
            currIndex = self.mImgList.index(self.filePath)
            if currIndex + 1 < len(self.mImgList):
                filename = self.mImgList[currIndex + 1]

        if filename:
            self.loadFile(filename)

    def openFile(self, _value=False):
        if not self.mayContinue():
            return
        path = os.path.dirname(ustr(self.filePath)) if self.filePath else '.'
        formats = ['*.%s' % fmt.data().decode("ascii").lower()
                   for fmt in QImageReader.supportedImageFormats()]
        filters = "Image & Label files (%s)" % ' '.join(formats + ['*%s' % LabelFile.suffix])
        filename = QFileDialog.getOpenFileName(
            self, '%s - Choose Image or Label file' % __appname__, path, filters)
        if filename:
            if isinstance(filename, (tuple, list)):
                filename = filename[0]
            self.loadFile(filename)

    def saveFile(self, _value=False):
        if self.defaultSaveDir is not None and len(ustr(self.defaultSaveDir)):
            if self.filePath:
                imgFileName = os.path.basename(self.filePath)
                savedFileName = os.path.splitext(imgFileName)[0]
                savedPath = os.path.join(ustr(self.defaultSaveDir), savedFileName)
                self._saveFile(savedPath)
        else:
            imgFileDir = os.path.dirname(self.filePath)
            imgFileName = os.path.basename(self.filePath)
            savedFileName = os.path.splitext(imgFileName)[0]
            savedPath = os.path.join(imgFileDir, savedFileName)
            self._saveFile(savedPath)
            # self._saveFile(savedPath if self.labelFile
            #                else self.saveFileDialog(removeExt=False))

    def product_item_double_clicked(self, modelindex: QtCore.QModelIndex) -> None:
        """
        商品信息按钮双击进行编辑

        @param {QModelIndex} modelindex - <description>

        @returns {None} - <description>
        """
        _row = modelindex.row()
        _item = self.productInfo.item(_row)
        _value = _item.text()
        _index = _value.find('】')
        _propname = _value[0:_index].strip('【】')
        _propvalue = _value[_index + 2:]  # 加上一个空格
        _new_value, ok = QInputDialog.getText(
            self, "编辑信息项", "请输入要设置的【%s】值：" % _propname, QLineEdit.Normal, _propvalue)

        # 设置值
        if ok:
            ok = ExtendLib.change_info_file(self.filePath, _propname, _new_value)
        else:
            return

        # 修改显示
        if ok:
            _item.setText('【%s】 %s' % (_propname, _new_value))
        else:
            # 提示错误
            QMessageBox.warning(self, "告警", "编辑信息项失败", QMessageBox.Yes)

    def imageDeal(self, _value=False):
        """
        处理图片,包括转换格式和删除非RGB格式图片

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件路径
        _deal_dir = str(QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Open Directory') % __appname__,
            '',
            QFileDialog.ShowDirsOnly |
            QFileDialog.DontResolveSymlinks))

        if not _deal_dir:
            return

        TFRecordCreater.labelimg_pic_deal(_deal_dir)

        QMessageBox.information(
            self, "提示", "图片处理成功", QMessageBox.Yes)

    def imageRename(self, _value=False):
        """
        批量重命名文件夹中的图片

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件路径
        _deal_dir = str(QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Open Directory') % __appname__,
            '',
            QFileDialog.ShowDirsOnly |
            QFileDialog.DontResolveSymlinks))

        if not _deal_dir:
            return

        TFRecordCreater.labelimg_rename_filename(_deal_dir)

        QMessageBox.information(
            self, "提示", "图片批量重命名成功", QMessageBox.Yes)

    def imageCropByTag(self, _value=False):
        """
        按标注截图

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件路径
        _source_dir = str(QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Copy Source Directory') % __appname__,
            '',
            QFileDialog.ShowDirsOnly |
            QFileDialog.DontResolveSymlinks))

        if not _source_dir:
            return

        _dest_dir = str(QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Copy Dest Directory') % __appname__,
            '',
            QFileDialog.ShowDirsOnly |
            QFileDialog.DontResolveSymlinks))

        if not _dest_dir:
            return

        # 判断无标注文件是否复制
        _copy_no_flag_pic = False
        _result = QMessageBox().question(
            self, "询问", '无标注的图片文件是否进行复制？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if _result == QMessageBox.Yes:
            _copy_no_flag_pic = True

        # 判断截取图片按子目录保存
        _with_sub_dir = False
        _result = QMessageBox().question(
            self, "询问", '是否按原目录结构保存截取的图片？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if _result == QMessageBox.Yes:
            _with_sub_dir = True

        # 进度显示
        pd = QProgressDialog(self)
        pd.setMinimumSize(500, 200)
        pd.setWindowTitle("按标注截取图片保存")
        pd.setLabelText("处理进度")
        pd.setCancelButtonText("取消")

        timer = QtCore.QTimer(pd)

        _iter_list = TFRecordCreater.labelimg_crop_pic_by_flags(
            _source_dir, _dest_dir, copy_no_flag_pic=_copy_no_flag_pic,
            with_sub_dir=_with_sub_dir, fix_len=10
        )

        RunTool.set_global_var(
            'IMAGE_CROP_BY_TAG_TEMP',
            {
                'result_iter': _iter_list,
                'last_result': None
            }
        )

        def show_progress():
            _para = RunTool.get_global_var('IMAGE_CROP_BY_TAG_TEMP')
            _progress = _para['result_iter'].__next__()

            if _progress is None or not _progress[2] or _progress[0] == _progress[1]:
                # 满足停止条件
                timer.stop()
                if _progress is None:
                    _progress = _para['last_result']

                if _progress[2]:
                    pd.setValue(_progress[0])
                    pd.setLabelText('处理成功！')
                else:
                    pd.setLabelText('处理失败！')

                # 显示提示
                pd.setCancelButtonText("关闭")
                pd.show()
                return

            _para['last_result'] = _progress

            if _progress[1] != pd.maximum():
                pd.setRange(0, _progress[1])
                pd.show()

            # 显示进度
            pd.setValue(_progress[0])

        timer.timeout.connect(show_progress)
        timer.start(10)

        pd.canceled.connect(timer.stop)

    def copyFlagsPics(self, _value=False):
        """
        按标注将文件复制到指定文件夹

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件路径
        _source_dir = str(QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Copy Source Directory') % __appname__,
            '',
            QFileDialog.ShowDirsOnly |
            QFileDialog.DontResolveSymlinks))

        if not _source_dir:
            return

        _dest_dir = str(QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Copy Dest Directory') % __appname__,
            '',
            QFileDialog.ShowDirsOnly |
            QFileDialog.DontResolveSymlinks))

        if not _dest_dir:
            return

        TFRecordCreater.labelimg_copy_flags_pics(
            _source_dir, _dest_dir, use_mapping=True, mapping=self.mapping
        )

        QMessageBox.information(
            self, "提示", "按标签复制文件成功", QMessageBox.Yes)

    def countFlags(self, _value=False):
        """
        统计指定目录中的labelimg标记对应标签的数量

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件路径
        _deal_dir = str(QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Open Directory') % __appname__,
            '',
            QFileDialog.ShowDirsOnly |
            QFileDialog.DontResolveSymlinks))

        if not _deal_dir:
            return

        # 进度显示
        pd = QProgressDialog(self)
        pd.setMinimumSize(500, 200)
        pd.setWindowTitle("统计labelimg标记数量")
        pd.setLabelText("处理进度")
        pd.setCancelButtonText("取消")

        timer = QtCore.QTimer(pd)

        _iter_list = TFRecordCreater.labelimg_flags_count(
            _deal_dir, self.mapping
        )

        RunTool.set_global_var(
            'LABELIMG_FLAGS_COUNT_TEMP',
            {
                'result_iter': _iter_list,
                'last_result': None
            }
        )

        def show_progress():
            _para = RunTool.get_global_var('LABELIMG_FLAGS_COUNT_TEMP')
            _progress = _para['result_iter'].__next__()

            if _progress is None or not _progress[2] or _progress[0] == _progress[1]:
                # 满足停止条件
                timer.stop()
                if _progress is None:
                    _progress = _para['last_result']

                if _progress[2]:
                    pd.setValue(_progress[0])
                    _count_str = '%s:\n%s' % (
                        'LabelImg标注统计', json.dumps(_progress[3], ensure_ascii=False, indent=4)
                    )
                    print(_count_str)
                    pd.setLabelText(_count_str)
                else:
                    pd.setLabelText('处理失败！')

                # 显示提示
                pd.setCancelButtonText("关闭")
                pd.show()
                return

            _para['last_result'] = _progress

            if _progress[1] != pd.maximum():
                pd.setRange(0, _progress[1])
                pd.show()

            # 显示进度
            pd.setValue(_progress[0])

        timer.timeout.connect(show_progress)
        timer.start(10)

        pd.canceled.connect(timer.stop)

    def createPbtxt(self, _value=False):
        """
        根据mapping.json文件生成对应的labelmap.pbtxt文件

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件路径
        _deal_dir = str(QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Open Directory') % __appname__,
            '',
            QFileDialog.ShowDirsOnly |
            QFileDialog.DontResolveSymlinks))

        if not _deal_dir:
            return

        if TFRecordCreater.create_pbtxt(_deal_dir, self.mapping):
            QMessageBox.information(
                self, "提示", "labelmap.pbtxt文件创建成功", QMessageBox.Yes)
        else:
            QMessageBox.information(
                self, "提示", "labelmap.pbtxt文件创建失败", QMessageBox.Yes)

    def labelimg_to_tfrecord(self, _value=False):
        """
        将LabelImg的标注生成TFRecord文件

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件路径
        _deal_dir = str(QFileDialog.getExistingDirectory(
            self,
            self.tr('%s - Open Directory') % __appname__,
            '',
            QFileDialog.ShowDirsOnly |
            QFileDialog.DontResolveSymlinks))

        # 拆分文件数量
        _num_per_file, ok = QInputDialog.getText(
            self, "拆分文件参数", "请输入每个TFRecord文件包含的图片数量(不拆分传空或0)：", QLineEdit.Normal, '0')

        if _num_per_file == '':
            _num_per_file = None
        else:
            _num_per_file = int(_num_per_file)
            if _num_per_file <= 0:
                _num_per_file = None

        # 进度显示
        pd = QProgressDialog(self)
        pd.setMinimumSize(500, 200)
        pd.setWindowTitle("生成LabelImg标注的TFRecord文件")
        pd.setLabelText("处理进度")
        pd.setCancelButtonText("取消")

        timer = QtCore.QTimer(pd)

        _iter_list = TFRecordCreater.labelimg_to_tfrecord(
            _deal_dir, os.path.join(_deal_dir, '%s.record' % FileTool.get_dir_name(_deal_dir)),
            _num_per_file, use_mapping=True, mapping=self.mapping
        )

        RunTool.set_global_var(
            'LABELIMG_TO_TFRECORD_TEMP',
            {
                'result_iter': _iter_list,
                'last_result': None
            }
        )

        def show_progress():
            _para = RunTool.get_global_var('LABELIMG_TO_TFRECORD_TEMP')
            _progress = _para['result_iter'].__next__()

            if _progress is None or not _progress[2] or _progress[0] == _progress[1]:
                # 满足停止条件
                timer.stop()
                if _progress is None:
                    _progress = _para['last_result']

                if _progress[2]:
                    pd.setValue(_progress[0])
                    pd.setLabelText('处理成功！')
                else:
                    pd.setLabelText('处理失败！')

                # 显示提示
                pd.setCancelButtonText("关闭")
                pd.show()
                return

            _para['last_result'] = _progress

            if _progress[1] != pd.maximum():
                pd.setRange(0, _progress[1])
                pd.show()

            # 显示进度
            pd.setValue(_progress[0])

        timer.timeout.connect(show_progress)
        timer.start(10)

        pd.canceled.connect(timer.stop)

    def dealDomFile(self, _value=False):
        """
        解析当前文件清单的dom文件生成商品信息

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件清单
        if self.dirname is None:
            QMessageBox(QMessageBox.Warning, '警告', '未打开文件目录！').exec()
            return

        _file_list = CommonLib.get_dom_file_list(self.dirname)
        if len(_file_list) == 0:
            return

        # 判断是否需要重做已有文件的
        _redo = False
        _result = QMessageBox().question(
            self, "询问", '对于已有info.json的商品是否重新解析？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if _result == QMessageBox.Yes:
            _redo = True

        pd = QProgressDialog(self)
        pd.setMinimumSize(500, 200)
        pd.setWindowTitle("解析dom文件商品信息")
        pd.setLabelText("处理进度")
        pd.setCancelButtonText("取消")

        pd.setRange(0, len(_file_list))
        pd.show()
        timer = QTimer(pd)

        RunTool.set_global_var(
            'DEAL_DOM_FILE_TEMP',
            {
                'index': 0,
                'file_list': _file_list,
                'fail_list': [],
                'redo': _redo
            }
        )

        def deal_with_dom_file():
            _para = RunTool.get_global_var('DEAL_DOM_FILE_TEMP')
            _current_index = _para['index']
            _file_list = _para['file_list']

            # 通过timer逐个文件进行处理
            if not CommonLib.analyse_dom_file(_file_list[_para['index']], redo=_para['redo']):
                # 处理失败，加入失败清单
                _para['fail_list'].append(_file_list[_para['index']])
                # pd.cancel()  # 失败取消继续执行

            # 更新进展
            _para['index'] += 1
            pd.setValue(_para['index'])

            # 判断是否已全部处理完成
            if _para['index'] >= pd.maximum():
                # 已全部执行完成
                timer.stop()
                if len(_para['fail_list']) == 0:
                    pd.setWindowTitle("解析dom文件商品信息")
                    pd.setLabelText('解析dom文件商品信息完成')

                else:
                    # 存在失败的情况
                    pd.setWindowTitle("解析dom文件商品信息")
                    pd.setLabelText('存在处理失败文件:\r\n' + '\r\n'.join(_para['fail_list']))

                # 显示提示
                pd.setCancelButtonText("关闭")
                pd.show()

        timer.timeout.connect(deal_with_dom_file)
        timer.start(10)

        pd.canceled.connect(timer.stop)

    def create_info_xls_file(self, _value=False):
        """
        将当前目录的产品信息生成excel汇总文件

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件清单
        _deal_dir = self.dirname
        if self.dirname is None:
            _deal_dir = str(QFileDialog.getExistingDirectory(
                self,
                self.tr('%s - Open Directory') % __appname__,
                '',
                QFileDialog.ShowDirsOnly |
                QFileDialog.DontResolveSymlinks))

            if not _deal_dir:
                return

        pd = QProgressDialog(self)
        pd.setMinimumSize(500, 200)
        pd.setWindowTitle("生成商品信息汇总文件")
        pd.setLabelText("处理进度")
        # pd.setCancelButtonText("取消")
        pd.setRange(0, 1)
        pd.setValue(0)
        pd.show()

        if CommonLib.product_info_to_xls(_deal_dir):
            # 处理成功
            pd.setLabelText('处理成功')
        else:
            # 处理失败
            pd.setLabelText('处理失败')

        # 显示提示
        pd.setCancelButtonText("关闭")
        pd.setValue(1)
        pd.show()

    def clean_product_files(self, _value=False):
        """
        清理商品信息文件夹内容

        @param {bool} _value=False - <description>
        """
        # 获取需要处理的文件清单
        _deal_dir = self.dirname
        if self.dirname is None:
            _deal_dir = str(QFileDialog.getExistingDirectory(
                self,
                self.tr('%s - Open Directory') % __appname__,
                '',
                QFileDialog.ShowDirsOnly |
                QFileDialog.DontResolveSymlinks))

            if not _deal_dir:
                return

        pd = QProgressDialog(self)
        pd.setMinimumSize(500, 200)
        pd.setWindowTitle("清理商品信息文件")
        pd.setLabelText("处理进度")

        timer = QtCore.QTimer(pd)

        _iter_list = CommonLib.clean_file_path(_deal_dir)

        RunTool.set_global_var(
            'CLEAN_PRODUCT_FILES_TEMP',
            {
                'result_iter': _iter_list,
                'last_result': None
            }
        )

        def show_progress():
            _para = RunTool.get_global_var('CLEAN_PRODUCT_FILES_TEMP')
            _progress = _para['result_iter'].__next__()

            if _progress is None or not _progress[2] or _progress[0] == _progress[1]:
                # 满足停止条件
                timer.stop()
                if _progress is None:
                    _progress = _para['last_result']

                if _progress[2]:
                    pd.setValue(_progress[0])
                    pd.setLabelText('处理成功！')
                else:
                    pd.setLabelText('处理失败！')

                # 显示提示
                pd.setCancelButtonText("关闭")
                pd.show()
                return

            _para['last_result'] = _progress

            if _progress[1] != pd.maximum():
                pd.setRange(0, _progress[1])
                pd.show()

            # 显示进度
            pd.setValue(_progress[0])

        timer.timeout.connect(show_progress)
        timer.start(10)

        pd.canceled.connect(timer.stop)

    def deleteCurrentFile(self, _value=False):
        """
        删除当前文件

        @param {bool} _value=False - <description>
        """
        if self.filePath is not None:
            if self.deleteWarningButton.isChecked():
                _result = QMessageBox().question(
                    self, "询问", '确认删除文件：\r\n%s' % self.filePath,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if not _result == QMessageBox.Yes:
                    return

            _file = self.filePath
            _row = self.fileListWidget.currentRow()

            # 转到下一个图片
            self.openNextImg()

            if _file == self.filePath:
                # 已经是最后一个图片
                self.openPrevImg()
                if _file == self.filePath:
                    self.closeFile()

            # 从列表清单中删除_row
            self.mImgList.remove(_file)
            self.fileListWidget.takeItem(_row)

            # 开始执行删除文件操作
            FileTool.remove_file(_file)

            # 提示
            QMessageBox.information(self, "提示", "文件删除成功", QMessageBox.Yes)

    def openPrevDir(self, _value=False):
        """
        打开上一个文件夹

        @param {bool} _value=False - <description>
        """
        # Proceding prev image without dialog if having any label
        if self.autoSaving.isChecked():
            if self.dirty is True:
                self.saveFile()

        if not self.mayContinue():
            return

        if len(self.mImgList) <= 0:
            return

        filename = None
        if self.filePath is None:
            filename = self.mImgList[0]
        else:
            currIndex = self.mImgList.index(self.filePath)
            _path = os.path.split(self.filePath)[0]
            _is_found = False
            while currIndex > 0:
                currIndex -= 1
                if _is_found:
                    # 已找到，只是需要找第一个
                    if os.path.split(self.mImgList[currIndex])[0] != _path:
                        currIndex += 1
                        filename = self.mImgList[currIndex]
                        break
                else:
                    if os.path.split(self.mImgList[currIndex])[0] != _path:
                        # 找到了上一个文件夹, 设置标签，还要继续循环找第一个
                        _path = os.path.split(self.mImgList[currIndex])[0]
                        _is_found = True

        if filename:
            self.loadFile(filename)

    def openNextDir(self, _value=False):
        """
        打开下一个文件夹

        @param {bool} _value=False - <description>
        """
        # Proceding prev image without dialog if having any label
        if self.autoSaving.isChecked():
            if self.dirty is True:
                self.saveFile()

        if not self.mayContinue():
            return

        if len(self.mImgList) <= 0:
            return

        filename = None
        if self.filePath is None:
            filename = self.mImgList[0]
        else:
            currIndex = self.mImgList.index(self.filePath)
            _path = os.path.split(self.filePath)[0]
            while currIndex < len(self.mImgList) - 1:
                currIndex += 1
                if os.path.split(self.mImgList[currIndex])[0] != _path:
                    # 找到了下一个文件夹
                    filename = self.mImgList[currIndex]
                    break

        if filename:
            self.loadFile(filename)

    def saveFileAs(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        self._saveFile(self.saveFileDialog())

    def saveFileDialog(self, removeExt=True):
        caption = '%s - Choose File' % __appname__
        filters = 'File (*%s)' % LabelFile.suffix
        openDialogPath = self.currentPath()
        dlg = QFileDialog(self, caption, openDialogPath, filters)
        dlg.setDefaultSuffix(LabelFile.suffix[1:])
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        filenameWithoutExtension = os.path.splitext(self.filePath)[0]
        dlg.selectFile(filenameWithoutExtension)
        dlg.setOption(QFileDialog.DontUseNativeDialog, False)
        if dlg.exec_():
            fullFilePath = ustr(dlg.selectedFiles()[0])
            if removeExt:
                return os.path.splitext(fullFilePath)[0]  # Return file path without the extension.
            else:
                return fullFilePath
        return ''

    def _saveFile(self, annotationFilePath):
        if annotationFilePath and self.saveLabels(annotationFilePath):
            self.setClean()
            self.statusBar().showMessage('Saved to  %s' % annotationFilePath)
            self.statusBar().show()

    def closeFile(self, _value=False):
        if not self.mayContinue():
            return
        self.resetState()
        self.setClean()
        self.toggleActions(False)
        self.canvas.setEnabled(False)
        self.actions.saveAs.setEnabled(False)

    def resetAll(self):
        self.settings.reset()
        self.close()
        proc = QProcess()
        proc.startDetached(os.path.abspath(__file__))

    def mayContinue(self):
        return not (self.dirty and not self.discardChangesDialog())

    def discardChangesDialog(self):
        yes, no = QMessageBox.Yes, QMessageBox.No
        msg = u'You have unsaved changes, proceed anyway?'
        return yes == QMessageBox.warning(self, u'Attention', msg, yes | no)

    def errorMessage(self, title, message):
        return QMessageBox.critical(self, title,
                                    '<p><b>%s</b></p>%s' % (title, message))

    def currentPath(self):
        return os.path.dirname(self.filePath) if self.filePath else '.'

    def chooseColor1(self):
        color = self.colorDialog.getColor(self.lineColor, u'Choose line color',
                                          default=DEFAULT_LINE_COLOR)
        if color:
            self.lineColor = color
            Shape.line_color = color
            self.canvas.setDrawingColor(color)
            self.canvas.update()
            self.setDirty()

    def deleteSelectedShape(self):
        self.remLabel(self.canvas.deleteSelected())
        self.setDirty()
        if self.noShapes():
            for action in self.actions.onShapesPresent:
                action.setEnabled(False)

    # 将选中的自动标注添加到xml文件中
    def addSelectedAutoShape(self):
        """
        将选中标注置为正式标注
        """
        item = self.currentItem()
        if not item:
            return

        _label = item.text()
        if _label.startswith('auto_'):
            _label = _label[_label.find('_', 5) + 1:]
            item.setText(_label)
            item.setBackground(generateColorByText(_label))
            self.setDirty()
            self.updateComboBox()

    def addAllSelectedAutoShape(self):
        """
        将所有勾选的自动批注设置为正式批注
        """
        _is_change = False
        for i in range(self.labelList.count()):
            item = self.labelList.item(i)
            _label = item.text()
            if item.checkState() == 2 and _label.startswith('auto_'):
                _label = _label[_label.find('_', 5) + 1:]
                item.setText(_label)
                item.setBackground(generateColorByText(_label))
                _is_change = True

        if _is_change:
            self.setDirty()
            self.updateComboBox()

    def chshapeLineColor(self):
        color = self.colorDialog.getColor(self.lineColor, u'Choose line color',
                                          default=DEFAULT_LINE_COLOR)
        if color:
            self.canvas.selectedShape.line_color = color
            self.canvas.update()
            self.setDirty()

    def chshapeFillColor(self):
        color = self.colorDialog.getColor(self.fillColor, u'Choose fill color',
                                          default=DEFAULT_FILL_COLOR)
        if color:
            self.canvas.selectedShape.fill_color = color
            self.canvas.update()
            self.setDirty()

    def copyShape(self):
        self.canvas.endMove(copy=True)
        self.addLabel(self.canvas.selectedShape)
        self.setDirty()

    def moveShape(self):
        self.canvas.endMove(copy=False)
        self.setDirty()

    def loadPredefinedClasses(self, predefClassesFile):
        if os.path.exists(predefClassesFile) is True:
            with codecs.open(predefClassesFile, 'r', 'utf8') as f:
                for line in f:
                    line = line.strip()
                    if self.labelHist is None:
                        self.labelHist = [line]
                    else:
                        self.labelHist.append(line)

    def loadPascalXMLByFilename(self, xmlPath):
        if self.filePath is None:
            return
        if os.path.isfile(xmlPath) is False:
            return

        self.set_format(FORMAT_PASCALVOC)

        tVocParseReader = PascalVocReader(xmlPath)
        shapes = tVocParseReader.getShapes()

        # 增加auto_label的形状显示
        shapes.extend(
            self.auto_label_tool.detect_object(
                self.filePath, shapes
            )
        )

        self.loadLabels(shapes)
        self.canvas.verified = tVocParseReader.verified

    def loadYOLOTXTByFilename(self, txtPath):
        if self.filePath is None:
            return
        if os.path.isfile(txtPath) is False:
            return

        self.set_format(FORMAT_YOLO)
        tYoloParseReader = YoloReader(txtPath, self.image)
        shapes = tYoloParseReader.getShapes()
        print(shapes)
        self.loadLabels(shapes)
        self.canvas.verified = tYoloParseReader.verified

    def togglePaintLabelsOption(self):
        for shape in self.canvas.shapes:
            shape.paintLabel = self.displayLabelOption.isChecked()

    def toogleDrawSquare(self):
        self.canvas.setDrawingShapeToSquare(self.drawSquaresOption.isChecked())


def inverted(color):
    return QColor(*[255 - v for v in color.getRgb()])


def read(filename, default=None):
    try:
        with open(filename, 'rb') as f:
            return f.read()
    except:
        return default


def get_main_app(argv=[]):
    """
    Standard boilerplate Qt application code.
    Do everything but app.exec_() -- so that we can test the application in one thread
    """
    app = QApplication(argv)
    app.setApplicationName(__appname__)
    app.setWindowIcon(newIcon("app"))
    # Tzutalin 201705+: Accept extra agruments to change predefined class file
    # Usage : labelImg.py image predefClassFile saveDir
    win = MainWindow(argv[1] if len(argv) >= 2 else None,
                     argv[2] if len(argv) >= 3 else os.path.join(
                         os.path.dirname(sys.argv[0]),
                         'data', 'predefined_classes.txt'),
                     argv[3] if len(argv) >= 4 else None)
    win.show()
    return app, win


def main():
    '''construct main app and run it'''
    app, _win = get_main_app(sys.argv)
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
