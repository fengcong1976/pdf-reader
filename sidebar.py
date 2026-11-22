"""侧边栏模块 - 缩略图、目录大纲、书签收藏"""

import json
import os
import pymupdf
from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QPixmap, QImage, QIcon, QAction, QColor
from PySide6.QtWidgets import (
    QTabWidget, QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem,
    QVBoxLayout, QHBoxLayout, QWidget, QLabel, QMenu, QInputDialog, QMessageBox,
    QFileDialog, QAbstractItemView, QPushButton
)
from typing import Optional, List


# ── 缩略图标签页 ──────────────────────────────────────────────

class ThumbnailsTab(QWidget):
    """页面缩略图标签页"""

    page_selected = Signal(int)  # 页码（0-based）

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(120, 160))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setSpacing(10)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

    # 缩略图批次间隔（毫秒）：给界面留出响应时间，避免连续渲染卡死
    THUMB_BATCH_DELAY = 40

    def load_document(self, document):
        """加载文档：先建占位项立即显示界面，缩略图再分批异步渲染"""
        # 递增任务代号，使上一个文档未完成的渲染链自然失效
        self._thumb_gen = getattr(self, "_thumb_gen", 0) + 1
        self._thumb_doc = None
        self._list.clear()
        if not document or not document.is_loaded:
            return
        # 只建占位项（显示页码），瞬间完成，不阻塞打开文件；
        # 占位图标与正式缩略图同尺寸，保证布局从头到尾稳定不跳动
        placeholder = QPixmap(QSize(120, 160))
        placeholder.fill(QColor(228, 228, 228))
        for i in range(document.page_count):
            item = QListWidgetItem(QIcon(placeholder), f"{i + 1}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)
        # 稍后启动分批渲染：优先让主视图先渲染出第一页
        self._thumb_doc = document
        self._thumb_next = 0
        gen = self._thumb_gen
        QTimer.singleShot(250, lambda: self._render_thumbnail_batch(gen))

    def _render_thumbnail_batch(self, gen: int):
        """每次渲染 1 页缩略图，批次间留间隙，界面不可见时暂停"""
        if gen != self._thumb_gen:
            return  # 任务已被新文档取代
        doc = self._thumb_doc
        if not doc or not doc.is_loaded:
            return
        if self._thumb_next >= doc.page_count:
            return  # 全部完成
        if not self.isVisible():
            # 侧边栏/缩略图页不可见时暂缓渲染，之后自动恢复
            QTimer.singleShot(300, lambda: self._render_thumbnail_batch(gen))
            return
        i = self._thumb_next
        self._thumb_next += 1
        pix = doc.get_page_pixmap(i, zoom=0.3)
        if pix:
            qimg = QImage(pix.samples, pix.width, pix.height, pix.stride,
                          QImage.Format.Format_RGB888 if not pix.alpha
                          else QImage.Format.Format_RGBA8888).copy()
            self._list.item(i).setIcon(QIcon(QPixmap.fromImage(qimg)))
        QTimer.singleShot(
            self.THUMB_BATCH_DELAY,
            lambda: self._render_thumbnail_batch(gen),
        )

    def highlight_page(self, page_num: int):
        """高亮指定页面"""
        if 0 <= page_num < self._list.count():
            self._list.setCurrentRow(page_num)

    def _on_item_clicked(self, item):
        page = item.data(Qt.ItemDataRole.UserRole)
        self.page_selected.emit(page)


# ── 目录大纲标签页 ─────────────────────────────────────────────

class OutlineTab(QWidget):
    """PDF 目录大纲标签页"""

    page_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)
        self._empty_label = QLabel("此 PDF 没有目录大纲")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)
        self._empty_label.hide()

    def load_outline(self, outline: List[dict]):
        """加载目录大纲"""
        self._tree.clear()
        if not outline:
            self._empty_label.show()
            return
        self._empty_label.hide()

        def build_tree(parent_item, nodes):
            for node in nodes:
                item = QTreeWidgetItem(parent_item, [node["title"]])
                item.setData(0, Qt.ItemDataRole.UserRole, node["page"])
                if node.get("children"):
                    build_tree(item, node["children"])

        build_tree(self._tree.invisibleRootItem(), outline)
        self._tree.expandAll()

    def _on_item_clicked(self, item):
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None and page >= 0:
            self.page_selected.emit(page)


# ── 书签收藏标签页 ─────────────────────────────────────────────

class BookmarksTab(QWidget):
    """自定义书签收藏标签页"""

    page_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self._document = None
        self._bookmarks: List[dict] = []  # [{"name": ..., "page": ...}, ...]
        self._bookmarks_file = ""  # 与 PDF 同名的 .bmk 文件

        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list)

        self._empty_label = QLabel("双击主视图页面可添加书签\n或右键列表添加")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: gray; padding: 20px;")
        layout.addWidget(self._empty_label)

    def set_document(self, document, file_path: str):
        """设置文档，加载对应的书签文件"""
        self._document = document
        self._list.clear()
        self._bookmarks = []
        # 书签文件与 PDF 同名，扩展名 .bmk
        if file_path:
            self._bookmarks_file = os.path.splitext(file_path)[0] + ".bmk"
            self._load_bookmarks_file()
        self._update_empty_label()

    def _load_bookmarks_file(self):
        """从 .bmk 文件加载书签"""
        if not os.path.exists(self._bookmarks_file):
            return
        try:
            with open(self._bookmarks_file, "r", encoding="utf-8") as f:
                self._bookmarks = json.load(f)
            for bm in self._bookmarks:
                item = QListWidgetItem(f"[第 {bm['page'] + 1} 页] {bm['name']}")
                item.setData(Qt.ItemDataRole.UserRole, bm["page"])
                self._list.addItem(item)
        except Exception:
            pass

    def _save_bookmarks_file(self):
        """保存书签到 .bmk 文件"""
        if not self._bookmarks_file:
            return
        try:
            with open(self._bookmarks_file, "w", encoding="utf-8") as f:
                json.dump(self._bookmarks, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_bookmark(self, page: int, name: str = ""):
        """添加书签"""
        if not name:
            name = f"书签 {len(self._bookmarks) + 1}"
        bookmark = {"name": name, "page": page}
        self._bookmarks.append(bookmark)
        item = QListWidgetItem(f"[第 {page + 1} 页] {name}")
        item.setData(Qt.ItemDataRole.UserRole, page)
        self._list.addItem(item)
        self._save_bookmarks_file()
        self._update_empty_label()

    def _show_context_menu(self, pos):
        item = self._list.itemAt(pos)
        menu = QMenu(self)
        action_add = QAction("添加当前页书签", self)
        action_add.triggered.connect(lambda: self._add_current_page_bookmark())
        menu.addAction(action_add)
        if item:
            action_del = QAction("删除此书签", self)
            action_del.triggered.connect(lambda: self._delete_bookmark(item))
            menu.addAction(action_del)
        action_clear = QAction("清空所有书签", self)
        action_clear.triggered.connect(self._clear_bookmarks)
        menu.addAction(action_clear)
        menu.exec(self._list.mapToGlobal(pos))

    def _add_current_page_bookmark(self):
        """通过对话框添加当前页书签"""
        if not self._document:
            return
        # 获取当前页（由主窗口设置）
        page = getattr(self, "_current_page", 0)
        name, ok = QInputDialog.getText(self, "添加书签", "书签名称：",
                                        text=f"第 {page + 1} 页")
        if ok and name:
            self.add_bookmark(page, name)

    def set_current_page(self, page: int):
        """设置当前页码（用于添加书签）"""
        self._current_page = page

    def _delete_bookmark(self, item: QListWidgetItem):
        row = self._list.row(item)
        if 0 <= row < len(self._bookmarks):
            del self._bookmarks[row]
            self._list.takeItem(row)
            self._save_bookmarks_file()
            self._update_empty_label()

    def _clear_bookmarks(self):
        self._bookmarks = []
        self._list.clear()
        self._save_bookmarks_file()
        self._update_empty_label()

    def _on_item_double_clicked(self, item):
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is not None and page >= 0:
            self.page_selected.emit(page)

    def _update_empty_label(self):
        if self._list.count() == 0:
            self._empty_label.show()
        else:
            self._empty_label.hide()


# ── 侧边栏主组件 ──────────────────────────────────────────────

class Sidebar(QWidget):
    """侧边栏：缩略图、目录大纲、书签收藏"""

    page_selected = Signal(int)
    close_requested = Signal()  # 请求关闭侧边栏

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题行：右对齐的关闭按钮（独立于标签栏，避免被裁剪）
        header = QWidget()
        header.setStyleSheet("QWidget { background: transparent; }")
        hlayout = QHBoxLayout(header)
        hlayout.setContentsMargins(4, 3, 6, 3)
        hlayout.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(48, 24)
        close_btn.setToolTip("关闭侧边栏 (F9)")
        close_btn.setStyleSheet(
            "QPushButton { border: 1px solid #ccc; border-radius: 4px;"
            "  color: #333; font-size: 12px; background: #f5f5f5; }"
            "QPushButton:hover { color: #fff; background: #e74c3c; border-color: #e74c3c; }"
            "QPushButton:pressed { background: #c0392b; }"
        )
        close_btn.clicked.connect(self.close_requested.emit)
        hlayout.addWidget(close_btn)
        layout.addWidget(header)

        # 标签页
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        layout.addWidget(self._tabs)

        self.thumbnails_tab = ThumbnailsTab()
        self.outline_tab = OutlineTab()
        self.bookmarks_tab = BookmarksTab()

        self._tabs.addTab(self.thumbnails_tab, "缩略图")
        self._tabs.addTab(self.outline_tab, "目录")
        self._tabs.addTab(self.bookmarks_tab, "书签")

        # 转发信号
        self.thumbnails_tab.page_selected.connect(self.page_selected)
        self.outline_tab.page_selected.connect(self.page_selected)
        self.bookmarks_tab.page_selected.connect(self.page_selected)

        self.setMinimumWidth(180)
        self.setMaximumWidth(400)

    def load_document(self, document, file_path: str):
        """加载文档到所有标签页"""
        self.thumbnails_tab.load_document(document)
        self.outline_tab.load_outline(document.get_outline() if document else [])
        self.bookmarks_tab.set_document(document, file_path)

    def update_current_page(self, page: int):
        """更新当前页码到各标签页"""
        self.thumbnails_tab.highlight_page(page)
        self.bookmarks_tab.set_current_page(page)
