"""搜索功能模块 - 全文搜索栏"""

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel, QCheckBox
)


class SearchBar(QWidget):
    """搜索栏组件"""

    search_requested = Signal(str, bool)  # (查询文本, 是否区分大小写)
    next_requested = Signal()
    prev_requested = Signal()
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_query = ""
        self._had_results = False
        self._build_ui()
        self.hide()

    def _build_ui(self):
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入搜索文本...")
        self._search_input.setFixedHeight(26)
        self._search_input.installEventFilter(self)
        self._search_input.returnPressed.connect(self._on_search)
        layout.addWidget(self._search_input, 1)

        self._case_check = QCheckBox("区分大小写")
        self._case_check.setFixedHeight(26)
        layout.addWidget(self._case_check)

        self._search_btn = QPushButton("搜索")
        self._search_btn.setFixedHeight(26)
        self._search_btn.clicked.connect(self._on_search)
        layout.addWidget(self._search_btn)

        self._prev_btn = QPushButton("上一个")
        self._prev_btn.setFixedHeight(26)
        self._prev_btn.clicked.connect(self.prev_requested.emit)
        self._prev_btn.setEnabled(False)
        layout.addWidget(self._prev_btn)

        self._next_btn = QPushButton("下一个")
        self._next_btn.setFixedHeight(26)
        self._next_btn.clicked.connect(self.next_requested.emit)
        self._next_btn.setEnabled(False)
        layout.addWidget(self._next_btn)

        self._result_label = QLabel("")
        self._result_label.setFixedHeight(26)
        self._result_label.setStyleSheet("color: #666; min-width: 80px;")
        layout.addWidget(self._result_label)

        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; "
            "border: none; color: #888; }"
            "QPushButton:hover { color: #c00; }"
        )
        self._close_btn.clicked.connect(self.close_search)
        layout.addWidget(self._close_btn)

    def _on_search(self):
        query = self._search_input.text().strip()
        if query:
            self._last_query = query
            self.search_requested.emit(query, self._case_check.isChecked())

    def eventFilter(self, obj, event):
        """输入框内回车导航：Enter=下一个，Shift+Enter=上一个；查询变化时 Enter 重新搜索"""
        if obj is self._search_input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                query = self._search_input.text().strip()
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    if self._had_results:
                        self.prev_requested.emit()
                    return True
                # 查询未变且已有结果 → 跳到下一个；否则触发搜索
                if self._had_results and query and query == self._last_query:
                    self.next_requested.emit()
                    return True
                return False  # 交给 returnPressed 触发搜索
        return super().eventFilter(obj, event)

    def set_result_info(self, current: int, total: int):
        """设置搜索结果信息"""
        self._had_results = total > 0
        if total > 0:
            self._result_label.setText(f"{current + 1} / {total}")
            self._prev_btn.setEnabled(True)
            self._next_btn.setEnabled(True)
        else:
            self._result_label.setText("无结果")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)

    def show_search(self):
        """显示搜索栏并获取焦点"""
        self.show()
        self._search_input.setFocus()

    def close_search(self):
        """关闭搜索栏"""
        self.hide()
        self.closed.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_search()
        super().keyPressEvent(event)
