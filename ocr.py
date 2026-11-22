"""文字识别（OCR）模块 - 单次框选区域识别，基于 RapidOCR(ONNX) 纯 CPU 推理

使用流程：点击「文字识别」→ 在页面上拖出一个矩形框 →
高 DPI 裁剪该区域后台识别 → 弹窗只显示本次识别结果，可复制或保存为 TXT。
再次识别时点击工具栏按钮重新框选即可。
"""

import pymupdf
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFileDialog, QMessageBox, QApplication
)
from typing import List, Tuple

# OCR 引擎单例（首次加载较慢，全局复用）
_ocr_engine = None


def get_ocr_engine():
    """获取全局唯一的 RapidOCR 引擎（懒加载）"""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def is_engine_loaded() -> bool:
    """OCR 模型是否已加载（用于判断是否需要提示首次加载较慢）"""
    return _ocr_engine is not None


def _extract_texts(output) -> List[str]:
    """兼容 RapidOCR 1.x / 2.x 两种返回格式，提取识别出的文本行"""
    if output is None:
        return []
    # RapidOCR 1.x：(result, elapse)，result 为 [[box, text, score], ...] 或 None
    if isinstance(output, tuple):
        result = output[0]
        if not result:
            return []
        return [str(item[1]) for item in result if len(item) >= 2]
    # RapidOCR 2.x：RapidOCROutput 对象，含 txts / boxes / scores
    txts = getattr(output, "txts", None)
    if txts is not None:
        return [str(t) for t in txts]
    # 其他可迭代形式
    try:
        return [str(item[1]) for item in output if len(item) >= 2]
    except Exception:
        return []


def ocr_region_text(document, page_num: int,
                    render_rect: Tuple[float, float, float, float],
                    engine=None) -> str:
    """高清渲染指定区域并 OCR 识别，返回识别文本（无文字时为空串）

    render_rect 为 zoom=1 渲染坐标（应用了 PDF 自带旋转后的显示空间）。
    供框选识别、划词解释等场景复用。
    """
    raw = document.get_raw_document()
    if raw is None:
        return ""
    if engine is None:
        engine = get_ocr_engine()
    page = raw[page_num]
    # 显示空间选框（加边距并限制在页面显示范围内）
    # 说明：page.rect 与 get_pixmap(clip=) 均使用应用 PDF 自带旋转后的
    # 显示坐标空间，因此 clip 直接使用选框即可，无需再做逆旋转
    pw, ph = document.get_page_size(page_num)
    x0, y0, x1, y1 = render_rect
    clip = pymupdf.Rect(
        max(0.0, x0 - 4.0),
        max(0.0, y0 - 4.0),
        min(pw, x1 + 4.0),
        min(ph, y1 + 4.0),
    )
    if clip.width <= 1 or clip.height <= 1:
        return ""
    # 按区域宽度自适应高清倍率，提高小字识别率
    zoom = max(2.0, min(6.0, 1600.0 / max(clip.width, 1.0)))
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False
    )
    texts = _extract_texts(engine(pix.tobytes("png")))
    return "\n".join(texts).strip()


class OCRRegionWorker(QThread):
    """后台区域 OCR 识别线程

    render_rect 为 zoom=1 渲染坐标（应用了 PDF 自带旋转后的显示空间）。
    """

    succeeded = Signal(int, str)   # 页码（0-based）, 识别文本
    failed = Signal(int, str)      # 页码（0-based）, 错误信息

    # 选框外扩边距（渲染坐标/pt），避免裁掉贴边笔画
    PADDING = 4.0
    # 裁剪图目标宽度（像素），据此自适应渲染倍率
    TARGET_WIDTH = 1600.0
    MIN_ZOOM = 2.0
    MAX_ZOOM = 6.0

    def __init__(self, document, page_num: int,
                 render_rect: Tuple[float, float, float, float], parent=None):
        super().__init__(parent)
        self._document = document
        self._page_num = page_num
        self._render_rect = render_rect

    def run(self):
        try:
            engine = get_ocr_engine()
        except Exception as e:
            self.failed.emit(
                self._page_num,
                f"OCR 模型加载失败：{e}\n\n"
                "请确认已安装 rapidocr-onnxruntime：\n"
                "pip install rapidocr-onnxruntime"
            )
            return

        try:
            text = ocr_region_text(
                self._document, self._page_num, self._render_rect, engine
            )
            if not text:
                text = "（该区域未识别到文字）"
            self.succeeded.emit(self._page_num, text)
        except Exception as e:
            self.failed.emit(self._page_num, f"识别失败：{e}")


def ocr_page_text(document, page_num: int, engine=None) -> str:
    """渲染整页并 OCR 识别，返回按识别顺序拼接的文本（无文字时为空串）

    供批量文本提取、整页翻译等需要全文的场景复用。
    """
    raw = document.get_raw_document()
    if raw is None:
        return ""
    if engine is None:
        engine = get_ocr_engine()
    page = raw[page_num]
    # 按页宽自适应高清倍率，提高小字识别率
    pw, _ = document.get_page_size(page_num)
    zoom = max(2.0, min(4.0, 1600.0 / max(pw, 1.0)))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    texts = _extract_texts(engine(pix.tobytes("png")))
    return "\n".join(texts).strip()


class BatchTextWorker(QThread):
    """后台批量提取整本文档文本的线程

    有文字层的页直接提取（快且准）；无文字层的页（扫描件/图片型 PDF）
    高清渲染整页后交给 RapidOCR 识别，OCR 引擎惰性加载（遇到第一个
    扫描页才加载，纯文字层文档不受首次加载耗时影响）。
    """

    page_done = Signal(int, str, bool)  # 页码(0-based), 该页文本, 是否经过 OCR
    all_done = Signal()                 # 全部页处理完成
    failed = Signal(str)                # 致命错误信息

    # 整页渲染目标宽度（像素），与区域识别一致以兼顾速度与识别率
    TARGET_WIDTH = 1600.0
    MIN_ZOOM = 2.0
    MAX_ZOOM = 4.0

    def __init__(self, document, start: int, end: int, ocr_enabled: bool, parent=None):
        super().__init__(parent)
        self._document = document
        self._start = start
        self._end = end
        self._ocr_enabled = ocr_enabled
        self._cancelled = False

    def cancel(self):
        """请求停止（当前页处理完后退出）"""
        self._cancelled = True

    def run(self):
        raw = self._document.get_raw_document()
        if raw is None:
            self.failed.emit("文档未打开，无法提取文本")
            return
        engine = None
        for i in range(self._start, self._end + 1):
            if self._cancelled:
                return
            try:
                page = raw[i]
                text = page.get_text().strip()
                if text:
                    self.page_done.emit(i, text, False)
                    continue
                if not self._ocr_enabled:
                    self.page_done.emit(i, "", False)
                    continue
                if engine is None:
                    try:
                        engine = get_ocr_engine()
                    except Exception as e:
                        self.failed.emit(
                            f"OCR 模型加载失败：{e}\n\n"
                            "请确认已安装 rapidocr-onnxruntime：\n"
                            "pip install rapidocr-onnxruntime"
                        )
                        return
                text = ocr_page_text(self._document, i, engine)
                self.page_done.emit(i, text, True)
            except Exception as e:
                # 单页失败不中断整体，写入占位说明
                self.page_done.emit(i, f"（第 {i + 1} 页提取失败：{e}）", False)
        self.all_done.emit()


class OCRResultDialog(QDialog):
    """单次框选识别结果对话框：只显示最近一次框选的识别结果"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("文字识别结果")
        self.setMinimumSize(520, 380)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._result_edit = QPlainTextEdit()
        # 识别中只读；识别出结果后允许用户直接编辑修正
        self._result_edit.setReadOnly(True)
        self._result_edit.setPlaceholderText("正在识别……")
        layout.addWidget(self._result_edit, 1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #1a5fb4; font-weight: bold;")
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._copy_btn = QPushButton("复制文本")
        self._copy_btn.setMinimumHeight(32)
        self._copy_btn.clicked.connect(self.copy_text)
        self._save_btn = QPushButton("保存为 TXT…")
        self._save_btn.setMinimumHeight(32)
        self._save_btn.clicked.connect(self.save_txt)
        self._close_btn = QPushButton("关闭")
        self._close_btn.setMinimumHeight(32)
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._copy_btn)
        btn_row.addWidget(self._save_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

    # ── 结果展示（每次框选均为全新内容，不累积）─────────────────

    def show_busy(self, page_num: int, first_load: bool = False):
        """开始识别：清空旧结果，只显示本次进度"""
        self._result_edit.clear()
        self._result_edit.setReadOnly(True)
        self._status_label.setStyleSheet("color: #1a5fb4; font-weight: bold;")
        self._status_label.setText(
            f"正在识别第 {page_num + 1} 页框选区域……"
            + ("（首次加载模型约需十几秒，请稍候）" if first_load else "")
        )
        self._copy_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        self.show()
        self.raise_()
        self.activateWindow()

    def set_result(self, page_num: int, text: str):
        """显示本次识别结果（替换旧内容），并允许用户编辑修正"""
        self._result_edit.setPlainText(text)
        self._result_edit.setReadOnly(False)
        self._result_edit.setFocus()
        self._status_label.setStyleSheet("color: #1a5fb4; font-weight: bold;")
        self._status_label.setText(f"第 {page_num + 1} 页区域识别完成（可直接编辑修正）")
        self._copy_btn.setEnabled(True)
        self._save_btn.setEnabled(True)
        self.show()
        self.raise_()
        self.activateWindow()

    def show_failed(self, message: str):
        self._result_edit.setPlainText("")
        self._status_label.setStyleSheet("color: #b00; font-weight: bold;")
        self._status_label.setText("识别失败")
        self._copy_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        QMessageBox.critical(self, "文字识别失败", message)

    def copy_text(self):
        text = self._result_edit.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._status_label.setText("已复制到剪贴板")

    def save_txt(self):
        text = self._result_edit.toPlainText()
        if not text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存识别结果", "OCR识别结果.txt", "文本文件 (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self._status_label.setText(f"已保存：{path}")
            QMessageBox.information(self, "成功", f"识别结果已保存到：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")
