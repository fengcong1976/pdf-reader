"""PDF 阅读器 - 主程序入口"""

import sys
import os
from typing import Optional
from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtGui import QAction, QKeySequence, QIcon, QCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QMessageBox,
    QSplitter, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QSpinBox,
    QInputDialog, QStatusBar, QLineEdit, QSlider, QToolButton, QFrame,
    QDialog, QTextBrowser, QPushButton, QMenu
)
from pdf_document import PDFDocument
from pdf_view import PDFView
from sidebar import Sidebar
from search_bar import SearchBar
from tools import PDFToolsDialog
import ocr as ocr_module
from ocr import OCRRegionWorker, OCRResultDialog
import translator as ai_translate_module
from translator import (
    APISettingsDialog, TranslateResultDialog, PageTranslateWorker,
    PageRangeSummaryWorker, DirectionPickDialog, SummaryRangeDialog,
    is_configured as ai_is_configured, load_config as ai_load_config,
    save_direction as ai_save_direction,
    DIRECTIONS as AI_DIRECTIONS, DIRECTION_AUTO as AI_DIRECTION_AUTO,
)
from slideshow import SlideshowWindow
from about_dialog import show_about
from version import VERSION


class MainWindow(QMainWindow):
    """PDF 阅读器主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 阅读器")
        self.setMinimumSize(900, 600)
        # 设置窗口图标（优先 ICO，备选 PNG）
        icon = _load_app_icon()
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(1200, 800)

        # 核心组件
        self._document = PDFDocument()
        self._pdf_view = PDFView()
        self._sidebar = Sidebar()
        self._search_bar = SearchBar()

        # 最近打开文件（需在构建菜单前加载）
        self._settings = QSettings("PDFReader", "PDF阅读器")
        self._recent_files: list = []
        self._load_recent_files()

        # 构建界面
        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._connect_signals()

        # 启用主窗口拖放
        self.setAcceptDrops(True)

        # 状态
        self._current_page = 0
        self._search_query = ""

        # 画框识别（单次框选，结果对话框复用）
        self._ocr_worker = None
        self._ai_page_worker = None
        self._ai_page_dialog = None
        self._ocr_dialog = OCRResultDialog(self)
        # 幻灯片放映窗口
        self._slideshow_window = None

    # ── UI 构建 ──────────────────────────────────────────────────

    def _build_ui(self):
        # 中央区域：侧边栏 + 主视图
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._pdf_view)
        splitter.setSizes([250, 950])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # 主容器
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._search_bar)
        layout.addWidget(splitter)
        self.setCentralWidget(central)

    def _build_menu(self):
        menubar = self.menuBar()

        # ── 文件菜单 ──
        file_menu = menubar.addMenu("文件(&F)")

        self._action_open = QAction("打开(&O)...", self)
        self._action_open.setShortcut(QKeySequence.StandardKey.Open)
        self._action_open.triggered.connect(self.open_file_dialog)
        file_menu.addAction(self._action_open)

        # 最近打开的文件
        self._recent_menu = file_menu.addMenu("最近打开(&R)")
        self._recent_menu.setToolTipsVisible(True)
        self._action_clear_recent = QAction("清除最近打开记录(&C)", self)
        self._action_clear_recent.triggered.connect(self._clear_recent_files)
        file_menu.addSeparator()
        file_menu.addAction(self._action_clear_recent)
        self._update_recent_menu()

        self._action_save_as = QAction("另存为(&S)...", self)
        self._action_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self._action_save_as.triggered.connect(self.save_as)
        file_menu.addAction(self._action_save_as)

        file_menu.addSeparator()

        self._action_print = QAction("打印(&P)...", self)
        self._action_print.setShortcut(QKeySequence.StandardKey.Print)
        self._action_print.triggered.connect(self.print_pdf)
        file_menu.addAction(self._action_print)

        file_menu.addSeparator()

        self._action_exit = QAction("退出(&X)", self)
        self._action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self._action_exit.triggered.connect(self.close)
        file_menu.addAction(self._action_exit)

        # ── 编辑菜单 ──
        edit_menu = menubar.addMenu("编辑(&E)")

        self._action_search = QAction("搜索(&F)...", self)
        self._action_search.setShortcut(QKeySequence.StandardKey.Find)
        self._action_search.triggered.connect(self.toggle_search)
        edit_menu.addAction(self._action_search)

        self._action_find_next = QAction("查找下一个", self)
        self._action_find_next.setShortcut(QKeySequence.StandardKey.FindNext)
        self._action_find_next.triggered.connect(self.find_next)
        edit_menu.addAction(self._action_find_next)

        self._action_find_prev = QAction("查找上一个", self)
        self._action_find_prev.setShortcut(QKeySequence.StandardKey.FindPrevious)
        self._action_find_prev.triggered.connect(self.find_prev)
        edit_menu.addAction(self._action_find_prev)

        edit_menu.addSeparator()

        self._action_add_bookmark = QAction("添加书签(&B)", self)
        self._action_add_bookmark.setShortcut("Ctrl+B")
        self._action_add_bookmark.triggered.connect(self.add_bookmark)
        edit_menu.addAction(self._action_add_bookmark)

        # ── 视图菜单 ──
        view_menu = menubar.addMenu("视图(&V)")

        self._action_zoom_in = QAction("放大(&+)", self)
        self._action_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self._action_zoom_in.triggered.connect(self._pdf_view.zoom_in)
        view_menu.addAction(self._action_zoom_in)

        self._action_zoom_out = QAction("缩小(&-)", self)
        self._action_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self._action_zoom_out.triggered.connect(self._pdf_view.zoom_out)
        view_menu.addAction(self._action_zoom_out)

        self._action_reset_zoom = QAction("实际大小(&1)", self)
        self._action_reset_zoom.setShortcut("Ctrl+0")
        self._action_reset_zoom.triggered.connect(self._pdf_view.reset_zoom)
        view_menu.addAction(self._action_reset_zoom)

        self._action_fit_width = QAction("适应宽度(&W)", self)
        self._action_fit_width.setShortcut("Ctrl+2")
        self._action_fit_width.triggered.connect(self._pdf_view.fit_width)
        view_menu.addAction(self._action_fit_width)

        self._action_fit_page = QAction("适应页面(&P)", self)
        self._action_fit_page.setShortcut("Ctrl+3")
        self._action_fit_page.triggered.connect(self._pdf_view.fit_page)
        view_menu.addAction(self._action_fit_page)

        view_menu.addSeparator()

        self._action_rotate_cw = QAction("顺时针旋转(&R)", self)
        self._action_rotate_cw.setShortcut("Ctrl+Shift+R")
        self._action_rotate_cw.triggered.connect(self._pdf_view.rotate_clockwise)
        view_menu.addAction(self._action_rotate_cw)

        self._action_rotate_ccw = QAction("逆时针旋转(&L)", self)
        self._action_rotate_ccw.setShortcut("Ctrl+Shift+L")
        self._action_rotate_ccw.triggered.connect(self._pdf_view.rotate_counterclockwise)
        view_menu.addAction(self._action_rotate_ccw)

        view_menu.addSeparator()

        self._action_toggle_sidebar = QAction("显示/隐藏侧边栏(&S)", self)
        self._action_toggle_sidebar.setShortcut("F9")
        self._action_toggle_sidebar.triggered.connect(self.toggle_sidebar)
        view_menu.addAction(self._action_toggle_sidebar)

        view_menu.addSeparator()

        # 幻灯片放映
        self._action_slideshow_first = QAction("幻灯片放映（从第一页）(&H)", self)
        self._action_slideshow_first.setShortcut("F5")
        self._action_slideshow_first.triggered.connect(
            lambda: self.start_slideshow(from_current=False)
        )
        view_menu.addAction(self._action_slideshow_first)

        self._action_slideshow_current = QAction("全屏/幻灯片（从当前页放映）(&C)", self)
        self._action_slideshow_current.setShortcut("Shift+F5")
        self._action_slideshow_current.setIconText("全屏/幻灯片")
        self._action_slideshow_current.setToolTip(
            "进入全屏放映（从当前页开始）；进入后点击「播放」开始自动播放幻灯片，Esc 退出"
        )
        self._action_slideshow_current.triggered.connect(
            lambda: self.start_slideshow(from_current=True)
        )
        view_menu.addAction(self._action_slideshow_current)

        # ── 工具菜单 ──
        tools_menu = menubar.addMenu("工具(&T)")

        self._action_ocr = QAction("文字识别（框选区域）(&O)", self)
        self._action_ocr.setShortcut("Ctrl+Shift+O")
        self._action_ocr.setCheckable(True)
        self._action_ocr.setToolTip(
            "点击后在页面上拖出一个矩形框，识别框内文字（Esc 取消框选）"
        )
        self._action_ocr.toggled.connect(self.toggle_region_mode)
        tools_menu.addAction(self._action_ocr)

        tools_menu.addSeparator()

        # AI 翻译
        self._action_ai_page_translate = QAction("AI 翻译(&A)", self)
        self._action_ai_page_translate.setShortcut("Ctrl+Shift+A")
        self._action_ai_page_translate.setToolTip(
            "翻译当前页内容（扫描页自动 OCR），可选择翻译方向"
        )
        self._action_ai_page_translate.triggered.connect(
            self.ai_translate_current_page
        )
        tools_menu.addAction(self._action_ai_page_translate)

        self._action_ai_page_summary = QAction("AI 整页总结(&U)", self)
        self._action_ai_page_summary.setShortcut("Ctrl+Shift+Y")
        self._action_ai_page_summary.setToolTip(
            "总结当前页内容要点（扫描页自动 OCR），结果显示在弹窗中"
        )
        self._action_ai_page_summary.triggered.connect(self.ai_summarize)
        tools_menu.addAction(self._action_ai_page_summary)

        self._action_ai_settings = QAction("AI 大模型Key设置(&S)...", self)
        self._action_ai_settings.triggered.connect(self.open_ai_settings)
        tools_menu.addAction(self._action_ai_settings)

        tools_menu.addSeparator()

        self._action_tools = QAction("PDF 工具箱(&T)...", self)
        self._action_tools.triggered.connect(self.open_tools)
        tools_menu.addAction(self._action_tools)

        # ── 导航菜单 ──
        nav_menu = menubar.addMenu("导航(&N)")

        self._action_first = QAction("第一页", self)
        self._action_first.setShortcut("Home")
        self._action_first.triggered.connect(self._pdf_view.first_page)
        nav_menu.addAction(self._action_first)

        self._action_prev = QAction("上一页", self)
        self._action_prev.setShortcut(QKeySequence.StandardKey.MoveToPreviousPage)
        self._action_prev.triggered.connect(self._pdf_view.prev_page)
        nav_menu.addAction(self._action_prev)

        self._action_next = QAction("下一页", self)
        self._action_next.setShortcut(QKeySequence.StandardKey.MoveToNextPage)
        self._action_next.triggered.connect(self._pdf_view.next_page)
        nav_menu.addAction(self._action_next)

        self._action_last = QAction("最后一页", self)
        self._action_last.setShortcut("End")
        self._action_last.triggered.connect(self._pdf_view.last_page)
        nav_menu.addAction(self._action_last)

        # ── 帮助菜单 ──
        help_menu = menubar.addMenu("帮助(&H)")
        self._action_help = QAction("使用说明(&U)", self)
        self._action_help.setShortcut("F1")
        self._action_help.triggered.connect(self._show_help)
        help_menu.addAction(self._action_help)
        help_menu.addSeparator()
        self._action_about = QAction("关于(&A)", self)
        self._action_about.triggered.connect(self._show_about)
        help_menu.addAction(self._action_about)

    def _build_toolbar(self):
        toolbar = self.addToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # 文件操作
        toolbar.addAction(self._action_open)

        # 导航
        toolbar.addSeparator()
        toolbar.addAction(self._action_first)
        toolbar.addAction(self._action_prev)

        # 页码跳转
        page_widget = QWidget()
        page_layout = QHBoxLayout(page_widget)
        page_layout.setContentsMargins(4, 0, 4, 0)
        page_layout.addWidget(QLabel("页码:"))
        self._page_spin = QSpinBox()
        self._page_spin.setMinimum(1)
        self._page_spin.setMaximum(1)
        self._page_spin.setFixedWidth(70)
        self._page_spin.valueChanged.connect(self._goto_page_spin)
        page_layout.addWidget(self._page_spin)
        self._page_count_label = QLabel("/ 1")
        page_layout.addWidget(self._page_count_label)
        toolbar.addWidget(page_widget)

        toolbar.addAction(self._action_next)
        toolbar.addAction(self._action_last)

        # 旋转
        toolbar.addSeparator()
        toolbar.addAction(self._action_rotate_cw)
        toolbar.addAction(self._action_rotate_ccw)

        # 搜索
        toolbar.addSeparator()
        toolbar.addAction(self._action_search)

        # 文字识别
        toolbar.addSeparator()
        toolbar.addAction(self._action_ocr)

        # AI 翻译 / 总结
        self._action_ai_translate_btn = QAction("AI翻译", self)
        self._action_ai_translate_btn.setToolTip(
            "翻译当前页内容，点击后选择翻译方向（Ctrl+Shift+A）"
        )
        self._action_ai_translate_btn.triggered.connect(
            self.ai_translate_current_page
        )
        toolbar.addAction(self._action_ai_translate_btn)

        self._action_ai_summary_btn = QAction("AI总结", self)
        self._action_ai_summary_btn.setToolTip(
            "总结当前页内容要点（Ctrl+Shift+Y）"
        )
        self._action_ai_summary_btn.triggered.connect(self.ai_summarize)
        toolbar.addAction(self._action_ai_summary_btn)

        # 工具
        toolbar.addSeparator()
        toolbar.addAction(self._action_tools)

        # 全屏/幻灯片
        toolbar.addSeparator()
        toolbar.addAction(self._action_slideshow_current)

        # 画框模式开启时，按钮明显高亮（深蓝底 + 白色加粗）
        toolbar.setStyleSheet(
            "QToolButton:checked {"
            "background: #1a5fb4; color: white; font-weight: bold;"
            "border-radius: 3px; padding: 2px 6px;"
            "}"
        )

    def _build_statusbar(self):
        self._status_label = QLabel("就绪")
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(48)
        self._zoom_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._page_label = QLabel("")

        # ── 缩放控制组（按钮 + 滑块），整体放在状态栏右侧 ──
        zoom_box = QWidget()
        zoom_layout = QHBoxLayout(zoom_box)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(2)

        for action, short_text, tip in (
            (self._action_zoom_out, "缩小", "缩小（Ctrl+-）"),
            (self._action_zoom_in, "放大", "放大（Ctrl++）"),
            (self._action_reset_zoom, "100%", "实际大小 100%（Ctrl+0）"),
            (self._action_fit_width, "适宽", "适应宽度（Ctrl+2）"),
            (self._action_fit_page, "适页", "适应页面（Ctrl+3）"),
        ):
            action.setIconText(short_text)
            btn = QToolButton()
            btn.setDefaultAction(action)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.setAutoRaise(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip(tip)
            zoom_layout.addWidget(btn)

        # 竖分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        zoom_layout.addSpacing(6)
        zoom_layout.addWidget(sep)
        zoom_layout.addSpacing(6)

        # 可拖拽缩放滑块（10% ~ 400%）
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(10, 400)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(140)
        self._zoom_slider.setToolTip("拖动实时调整缩放比例（10% ~ 400%）")
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)
        zoom_layout.addWidget(self._zoom_slider)

        self.statusBar().addWidget(self._status_label, 1)
        self.statusBar().addPermanentWidget(zoom_box)
        self.statusBar().addPermanentWidget(self._zoom_label)
        self.statusBar().addPermanentWidget(self._page_label)

    # ── 信号连接 ─────────────────────────────────────────────────

    def _connect_signals(self):
        self._pdf_view.page_changed.connect(self._on_page_changed)
        self._pdf_view.scale_changed.connect(self._on_scale_changed)
        self._pdf_view.file_dropped.connect(self.open_file)
        self._sidebar.page_selected.connect(self._pdf_view.go_to_page)
        self._sidebar.close_requested.connect(self._sidebar.hide)
        self._pdf_view.page_double_clicked.connect(self._on_page_double_clicked)

        self._search_bar.search_requested.connect(self._on_search)
        self._search_bar.next_requested.connect(self.find_next)
        self._search_bar.prev_requested.connect(self.find_prev)
        self._search_bar.closed.connect(self._pdf_view.clear_search)

        # 画框识别
        self._pdf_view.region_selected.connect(self._on_region_selected)
        self._pdf_view.region_mode_changed.connect(self._on_region_mode_changed)

        # 划词解释
        self._pdf_view.text_region_selected.connect(self._on_text_region_selected)

    # ── 文件操作 ─────────────────────────────────────────────────

    def open_file_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开 PDF 文件", "", "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        if file_path:
            self.open_file(file_path)

    # ── 最近打开文件 ─────────────────────────────────────────────

    MAX_RECENT_FILES = 10

    def _load_recent_files(self):
        """从注册表/配置读取最近打开文件列表"""
        files = self._settings.value("recent_files", [])
        if isinstance(files, str):  # 只有一条时 QSettings 返回字符串
            files = [files]
        self._recent_files = [f for f in files if os.path.isfile(f)]

    def _save_recent_files(self):
        self._settings.setValue("recent_files", self._recent_files)

    def _push_recent_file(self, file_path: str):
        """记录最近打开的文件（去重、置顶、限量）"""
        file_path = os.path.abspath(file_path)
        # Windows 路径大小写不敏感
        self._recent_files = [
            f for f in self._recent_files if f.lower() != file_path.lower()
        ]
        self._recent_files.insert(0, file_path)
        del self._recent_files[self.MAX_RECENT_FILES:]
        self._save_recent_files()
        self._update_recent_menu()

    def _update_recent_menu(self):
        """根据最近文件列表重建菜单项"""
        self._recent_menu.clear()
        if not self._recent_files:
            empty = QAction("（无记录）", self)
            empty.setEnabled(False)
            self._recent_menu.addAction(empty)
        else:
            for path in self._recent_files:
                # 菜单文本过长时截断，完整路径放提示
                name = os.path.basename(path)
                text = name if len(name) <= 40 else name[:37] + "..."
                action = QAction(text, self)
                action.setToolTip(path)
                action.triggered.connect(
                    lambda checked=False, p=path: self._open_recent_file(p)
                )
                self._recent_menu.addAction(action)
        self._action_clear_recent.setEnabled(bool(self._recent_files))

    def _open_recent_file(self, file_path: str):
        """打开最近文件；文件不存在时提示并从列表移除"""
        if not os.path.isfile(file_path):
            QMessageBox.warning(self, "提示", f"文件不存在，已从最近打开列表移除：\n{file_path}")
            self._recent_files = [
                f for f in self._recent_files
                if f.lower() != file_path.lower()
            ]
            self._save_recent_files()
            self._update_recent_menu()
            return
        self.open_file(file_path)

    def _clear_recent_files(self):
        self._recent_files = []
        self._save_recent_files()
        self._update_recent_menu()

    def open_file(self, file_path: str):
        """打开指定路径的 PDF 文件"""
        # 等待正在进行的区域识别结束，避免操作已关闭的文档
        if self._ocr_worker is not None and self._ocr_worker.isRunning():
            self._ocr_worker.wait(20000)
        # 等待正在进行的 AI 整页翻译结束
        if self._ai_page_worker is not None and self._ai_page_worker.isRunning():
            self._ai_page_worker.wait(60000)
        # 打开新文件时退出框选模式（会同步复位工具栏按钮）
        if self._pdf_view.is_region_select_mode():
            self._pdf_view.set_region_select_mode(False)
        # 关闭旧文档
        if self._document.is_loaded:
            self._document.close()

        if not self._document.load(file_path):
            QMessageBox.critical(self, "错误", f"无法打开文件：\n{file_path}")
            return

        # 处理加密 PDF
        if self._document.is_encrypted():
            pwd, ok = QInputDialog.getText(
                self, "输入密码", "此 PDF 文件已加密，请输入密码：",
                QLineEdit.EchoMode.Password
            )
            if ok and pwd:
                if not self._document.authenticate(pwd):
                    QMessageBox.critical(self, "错误", "密码错误")
                    self._document.close()
                    return
            else:
                self._document.close()
                return

        # 更新界面
        self.setWindowTitle(f"PDF 阅读器 - {os.path.basename(file_path)}")
        self._pdf_view.set_document(self._document)
        self._sidebar.load_document(self._document, file_path)

        # 更新页码控件
        count = self._document.page_count
        self._page_spin.setMaximum(count)
        self._page_spin.setValue(1)
        self._page_count_label.setText(f"/ {count}")

        self._status_label.setText(
            f"已加载: {os.path.basename(file_path)}  ({count} 页)"
        )
        self._current_page = 0
        self._push_recent_file(file_path)

    def save_as(self):
        if not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self, "另存为", "", "PDF 文件 (*.pdf)"
        )
        if output_path:
            if self._document.save(output_path):
                QMessageBox.information(self, "成功", f"已保存到：\n{output_path}")
            else:
                QMessageBox.critical(self, "错误", "保存失败")

    def print_pdf(self):
        """打印 PDF（通过 Qt 打印对话框）"""
        if not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        from PySide6.QtGui import QPainter, QImage

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QPrintDialog.DialogCode.Accepted:
            painter = QPainter(printer)
            for i in range(self._document.page_count):
                pix = self._document.get_page_pixmap(i, zoom=2.0)
                if pix:
                    qimg = QImage(
                        pix.samples, pix.width, pix.height, pix.stride,
                        QImage.Format.Format_RGB888 if not pix.alpha
                        else QImage.Format.Format_RGBA8888
                    ).copy()
                    # 缩放图像适应打印页面
                    page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
                    img_scaled = qimg.scaled(
                        page_rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    x = (page_rect.width() - img_scaled.width()) // 2
                    y = (page_rect.height() - img_scaled.height()) // 2
                    painter.drawImage(x, y, img_scaled)
                    if i < self._document.page_count - 1:
                        printer.newPage()
            painter.end()

    # ── 搜索 ─────────────────────────────────────────────────────

    def toggle_search(self):
        if not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        self._search_bar.show_search()

    def _on_search(self, query: str, case_sensitive: bool):
        self._search_query = query
        results = self._document.search_text(query, case_sensitive)
        self._pdf_view.set_search_results(results)
        if results:
            self._pdf_view.goto_search_result(0)
            self._search_bar.set_result_info(0, self._pdf_view.get_search_count())
        else:
            self._search_bar.set_result_info(0, 0)

    def find_next(self):
        if not self._search_query:
            self.toggle_search()
            return
        idx = self._pdf_view.next_search_result()
        if idx >= 0:
            self._search_bar.set_result_info(idx, self._pdf_view.get_search_count())

    def find_prev(self):
        if not self._search_query:
            self.toggle_search()
            return
        idx = self._pdf_view.prev_search_result()
        if idx >= 0:
            self._search_bar.set_result_info(idx, self._pdf_view.get_search_count())

    # ── 书签 ─────────────────────────────────────────────────────

    def add_bookmark(self):
        if not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        name, ok = QInputDialog.getText(
            self, "添加书签", "书签名称：",
            text=f"第 {self._current_page + 1} 页"
        )
        if ok and name:
            self._sidebar.bookmarks_tab.add_bookmark(self._current_page, name)

    def _on_page_double_clicked(self, page_num: int):
        """双击页面 → 添加该书签"""
        self._current_page = page_num
        self.add_bookmark()

    # ── 视图操作 ─────────────────────────────────────────────────

    def toggle_sidebar(self):
        self._sidebar.setVisible(not self._sidebar.isVisible())

    # ── 全屏 / 幻灯片放映 ────────────────────────────────────────

    def start_slideshow(self, from_current: bool):
        """进入全屏放映（默认停在起始页，点放映窗口内“播放”才开始自动播放）"""
        if not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        # 放映期间关闭画框模式，避免交互冲突
        if self._pdf_view.is_region_select_mode():
            self._pdf_view.set_region_select_mode(False)

        start_page = self._pdf_view.get_current_page() if from_current else 0
        self._slideshow_window = SlideshowWindow(
            self._document, start_page, self._pdf_view.rotation
        )
        self._slideshow_window.closed.connect(self._on_slideshow_closed)
        self._slideshow_window.showFullScreen()

    def _on_slideshow_closed(self):
        """退出全屏放映：复位状态栏与引用（操作提示在放映窗口控制条内显示）"""
        self._slideshow_window = None
        self._status_label.setText("就绪")

    def _goto_page_spin(self, value: int):
        self._pdf_view.go_to_page(value - 1)

    def _on_page_changed(self, page: int):
        self._current_page = page
        self._page_spin.blockSignals(True)
        self._page_spin.setValue(page + 1)
        self._page_spin.blockSignals(False)
        self._page_label.setText(f"第 {page + 1} / {self._document.page_count} 页")
        self._sidebar.update_current_page(page)

    def _on_scale_changed(self, scale: float):
        self._zoom_label.setText(f"{int(scale * 100)}%")
        # 同步滑块位置（避免信号回环）
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(int(scale * 100))
        self._zoom_slider.blockSignals(False)

    def _on_zoom_slider_changed(self, value: int):
        """拖动滑块实时缩放"""
        self._pdf_view.set_scale(value / 100.0)

    # ── 工具 ─────────────────────────────────────────────────────

    def open_tools(self):
        if not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件（部分工具需要打开文件）")
        dialog = PDFToolsDialog(self._document, self)
        dialog.exec()

    def toggle_region_mode(self, checked: bool):
        """点击按钮 → 进入一次性框选；画完一个框自动退出"""
        if checked and not self._document.is_loaded:
            # 阻断勾选（避免 toggled 信号回环，先断开再复位）
            self._action_ocr.blockSignals(True)
            self._action_ocr.setChecked(False)
            self._action_ocr.blockSignals(False)
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        self._pdf_view.set_region_select_mode(checked)
        if checked:
            self._status_label.setText(
                "请在页面上按住鼠标拖出一个矩形框，识别框内文字（Esc 取消）"
            )

    def _on_region_mode_changed(self, enabled: bool):
        """视图侧（画框完成自动退出 / Esc 取消）改变模式时，同步按钮状态"""
        if self._action_ocr.isChecked() != enabled:
            self._action_ocr.blockSignals(True)
            self._action_ocr.setChecked(enabled)
            self._action_ocr.blockSignals(False)
        if not enabled:
            self._status_label.setText("已取消框选")

    def _on_region_selected(self, page_num: int, render_rect: tuple):
        """用户画好一个区域 → 自动退出框选 → 后台识别，结果只显示本次"""
        if self._ocr_worker is not None and self._ocr_worker.isRunning():
            return
        # 一次性框选：画完立即退出模式并复位按钮
        self._pdf_view.set_region_select_mode(False)
        first_load = not ocr_module.is_engine_loaded()
        self._ocr_dialog.show_busy(page_num, first_load)
        self._status_label.setText(f"正在识别第 {page_num + 1} 页框选区域……")

        worker = OCRRegionWorker(self._document, page_num, render_rect)
        worker.succeeded.connect(self._on_ocr_succeeded)
        worker.failed.connect(self._on_ocr_failed)
        worker.finished.connect(self._on_ocr_finished)
        self._ocr_worker = worker
        worker.start()

    def _on_ocr_succeeded(self, page_num: int, text: str):
        self._ocr_dialog.set_result(page_num, text)
        self._status_label.setText(f"第 {page_num + 1} 页区域识别完成")

    def _on_ocr_failed(self, page_num: int, message: str):
        self._ocr_dialog.show_failed(message)
        self._status_label.setText(f"第 {page_num + 1} 页区域识别失败")

    def _on_ocr_finished(self):
        self._ocr_worker = None

    # ── AI 翻译 ──────────────────────────────────────────────────

    def open_ai_settings(self):
        """打开 AI 大模型Key设置对话框"""
        APISettingsDialog(self).exec()

    def _ensure_ai_configured(self) -> bool:
        """已配置返回 True；未配置则弹设置对话框，完成后按结果判断"""
        if ai_is_configured():
            return True
        QMessageBox.information(
            self, "AI 大模型Key设置",
            "首次使用 AI 功能，请先填写大模型 API 信息。\n\n"
            "支持 DeepSeek / 通义千问 / Kimi / OpenAI 等\n"
            "OpenAI 兼容接口，只需接口地址 + API Key + 模型名。",
        )
        if APISettingsDialog(self).exec() != APISettingsDialog.DialogCode.Accepted:
            return False
        return ai_is_configured()

    def ai_translate_current_page(self):
        """AI 翻译当前页：先弹方向选择，再执行"""
        if not self._document or not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        if self._ai_page_worker is not None and self._ai_page_worker.isRunning():
            return  # 已有任务在进行
        dlg = DirectionPickDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected_direction:
            return
        self._run_ai_page_task("translate", dlg.selected_direction)

    def _run_ai_page_task(self, task: str, direction: str = None,
                          clip_rect=None, page_num: int = None):
        """AI 处理页（task：translate=翻译 / summary=总结 / explain=解释），弹窗显示结果

        clip_rect 非空时只处理该区域（划词解释），page_num 指定目标页。
        """
        if not self._document or not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        if self._ai_page_worker is not None and self._ai_page_worker.isRunning():
            return  # 已有任务在进行
        if not self._ensure_ai_configured():
            return
        if page_num is None:
            # 与状态栏同源的当前页（get_current_page 依赖布局坐标可能不准）
            page_num = self._current_page
        cfg = ai_load_config()
        if direction:
            ai_save_direction(direction)  # 记住本次方向，总结/全文翻译跟随
            cfg["direction"] = direction

        if self._ai_page_dialog is None:
            self._ai_page_dialog = TranslateResultDialog(self)
        self._ai_page_dialog.show_busy(
            page_num, cfg.get("direction", AI_DIRECTION_AUTO), task
        )
        self._ai_page_task_page = page_num  # 完成时按任务页码显示，不受翻页影响
        self._ai_page_task_label = None     # 范围总结时显示"第 X-Y 页"

        worker = PageTranslateWorker(self._document, page_num, cfg, task=task,
                                     clip_rect=clip_rect)
        worker.succeeded.connect(self._on_ai_page_succeeded)
        worker.bilingual.connect(self._on_ai_page_bilingual)
        worker.failed.connect(self._on_ai_page_failed)
        worker.finished.connect(self._on_ai_page_finished)
        self._ai_page_worker = worker
        worker.start()

    def ai_summarize(self):
        """AI 总结：先选范围（当前页 / 页码范围），再执行"""
        if not self._document or not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        if self._ai_page_worker is not None and self._ai_page_worker.isRunning():
            return  # 已有任务在进行
        dlg = SummaryRangeDialog(
            self._current_page, self._document.page_count, self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.mode == "page":
            self._run_ai_page_task("summary", page_num=dlg.start_page)
        else:
            self._run_ai_page_range_summary(dlg.start_page, dlg.end_page)

    def _run_ai_page_range_summary(self, page_start: int, page_end: int):
        """AI 总结页码范围：逐页取文拼接后整体总结"""
        if not self._ensure_ai_configured():
            return
        cfg = ai_load_config()
        if self._ai_page_dialog is None:
            self._ai_page_dialog = TranslateResultDialog(self)
        label = (
            f"第 {page_start + 1}-{page_end + 1} 页"
            if page_end > page_start else f"第 {page_start + 1} 页"
        )
        self._ai_page_dialog.show_busy(page_start, "", "summary", page_label=label)
        self._ai_page_task_page = page_start
        self._ai_page_task_label = label

        worker = PageRangeSummaryWorker(self._document, page_start, page_end, cfg)
        worker.succeeded.connect(self._on_ai_page_succeeded)
        worker.failed.connect(self._on_ai_page_failed)
        worker.finished.connect(self._on_ai_page_finished)
        self._ai_page_worker = worker
        worker.start()

    def _on_ai_page_succeeded(self, text: str):
        label = getattr(self, "_ai_page_task_label", None)
        self._ai_page_dialog.set_result(
            self._ai_page_task_page, text, page_label=label
        )
        self._ai_page_task_label = None

    def _on_ai_page_bilingual(self, pairs):
        self._ai_page_dialog.set_bilingual_result(self._ai_page_task_page, pairs)

    def _on_ai_page_failed(self, message: str):
        self._ai_page_dialog.show_failed(message)

    def _on_ai_page_finished(self):
        self._ai_page_worker = None

    def _on_text_region_selected(self, page_num: int, render_rect):
        """划词拖选完成：光标处弹菜单，AI 解释或复制文本"""
        if not self._document or not self._document.is_loaded:
            return
        text = self._document.get_text_in_rect(page_num, render_rect)
        menu = QMenu(self)
        if text:
            act_explain = menu.addAction("AI 解释")
            act_copy = menu.addAction("复制文本")
        else:
            act_explain = menu.addAction("AI 解释（图片文字，将先自动识别）")
            act_copy = None
        chosen = menu.exec(QCursor.pos())
        self._pdf_view.clear_text_selection()  # 菜单已关闭，选框此时消失
        if chosen == act_explain:
            self._run_ai_page_task("explain", clip_rect=render_rect,
                                   page_num=page_num)
        elif act_copy is not None and chosen == act_copy:
            QApplication.clipboard().setText(text)

    # ── 关于 ─────────────────────────────────────────────────────

    def _show_about(self):
        show_about("PDF 阅读器", self, version=VERSION)

    def _show_help(self):
        """详细使用说明（宽窗口 + 滚动条）"""
        html = (
            "<h2>PDF 阅读器使用说明</h2>"
            "<h3>一、打开文档</h3>"
            "<ul>"
            "<li>菜单「文件 → 打开」或按 <b>Ctrl+O</b> 选择 PDF 文件</li>"
            "<li>直接把 PDF 文件<b>拖拽</b>到窗口任意位置即可打开</li>"
            "<li>加密 PDF 会弹出密码输入框，输入正确密码后解锁</li>"
            "</ul>"
            "<h3>二、页面导航</h3>"
            "<ul>"
            "<li>工具栏「页码」输入框直接输入页码回车跳转</li>"
            "<li>上一页/下一页：<b>PgUp / PgDn</b>（或工具栏按钮）</li>"
            "<li>第一页/最后一页：<b>Home / End</b></li>"
            "<li>滚动鼠标滚轮可上下连续浏览</li>"
            "</ul>"
            "<h3>三、缩放与旋转</h3>"
            "<ul>"
            "<li>放大/缩小：<b>Ctrl++ / Ctrl+-</b>，或 <b>Ctrl+滚轮</b></li>"
            "<li>实际大小（100%）：<b>Ctrl+0</b></li>"
            "<li>适应宽度：<b>Ctrl+2</b>；适应页面：<b>Ctrl+3</b></li>"
            "<li>窗口底部右下角提供<b>缩放按钮组</b>（缩小 / 放大 / 100% / 适宽 / 适页）"
            "和<b>缩放滑块</b>，拖动滑块可实时缩放（10%~400%）</li>"
            "<li>旋转：顺时针 <b>Ctrl+Shift+R</b>，逆时针 <b>Ctrl+Shift+L</b></li>"
            "</ul>"
            "<h3>四、侧边栏</h3>"
            "<ul>"
            "<li>显示/隐藏：<b>F9</b>，或点击侧边栏右上角「关闭」按钮</li>"
            "<li>「缩略图」：点击任意页面缩略图跳转到该页</li>"
            "<li>「目录」：展示 PDF 自带书签大纲，点击条目跳转</li>"
            "<li>「书签」：收藏常用页面，自动保存到与 PDF 同名的 .bmk 文件</li>"
            "<li>添加书签：双击主视图页面，或右键书签列表，或按 <b>Ctrl+B</b></li>"
            "</ul>"
            "<h3>五、文本搜索</h3>"
            "<ul>"
            "<li>打开搜索栏：<b>Ctrl+F</b>（Esc 关闭）</li>"
            "<li>输入关键词后回车或点「搜索」，全文高亮所有结果</li>"
            "<li>上/下一个结果：<b>Enter / Shift+Enter</b>（或搜索栏按钮）</li>"
            "<li>可勾选「区分大小写」精确匹配</li>"
            "</ul>"
            "<h3>六、文字识别（OCR）</h3>"
            "<ul>"
            "<li>适用场景：扫描版 PDF、拍照图片做成的 PDF，无法选中/搜索文字时使用</li>"
            "<li>使用方式：菜单「工具 → 文字识别（框选区域）」、工具栏「文字识别」按钮"
            "（按下后深蓝高亮），或快捷键 <b>Ctrl+Shift+O</b></li>"
            "<li>点击后鼠标变为十字光标，<b>在页面上按住左键拖出一个矩形框</b>，"
            "松开即自动识别框内文字并弹出结果；每次只显示本次识别结果</li>"
            "<li>识别另一区域时，再次点击「文字识别」按钮重新框选即可；"
            "不想识别时按 <b>Esc</b> 取消框选</li>"
            "<li>识别结果可<b>直接在结果框内编辑修正</b>，再一键复制或保存为 TXT</li>"
            "<li>识别在后台进行不卡界面；首次使用会加载识别模型，约需十几秒，属正常现象</li>"
            "</ul>"
            "<h3>七、全屏 / 幻灯片放映</h3>"
            "<ul>"
            "<li>进入方式：点击工具栏「<b>全屏/幻灯片</b>」按钮、"
            "菜单「视图 → 全屏/幻灯片（从当前页放映）」或按 <b>Shift+F5</b>，"
            "从当前页进入全屏；按 <b>F5</b> 则从第一页开始</li>"
            "<li>进入后先<b>全屏展示当前页</b>（不会自动翻页），"
            "点击底部控制条上的「<b>播放</b>」按钮才开始自动播放幻灯片，"
            "再点一次可暂停</li>"
            "<li>放映中翻页：鼠标<b>左键下一页 / 右键上一页</b>，或 "
            "→/↓/空格/PageDown、←/↑/PageUp；Home/End 跳首尾</li>"
            "<li>自动播放间隔可选 3~30 秒/页；控制条显示当前页码，"
            "鼠标静止后自动隐藏，移动鼠标即重新出现</li>"
            "<li><b>聚光灯（显微镜）</b>：点击控制条「聚光灯」或按 <b>S</b>，"
            "屏幕压暗，鼠标周围圆形区域内的内容会以鼠标为中心"
            "<b>放大约 1.2 倍</b>突出显示，移动鼠标即可查看；再按一次关闭；"
            "与激光灯、画笔互斥</li>"
            "<li><b>激光灯</b>：点击「激光灯」或按 <b>L</b>，"
            "鼠标变为高亮绿色激光光点（带柔光晕）跟随移动指示内容，"
            "不压暗屏幕、左右键翻页照常；与聚光灯、画笔互斥，后开启的生效</li>"
            "<li><b>画笔涂写</b>：点击「画笔」或按 <b>D</b>，"
            "按住左键即可在页面上书写标注（可选红/黄/蓝/白/绿五色），"
            "此时左键不再翻页；笔迹按页保留，翻页后再翻回仍在；"
            "按 <b>C</b> 或点「清除」删除当前页笔迹；与聚光灯、激光灯互斥</li>"
            "<li><b>缩放与拖拽</b>：控制条上的缩放滑块（50%~400%，"
            "100% 为适应页面）、<b>＋ / －</b> 按钮或 <b>Ctrl+滚轮</b>均可缩放；"
            "放大后在页面上<b>按住左键拖动</b>可平移查看（按住没拖动则仍是翻页），"
            "点「适页」恢复整页；缩放倍率翻页时保留</li>"
            "<li>鼠标移到控制条上始终显示正常箭头光标，方便操作按钮和滑块</li>"
            "<li>退出全屏：按 <b>Esc</b>，或点击控制条上的「退出全屏」</li>"
            "</ul>"
            "<h3>七、AI 智能功能</h3>"
            "<ul>"
            "<li>前提：菜单「工具 → AI 大模型Key设置」填写接口地址、API Key 和模型名"
            "（支持 DeepSeek / 通义千问 / Kimi / OpenAI 等 OpenAI 兼容接口，"
            "首次使用会自动弹出）</li>"
            "<li><b>划词解释</b>：在页面上按住左键<b>拖选任意文字区域</b>，"
            "松开即弹出菜单，点「AI 解释」解释选中内容"
            "（外文先翻译再解释，术语讲定义，段落讲大意）；"
            "也可点「复制文本」快速复制；"
            "拖选扫描图片区域时会先自动 OCR 识别再解释</li>"
            "<li><b>AI 翻译</b>：工具栏「AI翻译」按钮或菜单「工具 → AI 翻译」"
            "（<b>Ctrl+Shift+A</b>），翻译当前整页，"
            "方向可选自动识别 / 中文→English / English→中文，"
            "结果按<b>原文 / 译文逐段对照</b>显示（灰色为原文）</li>"
            "<li><b>AI 总结</b>：工具栏「AI总结」按钮或 <b>Ctrl+Shift+Y</b>，"
            "可提炼<b>当前页</b>要点，也可自选<b>页码范围</b>做整体总结"
            "（最多 30 页，扫描页自动 OCR）</li>"
            "<li><b>AI 全文翻译</b>：菜单「工具 → PDF 工具箱」中的「AI全文翻译」，"
            "逐页翻译整个文档（方向跟随最近一次选择）</li>"
            "</ul>"
            "<h3>八、PDF 工具</h3>"
            "<ul>"
            "<li>菜单「工具 → PDF 工具箱」或工具栏「PDF 工具箱」按钮</li>"
            "<li>拆分：提取指定页面范围另存为新文件</li>"
            "<li>合并：将多个 PDF 按顺序合并成一个文件</li>"
            "<li>加密：为 PDF 设置密码（RC4-128 / AES-256）</li>"
            "<li>文本提取：将 PDF 全部文本导出为 TXT（扫描件可自动 OCR）</li>"
            "<li><b>PDF 瘦身（2.1 新增）</b>：可一次加入多个文件，四档可选"
            "（无损整理 / 轻度 / 标准 / 强力），也能按目标体积自动挑档；"
            "结果另存到原文件旁的 out 文件夹，压完自动打开，report.json 记录逐文件前后体积</li>"
            "<li style='color:#a33;'>瘦身有损披露：除无损整理外都会重新编码页面内嵌图片，"
            "画质会下降且不可由本工具还原；文字、矢量图形、页数与原文件都不变。"
            "任何档位压完没变小的文件，会原样输出而不放大体积。</li>"
            "</ul>"
            "<h3>九、其他</h3>"
            "<ul>"
            "<li>打印：<b>Ctrl+P</b></li>"
            "<li>另存为：<b>Ctrl+Shift+S</b></li>"
            "<li>退出：<b>Ctrl+Q</b></li>"
            "</ul>"
            "<hr>"
            "<p style='color:#666;'>版本 2.1 &nbsp;|&nbsp; "
            "开发者：深圳市创炫互动网络科技有限公司 &nbsp;|&nbsp; "
            "更多免费软件：<a href='http://www.mrheedu.com'>www.mrheedu.com</a></p>"
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("PDF 阅读器 - 使用说明")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(html)
        layout.addWidget(browser, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setMinimumHeight(32)
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # 宽窗口，高度取屏幕 80%，内容超出时浏览器自带垂直滚动条
        screen = QApplication.primaryScreen().availableGeometry()
        dlg.resize(min(960, screen.width() - 80),
                   min(760, int(screen.height() * 0.85)))
        dlg.exec()

    # ── 关闭事件 ─────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._ocr_worker is not None and self._ocr_worker.isRunning():
            self._ocr_worker.wait(20000)
        if self._ai_page_worker is not None and self._ai_page_worker.isRunning():
            self._ai_page_worker.wait(60000)
        if self._document.is_loaded:
            self._document.close()
        event.accept()

    # ── 拖放支持 ─────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith('.pdf'):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            fp = url.toLocalFile()
            if fp.lower().endswith('.pdf'):
                self.open_file(fp)
                event.acceptProposedAction()
                return
        event.ignore()


def _load_app_icon() -> Optional[QIcon]:
    """加载应用图标，优先 ICO 备选 PNG（兼容 PyInstaller 打包环境）"""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    for name in ("app.ico", "app.png"):
        path = os.path.join(base, "icons", name)
        if os.path.exists(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    return None


def _run_selftest(args) -> int:
    """冻结环境自检：不建窗口、不依赖控制台，结果可写日志文件。"""
    import pdf_slim
    log_path = next((a for a in args if a.lower().endswith((".log", ".txt"))), None)
    passed, total, lines = pdf_slim.selftest()
    ok = passed == total
    text = "\n".join(lines) + "\n"
    if log_path:
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass
    # 窗口版 exe 没有控制台，sys.stdout 可能是 None；不能在这里 flush
    try:
        if sys.stdout is not None:
            sys.stdout.write(text)
    except Exception:
        pass
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        return _run_selftest(args)
    app = QApplication(sys.argv)
    app.setApplicationName("PDF 阅读器")
    # 设置应用图标（影响任务栏、通知等）
    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    window = MainWindow()
    window.show()

    # 命令行参数：双击关联的 PDF 文件时，Windows 会以 "exe path\to\file.pdf" 方式启动
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.lower().endswith(".pdf"):
                # 延迟加载，等窗口初始化完毕
                QTimer.singleShot(100, lambda p=arg: window.open_file(p))
                break

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
