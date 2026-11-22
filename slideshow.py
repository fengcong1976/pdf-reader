"""幻灯片放映模块 - 全屏黑底逐页演示 PDF

操作：
  下一页：左键单击 / → / ↓ / 空格 / PageDown / 回车
  上一页：右键单击 / ← / ↑ / PageUp
  第一页/最后一页：Home / End
  聚光灯（显微镜放大）：控制条按钮或 S；激光灯：控制条按钮或 L
  画笔涂写：控制条按钮或 D；清除当前页笔迹：C
  缩放：控制条滑块/＋－/适页，或 Ctrl+滚轮；放大后按住左键拖拽平移
  Esc：退出全屏（控制条上也有“退出全屏”按钮）
  控制条移动鼠标即显示，静止 2.5 秒自动隐藏
"""

import pymupdf
from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, Signal
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QTransform, QKeySequence, QShortcut,
    QPen, QPainterPath, QRadialGradient, QBrush
)
from PySide6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QPushButton, QLabel, QComboBox, QSlider
)
from typing import Optional, List, Tuple

# 自动播放可选间隔（秒）
INTERVALS = ["3", "5", "10", "15", "30"]
DEFAULT_INTERVAL = "5"
# 页面四周留黑边（像素）
PAGE_MARGIN = 24
# 控制条自动隐藏延时（毫秒）
BAR_HIDE_DELAY = 2500
# 聚光灯半径（取窗口短边的比例）
SPOTLIGHT_RATIO = 0.14
SPOTLIGHT_MIN_RADIUS = 70
# 聚光灯（显微镜）放大倍数
SPOTLIGHT_ZOOM = 1.2
# 聚光灯遮罩颜色（外圈暗化程度）
SPOTLIGHT_OVERLAY = QColor(0, 0, 0, 165)
# 激光灯：亮芯半径 / 光晕半径（像素）
LASER_CORE_RADIUS = 5.0
LASER_GLOW_RADIUS = 24.0
LASER_CORE_COLOR = QColor(46, 255, 70)
LASER_GLOW_INNER = QColor(0, 255, 40, 200)
# 画笔颜色（名称, 色值）
PEN_COLORS: List[Tuple[str, str]] = [
    ("红笔", "#e02020"),
    ("黄笔", "#ffd400"),
    ("蓝笔", "#2f7bff"),
    ("白笔", "#ffffff"),
    ("绿笔", "#22c55e"),
]
# 笔迹宽度（相对窗口高度的比例）
STROKE_WIDTH_RATIO = 0.0045
# 缩放滑块范围（相对“适应页面”的百分比）
ZOOM_MIN = 50
ZOOM_MAX = 400
ZOOM_STEP = 10
ZOOM_FIT = 100
# 超过此像素位移即判定为拖拽平移而非点击翻页
PAN_THRESHOLD = 5


class SlideshowWindow(QWidget):
    """全屏幻灯片放映窗口"""

    closed = Signal()  # 放映窗口关闭（Esc / 退出按钮等任意路径）

    def __init__(self, document, start_page: int = 0, rotation: int = 0, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self._document = document
        self._current = max(0, min(start_page, max(0, document.page_count - 1)))
        self._rotation = rotation
        self._pixmap: Optional[QPixmap] = None
        self._playing = False
        self._bar_first_shown = False
        # 缩放（相对适应页面的倍率）与平移偏移
        self._fit_scale = 1.0
        self._user_zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self._pan_moved = False
        self._pan_press_pos: Optional[QPoint] = None
        self._pan_start: Optional[QPoint] = None
        # 缩放控件回调时抑制滑块信号
        self._syncing_zoom = False
        # 最近一次鼠标位置（作为滑块缩放的锚点）
        self._mouse_pos: Optional[QPoint] = None

        # 聚光灯
        self._spotlight_on = False
        self._spotlight_pos: Optional[QPoint] = None
        # 激光灯
        self._laser_on = False
        self._laser_pos: Optional[QPoint] = None
        # 涂写：{页码: [(颜色hex, [(归一化x, 归一化y), ...]), ...]}
        self._strokes: dict = {}
        self._draw_on = False
        self._drawing = False
        self._current_stroke: Optional[Tuple[str, list]] = None

        self.setWindowTitle("幻灯片放映")
        self.setStyleSheet("background: #000;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_control_bar()

        # 控制条自动隐藏
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: self._set_bar_visible(False))

        # 自动播放
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self.next_page)

        # Esc 退出（优先级最高的退出路径）
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(self.close)
        # S 聚光灯、L 激光灯、D 画笔、C 清除当前页笔迹
        for key, slot in (
            (Qt.Key.Key_S, self.toggle_spotlight),
            (Qt.Key.Key_L, self.toggle_laser),
            (Qt.Key.Key_D, self.toggle_draw),
            (Qt.Key.Key_C, self.clear_current_strokes),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(slot)

        self._render_page()
        self._set_bar_visible(True)

    def closeEvent(self, event):
        """任意路径退出全屏时停止定时器并通知主窗口"""
        self._play_timer.stop()
        self._hide_timer.stop()
        self.closed.emit()
        super().closeEvent(event)

    # ── 控制条 ───────────────────────────────────────────────────

    def _build_control_bar(self):
        self._bar = QFrame(self)
        self._bar.setObjectName("slideBar")
        self._bar.setStyleSheet(
            "QFrame#slideBar {"
            "background: rgba(20, 20, 20, 215);"
            "border-radius: 10px;"
            "}"
            "QPushButton {"
            "color: white; background: transparent; border: none;"
            "padding: 6px 14px; font-size: 14px; min-height: 26px;"
            "}"
            "QPushButton:hover { background: rgba(255, 255, 255, 45); border-radius: 6px; }"
            "QPushButton:checked {"
            "background: #1a5fb4; color: white; font-weight: bold; border-radius: 6px;"
            "}"
            "QLabel { color: #ddd; font-size: 13px; }"
            "QComboBox {"
            "color: white; background: rgba(255,255,255,30);"
            "border-radius: 4px; padding: 2px 6px; min-height: 22px;"
            "}"
            "QComboBox QAbstractItemView {"
            "color: white; background: #2b2b2b; selection-background-color: #1a5fb4;"
            "}"
            "QSlider::groove:horizontal {"
            "height: 4px; background: rgba(255,255,255,60); border-radius: 2px;"
            "}"
            "QSlider::sub-page:horizontal {"
            "background: #1a5fb4; border-radius: 2px;"
            "}"
            "QSlider::handle:horizontal {"
            "background: white; width: 12px; height: 12px;"
            "margin: -5px 0; border-radius: 6px;"
            "}"
        )
        # 鼠标移到功能条上一律显示正常箭头（激光/画笔模式也不例外）
        self._bar.setCursor(Qt.CursorShape.ArrowCursor)
        layout = QHBoxLayout(self._bar)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(4)

        self._prev_btn = QPushButton("上一页")
        self._prev_btn.clicked.connect(self.prev_page)
        self._play_btn = QPushButton("播放")
        self._play_btn.setCheckable(True)
        self._play_btn.toggled.connect(self._on_play_toggled)
        self._next_btn = QPushButton("下一页")
        self._next_btn.clicked.connect(self.next_page)
        self._exit_btn = QPushButton("退出全屏")
        self._exit_btn.setToolTip("退出全屏放映，返回普通窗口（Esc）")
        self._exit_btn.clicked.connect(self.close)

        self._page_label = QLabel("")
        self._page_label.setMinimumWidth(90)
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._interval_combo = QComboBox()
        self._interval_combo.addItems([f"{s} 秒/页" for s in INTERVALS])
        idx = INTERVALS.index(DEFAULT_INTERVAL) if DEFAULT_INTERVAL in INTERVALS else 1
        self._interval_combo.setCurrentIndex(idx)
        self._interval_combo.currentIndexChanged.connect(self._restart_play_timer)

        # 聚光灯 / 画笔涂写
        self._spot_btn = QPushButton("聚光灯(S)")
        self._spot_btn.setCheckable(True)
        self._spot_btn.setToolTip(
            f"开启/关闭聚光灯（S）：鼠标周围圆形区域放大突出显示（{SPOTLIGHT_ZOOM:g} 倍），与激光灯互斥"
        )
        self._spot_btn.toggled.connect(self.toggle_spotlight)

        self._laser_btn = QPushButton("激光灯(L)")
        self._laser_btn.setCheckable(True)
        self._laser_btn.setToolTip("开启/关闭激光灯（L）：高亮绿色光点跟随鼠标指示，与聚光灯互斥")
        self._laser_btn.toggled.connect(self.toggle_laser)

        self._draw_btn = QPushButton("画笔(D)")
        self._draw_btn.setCheckable(True)
        self._draw_btn.setToolTip("开启/关闭画笔涂写（D）：按住左键书写，与聚光灯、激光灯互斥")
        self._draw_btn.toggled.connect(self.toggle_draw)

        self._color_combo = QComboBox()
        self._color_combo.addItems([name for name, _ in PEN_COLORS])
        self._color_combo.setToolTip("画笔颜色")

        self._clear_btn = QPushButton("清除(C)")
        self._clear_btn.setToolTip("清除当前页的涂写笔迹（C）")
        self._clear_btn.clicked.connect(self.clear_current_strokes)

        # 缩放拖拽条（相对适应页面 50%~400%）
        self._zoom_out_btn = QPushButton("－")
        self._zoom_out_btn.setFixedWidth(34)
        self._zoom_out_btn.setToolTip("缩小")
        self._zoom_out_btn.clicked.connect(lambda: self._step_zoom(-ZOOM_STEP))
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(ZOOM_MIN, ZOOM_MAX)
        self._zoom_slider.setSingleStep(ZOOM_STEP)
        self._zoom_slider.setPageStep(ZOOM_STEP * 5)
        self._zoom_slider.setValue(ZOOM_FIT)
        self._zoom_slider.setFixedWidth(110)
        self._zoom_slider.setToolTip("缩放：放大后可在页面上按住左键拖拽平移")
        self._zoom_slider.valueChanged.connect(
            lambda v: self.set_user_zoom(v / 100.0)
        )
        self._zoom_in_btn = QPushButton("＋")
        self._zoom_in_btn.setFixedWidth(34)
        self._zoom_in_btn.setToolTip("放大")
        self._zoom_in_btn.clicked.connect(lambda: self._step_zoom(ZOOM_STEP))
        self._zoom_fit_btn = QPushButton("适页")
        self._zoom_fit_btn.setToolTip("恢复适应页面大小（100%）")
        self._zoom_fit_btn.clicked.connect(lambda: self._zoom_slider.setValue(ZOOM_FIT))
        self._zoom_label = QLabel("100%")
        self._zoom_label.setMinimumWidth(42)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (self._zoom_out_btn, self._zoom_slider, self._zoom_in_btn,
                  self._zoom_fit_btn, self._zoom_label):
            w.setCursor(Qt.CursorShape.ArrowCursor)

        layout.addWidget(self._prev_btn)
        layout.addWidget(self._play_btn)
        layout.addWidget(self._next_btn)
        layout.addSpacing(8)
        layout.addWidget(self._spot_btn)
        layout.addWidget(self._laser_btn)
        layout.addWidget(self._draw_btn)
        layout.addWidget(self._color_combo)
        layout.addWidget(self._clear_btn)
        layout.addSpacing(8)
        layout.addWidget(self._zoom_out_btn)
        layout.addWidget(self._zoom_slider)
        layout.addWidget(self._zoom_in_btn)
        layout.addWidget(self._zoom_fit_btn)
        layout.addWidget(self._zoom_label)
        layout.addSpacing(8)
        layout.addWidget(self._page_label)
        layout.addSpacing(8)
        self._interval_label = QLabel("间隔")
        layout.addWidget(self._interval_label)
        layout.addWidget(self._interval_combo)
        layout.addSpacing(10)
        layout.addWidget(self._exit_btn)

        # 功能条上的每个子控件都强制箭头光标（防止继承窗口的隐藏/十字光标）
        for child in self._bar.findChildren(QWidget):
            child.setCursor(Qt.CursorShape.ArrowCursor)

        self._bar.adjustSize()

    def _can_pan(self) -> bool:
        return (self._pixmap is not None
                and (self._pixmap.width() > self.width()
                     or self._pixmap.height() > self.height()))

    def _apply_cursor(self):
        """光标：画笔十字 / 激光隐藏 / 拖拽中抓手 / 可平移张开手 / 其余箭头"""
        if self._draw_on:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._laser_on:
            self.setCursor(Qt.CursorShape.BlankCursor)
        elif self._panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._can_pan():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _set_bar_visible(self, visible: bool):
        self._bar.setVisible(visible)
        if visible:
            self._reposition_bar()
            self._apply_cursor()
            # 首次进入时控制条多停留一会，方便找到「播放」按钮
            if not self._bar_first_shown:
                self._hide_timer.start(6000)
                self._bar_first_shown = True
            else:
                self._hide_timer.start(BAR_HIDE_DELAY)
        elif not (self._spotlight_on or self._draw_on):
            # 普通浏览时隐藏控制条连同光标；聚光灯/画笔模式下保留光标
            self.setCursor(Qt.CursorShape.BlankCursor)

    def _reposition_bar(self):
        self._bar.adjustSize()
        x = (self.width() - self._bar.width()) // 2
        y = self.height() - self._bar.height() - 28
        self._bar.move(max(0, x), max(0, y))

    # ── 渲染 ─────────────────────────────────────────────────────

    def _render_page(self):
        self._pixmap = None
        if not self._document or not self._document.is_loaded:
            self.update()
            return
        page_num = self._current
        w, h = self._document.get_page_size(page_num)
        if w <= 0 or h <= 0:
            self.update()
            return

        avail_w = max(100, self.width() - PAGE_MARGIN * 2)
        avail_h = max(100, self.height() - PAGE_MARGIN * 2)
        # 考虑界面旋转后显示宽高互换
        if self._rotation in (90, 270):
            fit = min(avail_w / h, avail_h / w)
        else:
            fit = min(avail_w / w, avail_h / h)
        self._fit_scale = fit
        scale = fit * self._user_zoom

        pix = self._document.get_page_pixmap(page_num, zoom=scale)
        if pix is not None:
            fmt = (QImage.Format.Format_RGBA8888 if pix.alpha
                   else QImage.Format.Format_RGB888)
            qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
            qpixmap = QPixmap.fromImage(qimg)
            if self._rotation != 0:
                qpixmap = qpixmap.transformed(
                    QTransform().rotate(self._rotation),
                    Qt.TransformationMode.SmoothTransformation,
                )
            self._pixmap = qpixmap
            self._clamp_pan()

        self._page_label.setText(
            f"第 {self._current + 1} / {self._document.page_count} 页"
        )
        self.update()

    # ── 缩放与平移 ───────────────────────────────────────────────

    def _clamp_pan(self):
        """限制平移范围：页面小于视口的方向必须居中，否则不超出边缘"""
        if self._pixmap is None:
            self._pan = QPoint(0, 0)
            return
        max_x = max(0, (self._pixmap.width() - self.width()) // 2)
        max_y = max(0, (self._pixmap.height() - self.height()) // 2)
        self._pan = QPoint(
            max(-max_x, min(max_x, self._pan.x())),
            max(-max_y, min(max_y, self._pan.y())),
        )

    def _sync_zoom_widgets(self):
        self._syncing_zoom = True
        self._zoom_slider.setValue(int(round(self._user_zoom * 100)))
        self._syncing_zoom = False
        self._zoom_label.setText(f"{int(round(self._user_zoom * 100))}%")

    def set_user_zoom(self, zoom: float):
        zoom = max(ZOOM_MIN / 100.0, min(ZOOM_MAX / 100.0, zoom))
        if abs(zoom - self._user_zoom) < 0.005:
            return
        self._user_zoom = zoom
        self._sync_zoom_widgets()
        # 以当前鼠标位置为锚点缩放（无鼠标位置信息时退回中心）
        anchor = self._mouse_pos or self._spotlight_pos or self._laser_pos
        self._zoom_at(anchor)
        self._apply_cursor()

    def _step_zoom(self, delta_percent: int):
        self._zoom_slider.setValue(self._zoom_slider.value() + delta_percent)

    def _zoom_at(self, anchor: Optional[QPoint]):
        """重新渲染当前页并尽量保持 anchor 屏幕点下的内容不动"""
        if self._pixmap is not None and anchor is not None:
            old_pix = self._pixmap
            old_origin_x = (self.width() - old_pix.width()) // 2 + self._pan.x()
            old_origin_y = (self.height() - old_pix.height()) // 2 + self._pan.y()
            # 锚点在旧页面像素中的归一化位置
            ux = (anchor.x() - old_origin_x) / max(1, old_pix.width())
            uy = (anchor.y() - old_origin_y) / max(1, old_pix.height())
            self._render_page()
            if self._pixmap is not None:
                nx = int(ux * self._pixmap.width())
                ny = int(uy * self._pixmap.height())
                new_cx = (self.width() - self._pixmap.width()) // 2
                new_cy = (self.height() - self._pixmap.height()) // 2
                self._pan = QPoint(
                    anchor.x() - new_cx - nx,
                    anchor.y() - new_cy - ny,
                )
                self._clamp_pan()
                self.update()
        else:
            self._render_page()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        page_x = page_y = 0
        if self._pixmap is not None:
            page_x = (self.width() - self._pixmap.width()) // 2 + self._pan.x()
            page_y = (self.height() - self._pixmap.height()) // 2 + self._pan.y()
            painter.drawPixmap(page_x, page_y, self._pixmap)

        # 聚光灯（显微镜）：圆内以鼠标为中心放大显示页面内容
        if self._spotlight_on and self._pixmap is not None:
            center = self._spotlight_pos or QPoint(
                self.width() // 2, self.height() // 2
            )
            radius = float(max(
                SPOTLIGHT_MIN_RADIUS,
                int(min(self.width(), self.height()) * SPOTLIGHT_RATIO),
            ))
            cf = QPointF(center)
            zoom = float(SPOTLIGHT_ZOOM)
            # 先在恒等变换下建立圆形裁剪（之后再改变换不会影响裁剪区域）
            circle_path = QPainterPath()
            circle_path.addEllipse(cf, radius, radius)
            painter.save()
            painter.setClipPath(circle_path)
            # 放大绘制：以鼠标点为锚点，保证光点正下方的内容不偏移
            # screen = center + zoom * (页面像素坐标 - (center - 页面原点))
            t = QTransform()
            t.translate(float(center.x()), float(center.y()))
            t.scale(zoom, zoom)
            t.translate(
                -(float(center.x()) - float(page_x)),
                -(float(center.y()) - float(page_y)),
            )
            painter.setTransform(t)
            painter.drawPixmap(0, 0, self._pixmap)
            painter.restore()

        # 当前页涂写笔迹（含正在画的笔画）
        self._paint_strokes(painter)

        # 聚光灯外圈遮罩：整屏挖去圆形亮区（圆内即放大后的内容）
        if self._spotlight_on:
            center = self._spotlight_pos or QPoint(
                self.width() // 2, self.height() // 2
            )
            radius = float(max(
                SPOTLIGHT_MIN_RADIUS,
                int(min(self.width(), self.height()) * SPOTLIGHT_RATIO),
            ))
            # 注意：本环境 PySide6 传 QRect/QPoint 重载会触发原生崩溃，
            # 必须显式使用 QRectF/QPointF 与 float 参数
            path = QPainterPath()
            path.addRect(0.0, 0.0, float(self.width()), float(self.height()))
            cf = QPointF(center)
            path.addEllipse(cf, radius, radius)
            painter.fillPath(path, SPOTLIGHT_OVERLAY)
            # 光圈描边，强化“镜头”边界
            pen = QPen(QColor(255, 255, 255, 70), 2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(cf, radius, radius)

        # 激光灯：红色亮芯 + 径向柔光晕（绘制在最上层）
        if self._laser_on:
            center = self._laser_pos or QPoint(
                self.width() // 2, self.height() // 2
            )
            lf = QPointF(center)
            glow = QRadialGradient(lf, LASER_GLOW_RADIUS)
            glow.setColorAt(0.0, LASER_GLOW_INNER)
            glow.setColorAt(0.35, QColor(0, 255, 40, 90))
            glow.setColorAt(1.0, QColor(0, 255, 40, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(lf, LASER_GLOW_RADIUS, LASER_GLOW_RADIUS)
            # 亮芯
            painter.setBrush(QBrush(LASER_CORE_COLOR))
            painter.drawEllipse(lf, LASER_CORE_RADIUS, LASER_CORE_RADIUS)

    def _paint_strokes(self, painter: QPainter):
        """绘制当前页全部笔迹（归一化坐标 → 窗口坐标）"""
        strokes = list(self._strokes.get(self._current, []))
        if self._drawing and self._current_stroke is not None:
            strokes.append(self._current_stroke)
        if not strokes:
            return
        w, h = self.width(), max(1, self.height())
        pen_width = max(1.5, h * STROKE_WIDTH_RATIO)
        for color_hex, points in strokes:
            if not points:
                continue
            pen = QPen(QColor(color_hex), pen_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            abs_pts = [(px * w, py * h) for px, py in points]
            if len(abs_pts) == 1:
                # 单点：画一个圆点
                painter.drawPoint(int(abs_pts[0][0]), int(abs_pts[0][1]))
                continue
            for i in range(1, len(abs_pts)):
                painter.drawLine(
                    int(abs_pts[i - 1][0]), int(abs_pts[i - 1][1]),
                    int(abs_pts[i][0]), int(abs_pts[i][1]),
                )

    def resizeEvent(self, event):
        self._render_page()
        self._reposition_bar()
        super().resizeEvent(event)

    # ── 翻页 ─────────────────────────────────────────────────────

    def _finish_stroke(self):
        """键盘/滚轮翻页时，把尚未释放的笔画存入当前页"""
        if self._drawing and self._current_stroke is not None:
            color_hex, points = self._current_stroke
            if points:
                self._strokes.setdefault(self._current, []).append((color_hex, points))
            self._drawing = False
            self._current_stroke = None

    def _change_page(self, new_index: int):
        """翻到指定页：保留缩放倍率，平移回到居中"""
        if new_index == self._current:
            return
        self._current = new_index
        self._pan = QPoint(0, 0)
        self._render_page()
        self._set_bar_visible(True)

    def next_page(self):
        self._finish_stroke()
        if self._current < self._document.page_count - 1:
            self._change_page(self._current + 1)
        else:
            # 到末页时停止自动播放
            if self._playing:
                self._play_btn.setChecked(False)

    def prev_page(self):
        self._finish_stroke()
        if self._current > 0:
            self._change_page(self._current - 1)

    def first_page(self):
        self._finish_stroke()
        if self._current != 0:
            self._change_page(0)

    def last_page(self):
        self._finish_stroke()
        last = self._document.page_count - 1
        if self._current != last:
            self._change_page(last)

    # ── 自动播放 ─────────────────────────────────────────────────

    def _current_interval_ms(self) -> int:
        try:
            return int(INTERVALS[self._interval_combo.currentIndex()]) * 1000
        except Exception:
            return 5000

    def _restart_play_timer(self):
        if self._playing:
            self._play_timer.start(self._current_interval_ms())

    def _on_play_toggled(self, checked: bool):
        self._playing = checked
        self._play_btn.setText("暂停" if checked else "播放")
        if checked:
            # 已在末页时点播放，从头开始
            if self._current >= self._document.page_count - 1:
                self.first_page()
            self._play_timer.start(self._current_interval_ms())
        else:
            self._play_timer.stop()
        self._set_bar_visible(True)

    # ── 聚光灯与涂写 ─────────────────────────────────────────────

    def toggle_spotlight(self, checked: Optional[bool] = None):
        on = (not self._spotlight_on) if checked is None else checked
        if on == self._spotlight_on:
            return
        self._spotlight_on = on
        # 同步控制条按钮（避免与快捷键回环，先阻断信号）
        if self._spot_btn.isChecked() != on:
            self._spot_btn.blockSignals(True)
            self._spot_btn.setChecked(on)
            self._spot_btn.blockSignals(False)
        if on:
            # 聚光灯/激光灯/画笔三者互斥：以后选择的为准
            if self._spotlight_pos is None:
                self._spotlight_pos = QPoint(self.width() // 2, self.height() // 2)
            if self._laser_on:
                self.toggle_laser(False)
            if self._draw_on:
                self.toggle_draw(False)
        self._set_bar_visible(True)
        self.update()

    def toggle_laser(self, checked: Optional[bool] = None):
        on = (not self._laser_on) if checked is None else checked
        if on == self._laser_on:
            return
        self._laser_on = on
        if self._laser_btn.isChecked() != on:
            self._laser_btn.blockSignals(True)
            self._laser_btn.setChecked(on)
            self._laser_btn.blockSignals(False)
        if on:
            # 激光灯/聚光灯/画笔三者互斥：以后选择的为准
            if self._laser_pos is None:
                self._laser_pos = QPoint(self.width() // 2, self.height() // 2)
            if self._spotlight_on:
                self.toggle_spotlight(False)
            if self._draw_on:
                self.toggle_draw(False)
        self._apply_cursor()
        self._set_bar_visible(True)
        self.update()

    def toggle_draw(self, checked: Optional[bool] = None):
        on = (not self._draw_on) if checked is None else checked
        if on == self._draw_on:
            return
        self._draw_on = on
        if self._draw_btn.isChecked() != on:
            self._draw_btn.blockSignals(True)
            self._draw_btn.setChecked(on)
            self._draw_btn.blockSignals(False)
        if not on:
            self._drawing = False
            self._current_stroke = None
        else:
            # 画笔/聚光灯/激光灯三者互斥：以后选择的为准
            if self._spotlight_on:
                self.toggle_spotlight(False)
            if self._laser_on:
                self.toggle_laser(False)
            # 进入画笔模式时暂停自动播放，避免边写边翻页
            if self._playing:
                self._play_btn.setChecked(False)
        self._apply_cursor()
        self._set_bar_visible(True)
        self.update()

    def clear_current_strokes(self):
        if self._strokes.pop(self._current, None):
            self.update()
        self._set_bar_visible(True)

    # ── 输入事件 ─────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space,
                   Qt.Key.Key_PageDown, Qt.Key.Key_Return, Qt.Key.Key_Enter,
                   Qt.Key.Key_MediaNext):
            self.next_page()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp,
                     Qt.Key.Key_Backspace, Qt.Key.Key_MediaPrevious):
            self.prev_page()
        elif key == Qt.Key.Key_Home:
            self.first_page()
        elif key == Qt.Key.Key_End:
            self.last_page()
        else:
            super().keyPressEvent(event)

    def _to_norm(self, pos: QPoint) -> Tuple[float, float]:
        return pos.x() / max(1, self.width()), pos.y() / max(1, self.height())

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        self._mouse_pos = pos
        if event.button() == Qt.MouseButton.LeftButton:
            if self._draw_on:
                # 画笔模式：左键开始书写，不翻页
                self._drawing = True
                color_hex = PEN_COLORS[self._color_combo.currentIndex()][1]
                self._current_stroke = (color_hex, [self._to_norm(pos)])
                self.update()
                event.accept()
                return
            # 准备拖拽平移；释放时若没拖动则视为点击翻页
            self._panning = True
            self._pan_moved = False
            self._pan_press_pos = pos
            self._pan_start = QPoint(self._pan)
            self._apply_cursor()
        elif event.button() == Qt.MouseButton.RightButton:
            # 画笔模式下右键也不翻页，避免误触（可用键盘/滚轮翻页）
            if not self._draw_on:
                self.prev_page()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        self._mouse_pos = pos
        if self._spotlight_on:
            self._spotlight_pos = pos
        if self._laser_on:
            self._laser_pos = pos
        if self._drawing and self._current_stroke is not None:
            self._current_stroke[1].append(self._to_norm(pos))
        if self._panning and self._pan_press_pos is not None \
                and self._pan_start is not None:
            delta = pos - self._pan_press_pos
            if not self._pan_moved and (
                abs(delta.x()) > PAN_THRESHOLD or abs(delta.y()) > PAN_THRESHOLD
            ):
                self._pan_moved = True
            if self._pan_moved:
                self._pan = self._pan_start + delta
                self._clamp_pan()
        self.update()
        self._set_bar_visible(True)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint()
        self._mouse_pos = pos
        if event.button() == Qt.MouseButton.LeftButton \
                and self._drawing and self._current_stroke is not None:
            color_hex, points = self._current_stroke
            if points:
                self._strokes.setdefault(self._current, []).append((color_hex, points))
            self._drawing = False
            self._current_stroke = None
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._panning:
            was_drag = self._pan_moved
            self._panning = False
            self._pan_moved = False
            self._pan_press_pos = None
            self._pan_start = None
            self._apply_cursor()
            # 按住没拖动 → 普通点击 → 下一页
            if not was_drag and not self._draw_on:
                self.next_page()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+滚轮：以鼠标位置为锚点缩放
            self._mouse_pos = event.position().toPoint()
            step = ZOOM_STEP if delta > 0 else -ZOOM_STEP
            self._zoom_slider.setValue(self._zoom_slider.value() + step)
        elif delta > 0:
            self.prev_page()
        elif delta < 0:
            self.next_page()
        super().wheelEvent(event)

    def contextMenuEvent(self, event):
        # 屏蔽右键菜单，把右键留给“上一页”
        event.accept()
