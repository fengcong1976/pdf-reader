"""PDF 视图渲染模块 - 页面显示、缩放、旋转、搜索高亮、区域框选"""

import pymupdf
from PySide6.QtCore import Qt, QSize, QRect, QPoint, Signal, QTimer
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QPen, QMouseEvent, QTransform,
    QCursor, QKeySequence, QShortcut
)
from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QSizePolicy, QApplication
)
from typing import Optional, List, Tuple


class PDFPageWidget(QWidget):
    """单个 PDF 页面渲染组件"""

    page_clicked = Signal(int)  # 页码（0-based）
    page_double_clicked = Signal(int)  # 双击页码（0-based）
    region_drawn = Signal(int, QRect)  # 画框识别：页码（0-based）+ widget 坐标矩形
    text_selected = Signal(int, QRect)  # 划词选择：页码（0-based）+ widget 坐标矩形

    def __init__(self, page_num: int, parent=None):
        super().__init__(parent)
        self._page_num = page_num
        self._pixmap: Optional[QPixmap] = None
        self._highlight_rects: List[QRect] = []  # 搜索高亮（已旋转的 widget 坐标）
        self._current_highlight: Optional[QRect] = None
        self._scale = 1.0
        self._rendered_scale = 0.0
        # 画框选择
        self._select_mode = False
        self._selecting = False
        self._select_origin: Optional[QPoint] = None
        self._select_current: Optional[QPoint] = None
        # 划词拖选（普通模式下拖动选文本）
        self._drag_origin: Optional[QPoint] = None
        self._drag_current: Optional[QPoint] = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    @property
    def page_num(self) -> int:
        return self._page_num

    def set_pixmap(self, pixmap: QPixmap, scale: float):
        """设置页面图像（pixmap 已在外部旋转好）"""
        self._pixmap = pixmap
        self._rendered_scale = scale
        self.update_size()
        self.update()

    def update_size(self):
        if self._pixmap:
            self.setFixedSize(self._pixmap.size())
        else:
            self.setFixedSize(200, 300)

    def set_scale(self, scale: float):
        self._scale = scale

    def set_highlights(self, rects: List[QRect]):
        self._highlight_rects = rects
        self.update()

    def set_current_highlight(self, rect: Optional[QRect]):
        self._current_highlight = rect
        self.update()

    def clear_highlights(self):
        self._highlight_rects = []
        self._current_highlight = None
        self.update()

    # ── 画框选择 ─────────────────────────────────────────────────

    def set_select_mode(self, enabled: bool):
        """开启/关闭画框模式（十字光标）"""
        self._select_mode = enabled
        self.setCursor(
            QCursor(Qt.CursorShape.CrossCursor) if enabled
            else QCursor(Qt.CursorShape.ArrowCursor)
        )
        self.clear_text_selection()  # 模式切换时清掉保持的划词选框
        if not enabled:
            self._selecting = False
            self._select_origin = None
            self._select_current = None
            self.update()

    def clear_text_selection(self):
        """清除保持显示的划词选框"""
        if self._drag_origin is not None or self._drag_current is not None:
            self._drag_origin = None
            self._drag_current = None
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._pixmap:
            painter.drawPixmap(0, 0, self._pixmap)
        else:
            painter.fillRect(self.rect(), QColor(240, 240, 240))
            painter.setPen(QPen(QColor(180, 180, 180)))
            painter.drawRect(self.rect())

        # 画框过程中的橡皮筋矩形
        if self._selecting and self._select_origin is not None \
                and self._select_current is not None:
            rubber = QRect(self._select_origin, self._select_current).normalized()
            painter.fillRect(rubber, QColor(26, 110, 240, 45))
            pen = QPen(QColor(20, 90, 220), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(rubber)

        # 划词拖选的橡皮筋矩形
        if self._drag_origin is not None and self._drag_current is not None:
            rubber = QRect(self._drag_origin, self._drag_current).normalized()
            painter.fillRect(rubber, QColor(26, 110, 240, 45))
            painter.setPen(QPen(QColor(20, 90, 220), 1, Qt.PenStyle.DashLine))
            painter.drawRect(rubber)

        for rect in self._highlight_rects:
            painter.fillRect(rect, QColor(255, 255, 0, 80))
            painter.setPen(QPen(QColor(255, 200, 0), 1))
            painter.drawRect(rect)

        if self._current_highlight:
            painter.fillRect(self._current_highlight, QColor(255, 140, 0, 120))
            painter.setPen(QPen(QColor(255, 100, 0), 2))
            painter.drawRect(self._current_highlight)

        if self._pixmap:
            painter.setPen(QPen(QColor(100, 100, 100), 1))
            painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._select_mode:
                # 开始拖框（同时通知当前页变化）
                self._selecting = True
                self._select_origin = event.position().toPoint()
                self._select_current = event.position().toPoint()
                self.page_clicked.emit(self._page_num)
                event.accept()
                return
            # 普通模式：清除上一次保持的划词选框，记录新拖选起点
            self._drag_origin = None
            self._drag_current = None
            self._drag_origin = event.position().toPoint()
            self._drag_current = self._drag_origin
            self.page_clicked.emit(self._page_num)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._select_mode and self._selecting:
            self._select_current = event.position().toPoint()
            self.update()
            event.accept()
            return
        if self._drag_origin is not None \
                and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag_current = event.position().toPoint()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._select_mode and self._selecting:
            self._selecting = False
            rect = QRect(self._select_origin, self._select_current).normalized()
            self._select_origin = None
            self._select_current = None
            self.update()
            # 框太小视为普通点击，忽略
            if rect.width() >= 4 and rect.height() >= 4:
                self.region_drawn.emit(self._page_num, rect)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_origin is not None:
            rect = QRect(self._drag_origin, event.position().toPoint()).normalized()
            # 拖动距离足够才视为划词；选框保持显示，直到菜单选择/再次按下/缩放
            if rect.width() >= 4 and rect.height() >= 4:
                self._drag_current = rect.bottomRight()
                self._drag_origin = rect.topLeft()
                self.update()
                self.text_selected.emit(self._page_num, rect)
            else:
                self._drag_origin = None
                self._drag_current = None
                self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            # 画框模式下屏蔽双击添加书签
            if not self._select_mode:
                self.page_double_clicked.emit(self._page_num)
        super().mouseDoubleClickEvent(event)


class PDFView(QScrollArea):
    """PDF 连续滚动视图"""

    page_changed = Signal(int)  # 当前页面变化信号
    scale_changed = Signal(float)  # 缩放变化信号
    file_dropped = Signal(str)  # 拖放打开文件信号
    page_double_clicked = Signal(int)  # 双击页面信号
    region_selected = Signal(int, tuple)  # 画框识别：页码 + 渲染坐标矩形(x0,y0,x1,y1)
    region_mode_changed = Signal(bool)  # 画框模式开关变化
    text_region_selected = Signal(int, tuple)  # 划词：页码 + 渲染坐标矩形(x0,y0,x1,y1)

    # 缩放预设
    ZOOM_LEVELS = [0.25, 0.33, 0.50, 0.67, 0.75, 0.90, 1.00,
                   1.10, 1.25, 1.50, 1.75, 2.00, 3.00, 4.00, 5.00]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._document = None
        self._page_widgets: List[PDFPageWidget] = []
        self._scale = 1.0
        self._rotation = 0
        self._fit_mode = "none"  # "none", "width", "page"
        self._search_results: List[Tuple[int, List]] = []
        self._current_search_index = -1
        self._region_select_mode = False
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_visible_pages)

        # Esc 退出画框模式（仅在画框模式下生效）
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.setEnabled(False)
        self._esc_shortcut.activated.connect(lambda: self.set_region_select_mode(False))

        # 容器
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._layout.setSpacing(10)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setAcceptDrops(True)

        # 滚动监听
        self.verticalScrollBar().valueChanged.connect(
            lambda: self._render_timer.start(150)
        )

    def set_document(self, document):
        """设置文档并初始化页面"""
        self._document = document
        self._clear_pages()
        if not document or not document.is_loaded:
            return

        # 创建所有页面的占位 widget
        for i in range(document.page_count):
            widget = PDFPageWidget(i)
            widget.set_scale(self._scale)
            widget.page_clicked.connect(self._on_page_clicked)
            widget.page_double_clicked.connect(self.page_double_clicked.emit)
            widget.region_drawn.connect(self._on_region_drawn)
            widget.text_selected.connect(self._on_text_region_drawn)
            widget.set_select_mode(self._region_select_mode)
            self._page_widgets.append(widget)
            self._layout.addWidget(widget)

        # 先设置占位尺寸，再渲染可见页面
        self._init_page_sizes()
        QTimer.singleShot(50, self._render_visible_pages)

    def _init_page_sizes(self):
        """用原始尺寸初始化占位 widget 大小（渲染后由 widget 自己管理）"""
        if not self._document:
            return
        for i, widget in enumerate(self._page_widgets):
            w, h = self._document.get_page_size(i)
            widget.setFixedSize(int(w * self._scale), int(h * self._scale))
            widget._rendered_rotation = -1  # 标记待渲染

    def _clear_pages(self):
        for widget in self._page_widgets:
            self._layout.removeWidget(widget)
            widget.deleteLater()
        self._page_widgets = []

    # ── 渲染 ────────────────────────────────────────────────────

    def _render_page(self, widget: PDFPageWidget, page_num: int):
        """渲染单个页面到 widget（在渲染阶段旋转 QPixmap）"""
        if not self._document or not widget:
            return
        pix = self._document.get_page_pixmap(page_num, self._scale)
        if pix:
            qimg = self._pixmap_to_qimage(pix)
            qpixmap = QPixmap.fromImage(qimg)
            # 旋转 QPixmap（0/90/180/270）
            if self._rotation != 0:
                qpixmap = qpixmap.transformed(
                    QTransform().rotate(self._rotation),
                    Qt.TransformationMode.SmoothTransformation,
                )
            widget.set_pixmap(qpixmap, self._scale)

    def _render_visible_pages(self):
        """渲染可见范围内的页面：每轮只渲染最靠近视口中心的一页，
        剩余的让出界面后再继续，避免大页面渲染时界面卡死"""
        if not self._document or not self._page_widgets:
            return
        scroll_pos = self.verticalScrollBar().value()
        viewport_rect = self.viewport().rect()
        view_top = scroll_pos - 200  # 预渲染上下各 200px
        view_bottom = scroll_pos + viewport_rect.height() + 200
        center_y = scroll_pos + viewport_rect.height() // 2

        candidates = []
        for widget in self._page_widgets:
            if widget.height() == 0:
                continue
            widget_top = widget.pos().y()
            widget_bottom = widget_top + widget.height()
            # 可见范围内的页面
            if widget_bottom >= view_top and widget_top <= view_bottom:
                need_render = (
                    widget._pixmap is None
                    or abs(widget._rendered_scale - self._scale) > 0.01
                    or getattr(widget, '_rendered_rotation', -1) != self._rotation
                )
                if need_render:
                    candidates.append(widget)
        if not candidates:
            return

        # 最靠近视口中心的先渲染（当前阅读页优先）
        widget = min(
            candidates,
            key=lambda w: abs(w.pos().y() + w.height() / 2 - center_y),
        )
        self._render_page(widget, widget.page_num)
        widget._rendered_rotation = self._rotation
        # 还有待渲染页面时，让出界面一帧再继续
        QTimer.singleShot(10, self._render_visible_pages)

    @staticmethod
    def _pixmap_to_qimage(pixmap: pymupdf.Pixmap) -> QImage:
        """PyMuPDF Pixmap 转 QImage"""
        if pixmap.alpha:
            fmt = QImage.Format.Format_RGBA8888
        else:
            fmt = QImage.Format.Format_RGB888
        qimg = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, fmt)
        return qimg.copy()  # 复制数据避免内存问题

    # ── 缩放与旋转 ──────────────────────────────────────────────

    def set_scale(self, scale: float):
        """设置缩放比例"""
        self._scale = max(0.1, min(10.0, scale))
        self._fit_mode = "none"
        self._apply_scale_to_all()
        self.scale_changed.emit(self._scale)
        self._render_timer.start(50)

    def zoom_in(self):
        """放大"""
        for level in self.ZOOM_LEVELS:
            if level > self._scale:
                self.set_scale(level)
                return
        self.set_scale(self._scale * 1.25)

    def zoom_out(self):
        """缩小"""
        for level in reversed(self.ZOOM_LEVELS):
            if level < self._scale:
                self.set_scale(level)
                return
        self.set_scale(self._scale * 0.8)

    def reset_zoom(self):
        """重置缩放为 100%"""
        self.set_scale(1.0)

    def fit_width(self):
        """适应宽度"""
        if not self._document or not self._page_widgets:
            return
        self._fit_mode = "width"
        viewport_width = self.viewport().width() - 60  # 留边距
        # 用第一个页面计算缩放
        w, h = self._document.get_page_size(0)
        if w > 0:
            self.set_scale(viewport_width / w)

    def fit_page(self):
        """适应整页"""
        if not self._document or not self._page_widgets:
            return
        self._fit_mode = "page"
        viewport_w = self.viewport().width() - 60
        viewport_h = self.viewport().height() - 60
        w, h = self._document.get_page_size(0)
        if w > 0 and h > 0:
            scale_w = viewport_w / w
            scale_h = viewport_h / h
            self.set_scale(min(scale_w, scale_h))

    def rotate_clockwise(self):
        """顺时针旋转 90°"""
        self._rotation = (self._rotation + 90) % 360
        self._apply_scale_to_all()
        self._render_timer.start(50)

    def rotate_counterclockwise(self):
        """逆时针旋转 90°"""
        self._rotation = (self._rotation - 90) % 360
        self._apply_scale_to_all()
        self._render_timer.start(50)

    def _apply_scale_to_all(self):
        """应用当前缩放/旋转到所有页面（标记为需要重渲染）"""
        if not self._document:
            return
        self.clear_text_selection()  # 坐标随缩放变化，清掉保持的划词选框
        for i, widget in enumerate(self._page_widgets):
            w, h = self._document.get_page_size(i)
            # 先设占位尺寸，渲染后 widget 自己会调整
            widget.setFixedSize(int(w * self._scale), int(h * self._scale))
            widget._rendered_rotation = -1  # 标记需要重新渲染旋转后的 pixmap

    def resizeEvent(self, event):
        """窗口大小变化时，如果处于适应模式则重新计算"""
        super().resizeEvent(event)
        if self._fit_mode == "width":
            self.fit_width()
        elif self._fit_mode == "page":
            self.fit_page()

    def wheelEvent(self, event):
        """Ctrl+滚轮缩放，普通滚轮滚动页面"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    # ── 页面导航 ─────────────────────────────────────────────────

    def go_to_page(self, page_num: int):
        """跳转到指定页面（0-based）"""
        if not self._page_widgets or page_num < 0 or page_num >= len(self._page_widgets):
            return
        widget = self._page_widgets[page_num]
        self.ensureVisible(0, widget.pos().y(), 0, 50)
        self.page_changed.emit(page_num)

    def next_page(self):
        """下一页"""
        current = self.get_current_page()
        if current < len(self._page_widgets) - 1:
            self.go_to_page(current + 1)

    def prev_page(self):
        """上一页"""
        current = self.get_current_page()
        if current > 0:
            self.go_to_page(current - 1)

    def first_page(self):
        """第一页"""
        self.go_to_page(0)

    def last_page(self):
        """最后一页"""
        if self._page_widgets:
            self.go_to_page(len(self._page_widgets) - 1)

    def get_current_page(self) -> int:
        """获取当前可见页码"""
        if not self._page_widgets:
            return 0
        scroll_pos = self.verticalScrollBar().value()
        viewport_h = self.viewport().height()
        center_y = scroll_pos + viewport_h // 2
        for i, widget in enumerate(self._page_widgets):
            top = widget.pos().y()
            bottom = top + widget.height()
            if top <= center_y <= bottom:
                return i
            if top > center_y:
                return max(0, i - 1)
        return len(self._page_widgets) - 1

    def _on_page_clicked(self, page_num: int):
        self.page_changed.emit(page_num)

    # ── 搜索高亮 ────────────────────────────────────────────────

    def set_search_results(self, results: List[Tuple[int, List]]):
        """设置搜索结果并高亮"""
        self._search_results = results
        self._current_search_index = -1
        self._apply_search_highlights()

    def _apply_search_highlights(self):
        """将搜索结果应用到页面 widget 上"""
        # 清除所有旧高亮
        for widget in self._page_widgets:
            widget.clear_highlights()

        if not self._search_results:
            return

        for page_num, rects in self._search_results:
            if page_num >= len(self._page_widgets):
                continue
            widget = self._page_widgets[page_num]
            qrects = []
            for rect in rects:
                # 将 PDF 坐标转为 widget 坐标
                x, y = self._pdf_to_widget_coords(page_num, rect.x0, rect.y0)
                x2, y2 = self._pdf_to_widget_coords(page_num, rect.x1, rect.y1)
                qrects.append(QRect(int(x), int(y), int(x2 - x), int(y2 - y)))
            widget.set_highlights(qrects)

    def _pdf_to_widget_coords(self, page_num: int, x: float, y: float) -> Tuple[float, float]:
        """将 PDF 页面坐标转为旋转后的 widget 显示坐标"""
        if not self._document:
            return (x, y)
        pw, ph = self._document.get_page_size(page_num)
        W, H = pw * self._scale, ph * self._scale  # 旋转前的渲染尺寸
        sx, sy = x * self._scale, y * self._scale
        # QPixmap.rotate 后的坐标映射（与 _render_page 的 QTransform 一致）
        if self._rotation == 90:    # 顺时针 90°: (x,y) → (H-y, x)
            return (H - sy, sx)
        elif self._rotation == 180: # 180°: (x,y) → (W-x, H-y)
            return (W - sx, H - sy)
        elif self._rotation == 270: # 逆时针 90°: (x,y) → (y, W-x)
            return (sy, W - sx)
        return (sx, sy)

    def goto_search_result(self, index: int):
        """跳转到第 index 个搜索结果"""
        if not self._search_results or index < 0 or index >= len(self._search_results):
            return
        page_num, rects = self._search_results[index]
        self._current_search_index = index
        self.go_to_page(page_num)
        # 更新当前高亮
        for i, (pn, rs) in enumerate(self._search_results):
            if pn < len(self._page_widgets):
                if i == index and rects:
                    rect = rects[0]
                    x, y = self._pdf_to_widget_coords(pn, rect.x0, rect.y0)
                    x2, y2 = self._pdf_to_widget_coords(pn, rect.x1, rect.y1)
                    self._page_widgets[pn].set_current_highlight(
                        QRect(int(x), int(y), int(x2 - x), int(y2 - y))
                    )
                else:
                    self._page_widgets[pn].set_current_highlight(None)

    def next_search_result(self):
        """下一个搜索结果"""
        if self._search_results:
            idx = (self._current_search_index + 1) % len(self._search_results)
            self.goto_search_result(idx)
            return idx
        return -1

    def prev_search_result(self):
        """上一个搜索结果"""
        if self._search_results:
            idx = (self._current_search_index - 1) % len(self._search_results)
            self.goto_search_result(idx)
            return idx
        return -1

    def clear_search(self):
        """清除搜索高亮"""
        self._search_results = []
        self._current_search_index = -1
        for widget in self._page_widgets:
            widget.clear_highlights()

    def get_search_count(self) -> int:
        """搜索结果总数（跨页面）"""
        return sum(len(rects) for _, rects in self._search_results)

    # ── 画框识别 ────────────────────────────────────────────────

    def is_region_select_mode(self) -> bool:
        return self._region_select_mode

    @property
    def rotation(self) -> int:
        """当前界面旋转角度（0/90/180/270）"""
        return self._rotation

    def set_region_select_mode(self, enabled: bool):
        """开启/关闭画框选择模式"""
        if self._region_select_mode == enabled:
            return
        self._region_select_mode = enabled
        for widget in self._page_widgets:
            widget.set_select_mode(enabled)
        self.viewport().setCursor(
            QCursor(Qt.CursorShape.CrossCursor) if enabled
            else QCursor(Qt.CursorShape.ArrowCursor)
        )
        self._esc_shortcut.setEnabled(enabled)
        self.region_mode_changed.emit(enabled)

    def _on_region_drawn(self, page_num: int, widget_rect: QRect):
        """页面上画出矩形 → 转换为渲染坐标并发出信号"""
        render_rect = self._widget_rect_to_render_rect(page_num, widget_rect)
        if render_rect is not None:
            self.region_selected.emit(page_num, render_rect)

    def _on_text_region_drawn(self, page_num: int, widget_rect: QRect):
        """划词拖选完成 → 转换为渲染坐标并发出信号"""
        render_rect = self._widget_rect_to_render_rect(page_num, widget_rect)
        if render_rect is not None:
            self.text_region_selected.emit(page_num, render_rect)

    def clear_text_selection(self):
        """清除所有页面保持显示的划词选框（菜单选择后/缩放旋转后调用）"""
        for widget in self._page_widgets:
            widget.clear_text_selection()

    def _widget_rect_to_render_rect(
        self, page_num: int, rect: QRect
    ) -> Optional[Tuple[float, float, float, float]]:
        """widget 显示坐标矩形 → zoom=1 渲染坐标矩形（已含 PDF 自带旋转，未含界面旋转）

        先对四个角做界面旋转的逆变换，再取轴对齐外包矩形。
        返回 (x0, y0, x1, y1)，单位为 PDF 渲染像素/点。
        """
        if not self._document:
            return None
        pw, ph = self._document.get_page_size(page_num)
        W, H = pw * self._scale, ph * self._scale
        corners = (
            (rect.left(), rect.top()),
            (rect.right(), rect.top()),
            (rect.right(), rect.bottom()),
            (rect.left(), rect.bottom()),
        )
        pts = []
        for wx, wy in corners:
            if self._rotation == 90:      # 正变换 (x,y)→(H-y, x)
                sx, sy = wy, H - wx
            elif self._rotation == 180:   # 正变换 (x,y)→(W-x, H-y)
                sx, sy = W - wx, H - wy
            elif self._rotation == 270:   # 正变换 (x,y)→(y, W-x)
                sx, sy = W - wy, wx
            else:
                sx, sy = wx, wy
            pts.append((sx / self._scale, sy / self._scale))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    # ── 拖放支持 ────────────────────────────────────────────────

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
                self.file_dropped.emit(fp)
                event.acceptProposedAction()
                return
        event.ignore()
