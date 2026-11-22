"""AI 翻译模块 - 基于大模型 API（OpenAI 兼容接口）的整页/全文翻译

配置（API 地址、密钥、模型名、目标语言）保存在 QSettings 中。
调用翻译前先用 is_configured() 检查；未配置时应先弹出 APISettingsDialog
让用户完成设置。

DeepSeek / 通义千问 / Kimi / OpenAI 等均提供 OpenAI 兼容的
chat/completions 接口，填写对应「接口地址 + 密钥 + 模型名」即可使用。
"""

import json
import re
import urllib.error
import urllib.request
from html import escape as html_escape

from PySide6.QtCore import Qt, QThread, Signal, QSettings
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QMessageBox, QApplication, QCheckBox,
    QPlainTextEdit, QStackedWidget, QTextBrowser, QSpinBox
)

from ocr import get_ocr_engine, ocr_page_text

_SETTINGS_PREFIX = "ai_translate"

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# 翻译方向
DIRECTION_AUTO = "自动识别"          # 中文→英文，其他→中文
DIRECTION_ZH2EN = "中文 → English"
DIRECTION_EN2ZH = "English → 中文"
DIRECTIONS = [DIRECTION_AUTO, DIRECTION_ZH2EN, DIRECTION_EN2ZH]

SUMMARY_TARGET_ZH2EN = "English"     # 中→英模式下，总结用英文
SUMMARY_TARGET_DEFAULT = "简体中文"

BASE_URL_PRESETS = [
    "https://api.deepseek.com/v1",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://api.moonshot.cn/v1",
    "https://api.openai.com/v1",
]
MODEL_PRESETS = [
    "deepseek-chat",
    "deepseek-reasoner",
    "qwen-plus",
    "qwen-turbo",
    "moonshot-v1-8k",
    "gpt-4o-mini",
]
TARGET_LANGS_REMOVED = None  # 旧字段占位（已改为翻译方向），防止误用

TRANSLATE_PROMPTS = {
    DIRECTION_AUTO: (
        "你是专业的 PDF 文档翻译引擎。规则：\n"
        "1. 先检测用户提供文本的主要语言：若主要为中文，将全文翻译成英文；"
        "若主要为英文或其他外语，将全文翻译成简体中文。\n"
        "2. 只输出译文正文，不要任何解释、前缀、后缀，不要重复原文。\n"
        "3. 保持原文的段落划分与换行结构。\n"
        "4. 代码、公式、数字、URL、邮箱保持原样。\n"
        "5. 译文自然通顺，符合目标语言的表达习惯。"
    ),
    DIRECTION_ZH2EN: (
        "你是专业的 PDF 文档翻译引擎，把用户提供的中文 PDF 页面文本翻译成英文。规则：\n"
        "1. 只输出英文译文正文，不要任何解释、前缀、后缀，不要重复原文。\n"
        "2. 保持原文的段落划分与换行结构。\n"
        "3. 代码、公式、数字、URL、邮箱保持原样。\n"
        "4. 译文自然地道，符合英语表达习惯。"
    ),
    DIRECTION_EN2ZH: (
        "你是专业的 PDF 文档翻译引擎，把用户提供的 PDF 页面文本翻译成简体中文。规则：\n"
        "1. 只输出简体中文译文正文，不要任何解释、前缀、后缀，不要重复原文。\n"
        "2. 保持原文的段落划分与换行结构。\n"
        "3. 代码、公式、数字、URL、邮箱保持原样。\n"
        "4. 译文自然通顺，符合中文表达习惯。"
    ),
}

SUMMARY_PROMPT = (
    "你是专业的文档分析助手，对用户提供的 PDF 页面内容做总结。规则：\n"
    "1. 用简洁的要点总结本页核心内容，按重要性排列。\n"
    "2. 保留关键数据、结论、专有名词。\n"
    "3. 只输出总结内容，不要任何前后缀。\n"
    "4. 使用语言：{target}。"
)

SUMMARY_RANGE_PROMPT = (
    "你是专业的文档分析助手，对用户提供的 PDF 多页内容做整体总结，"
    "每页文本前有【第 N 页】标记。规则：\n"
    "1. 按主题或逻辑脉络组织要点，做整体性总结，不要逐页流水账。\n"
    "2. 保留关键数据、结论、专有名词，可注明重要内容出自第几页。\n"
    "3. 只输出总结内容，不要任何前后缀。\n"
    "4. 使用语言：{target}。"
)

EXPLAIN_PROMPT = (
    "你是专业的阅读助手，请解释用户提供的 PDF 选中文本。规则：\n"
    "1. 若文本为外文，先给出翻译，再解释含义；若为中文则直接解释。\n"
    "2. 若是术语、概念，说明定义与背景。\n"
    "3. 若是句子、段落，解释核心意思；涉及公式、代码时逐项说明。\n"
    "4. 解释使用简体中文，简洁准确、条理清晰，可用要点分条。\n"
    "5. 只输出解释内容，不要任何前后缀。"
)

# 编号分段对照翻译（原文/译文逐段对照显示用）
_NUMBERED_RULES = (
    "用户提供的文本已按 [1]、[2]…… 编号分段。规则：\n"
    "1. 逐段翻译，每段译文前保留相同编号（如 [1]），编号后直接写译文。\n"
    "2. 编号必须与原文一一对应，不得合并、拆分或遗漏任何段落；"
    "无需翻译的段落（纯数字、URL、人名等）原样保留。\n"
    "3. 只输出编号译文，不要任何解释、前缀、后缀，不要重复原文内容。\n"
    "4. 代码、公式、数字、URL、邮箱保持原样。\n"
    "5. 译文自然通顺，符合目标语言的表达习惯。"
)

TRANSLATE_NUMBERED_PROMPTS = {
    DIRECTION_AUTO: (
        "你是专业的 PDF 文档翻译引擎。先检测文本主要语言："
        "主要为中文则译成英文，主要为英文或其他外语则译成简体中文。\n"
        + _NUMBERED_RULES
    ),
    DIRECTION_ZH2EN: (
        "你是专业的 PDF 文档翻译引擎，把用户提供的中文文本翻译成英文。\n"
        + _NUMBERED_RULES
    ),
    DIRECTION_EN2ZH: (
        "你是专业的 PDF 文档翻译引擎，把用户提供的文本翻译成简体中文。\n"
        + _NUMBERED_RULES
    ),
}

# 超过该段落数时放弃对照模式（输出过长易截断），回退整页翻译
_MAX_BILINGUAL_SEGS = 40


def split_bilingual_segments(text: str) -> list:
    """把页面文本切成对照段落：优先按空行分段，几乎没有空行时按行分段"""
    paras, cur = [], []
    for ln in text.splitlines():
        if ln.strip():
            cur.append(ln.rstrip())
        elif cur:
            paras.append("\n".join(cur).strip())
            cur = []
    if cur:
        paras.append("\n".join(cur).strip())
    if len(paras) < 2:
        paras = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return paras


def parse_numbered_translation(result: str, count: int):
    """解析编号译文为长度 count 的列表；编号缺失/异常时返回 None"""
    pat = re.compile(r"^\s*\[(\d+)\]\s*")
    segs, cur = {}, None
    for ln in result.splitlines():
        m = pat.match(ln)
        if m:
            cur = int(m.group(1))
            segs.setdefault(cur, [])
            rest = pat.sub("", ln, count=1).strip()
            if rest:
                segs[cur].append(rest)
        elif cur is not None and ln.strip():
            segs[cur].append(ln.strip())
    if not segs:
        return None
    out = []
    for i in range(1, count + 1):
        if i not in segs or not "\n".join(segs[i]).strip():
            return None
        out.append("\n".join(segs[i]).strip())
    return out


# ── 配置读写 ─────────────────────────────────────────────────────

def load_config() -> dict:
    s = QSettings("PDFReader", "PDF阅读器")
    direction = str(s.value(f"{_SETTINGS_PREFIX}/direction", DIRECTION_AUTO) or "")
    if direction not in DIRECTIONS:
        direction = DIRECTION_AUTO
    return {
        "base_url": str(s.value(f"{_SETTINGS_PREFIX}/base_url", DEFAULT_BASE_URL) or "").strip(),
        "api_key": str(s.value(f"{_SETTINGS_PREFIX}/api_key", "") or "").strip(),
        "model": str(s.value(f"{_SETTINGS_PREFIX}/model", DEFAULT_MODEL) or "").strip(),
        "direction": direction,
    }


def save_config(cfg: dict):
    s = QSettings("PDFReader", "PDF阅读器")
    for k, v in cfg.items():
        s.setValue(f"{_SETTINGS_PREFIX}/{k}", v)


def save_direction(direction: str):
    """单独保存翻译方向（工具栏下拉即时切换用）"""
    if direction in DIRECTIONS:
        s = QSettings("PDFReader", "PDF阅读器")
        s.setValue(f"{_SETTINGS_PREFIX}/direction", direction)


def is_configured(cfg: dict = None) -> bool:
    """是否已配置 API 密钥"""
    cfg = cfg or load_config()
    return bool(cfg.get("api_key"))


# ── 接口调用 ─────────────────────────────────────────────────────

def translate_once(text: str, cfg: dict, timeout: int = 180,
                   system_prompt: str = None) -> str:
    """调用 OpenAI 兼容 chat/completions 接口处理一段文本，返回结果。

    system_prompt 为空时使用翻译提示词；出错的抛 RuntimeError，
    错误信息已转为可读中文。
    """
    if system_prompt is None:
        direction = cfg.get("direction") or DIRECTION_AUTO
        system_prompt = TRANSLATE_PROMPTS.get(
            direction, TRANSLATE_PROMPTS[DIRECTION_AUTO]
        )
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        raise RuntimeError(f"接口返回错误（HTTP {e.code}）：{detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"无法连接翻译接口，请检查网络或接口地址：{e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"请求失败：{e}") from e

    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except Exception:
        raise RuntimeError(
            f"接口返回格式异常：{json.dumps(data, ensure_ascii=False)[:300]}"
        ) from None


# ── 设置对话框 ───────────────────────────────────────────────────

class APISettingsDialog(QDialog):
    """AI 翻译接口设置对话框：接口地址 / API Key / 模型 / 目标语言"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 大模型Key设置")
        self.setMinimumWidth(480)
        cfg = load_config()

        form = QFormLayout()
        self._base_url = QComboBox()
        self._base_url.setEditable(True)
        self._base_url.addItems(BASE_URL_PRESETS)
        self._base_url.setCurrentText(cfg["base_url"] or DEFAULT_BASE_URL)
        form.addRow("接口地址：", self._base_url)

        self._api_key = QLineEdit(cfg["api_key"])
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("sk-...")
        key_row = QHBoxLayout()
        key_row.addWidget(self._api_key, 1)
        self._key_toggle = QCheckBox("显示")
        self._key_toggle.toggled.connect(self._toggle_key_visible)
        key_row.addWidget(self._key_toggle)
        form.addRow("API Key：", key_row)

        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.addItems(MODEL_PRESETS)
        self._model.setCurrentText(cfg["model"] or DEFAULT_MODEL)
        form.addRow("模型名：", self._model)

        self._direction = QComboBox()
        self._direction.addItems(DIRECTIONS)
        self._direction.setCurrentText(cfg["direction"])
        form.addRow("翻译方向：", self._direction)

        btn_row = QHBoxLayout()
        self._test_btn = QPushButton("测试连接")
        self._test_btn.clicked.connect(self._on_test)
        self._save_btn = QPushButton("保存")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._test_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(cancel_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(btn_row)

    def _toggle_key_visible(self, show: bool):
        self._api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )

    def _collect_config(self) -> dict:
        return {
            "base_url": self._base_url.currentText().strip(),
            "api_key": self._api_key.text().strip(),
            "model": self._model.currentText().strip(),
            "direction": self._direction.currentText().strip() or DIRECTION_AUTO,
        }

    def _on_test(self):
        cfg = self._collect_config()
        if not cfg["base_url"] or not cfg["api_key"] or not cfg["model"]:
            QMessageBox.warning(self, "提示", "请先填写接口地址、API Key 和模型名")
            return
        self._test_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            reply = translate_once("Hello, world.", cfg, timeout=30)
            QMessageBox.information(self, "连接成功", f"模型回复：{reply[:100]}")
        except Exception as e:
            QMessageBox.critical(self, "连接失败", str(e))
        finally:
            QApplication.restoreOverrideCursor()
            self._test_btn.setEnabled(True)

    def _on_save(self):
        cfg = self._collect_config()
        if not cfg["base_url"]:
            QMessageBox.warning(self, "提示", "接口地址不能为空")
            return
        save_config(cfg)
        self.accept()


# ── 结果对话框 ───────────────────────────────────────────────────

class TranslateResultDialog(QDialog):
    """AI 处理结果对话框：显示翻译/总结/解释结果，可复制或保存"""

    TASK_TITLES = {"translate": "AI 翻译", "summary": "AI 总结", "explain": "AI 解释"}
    TASK_VERBS = {"translate": "翻译", "summary": "总结", "explain": "解释"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task = "translate"
        self.setWindowTitle(self.TASK_TITLES[self._task])
        self.setMinimumSize(560, 420)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._result_edit = QPlainTextEdit()
        self._result_edit.setReadOnly(True)
        self._result_edit.setPlaceholderText("正在处理……")
        self._bilingual_view = QTextBrowser()  # 原文/译文逐段对照视图
        self._stack = QStackedWidget()
        self._stack.addWidget(self._result_edit)      # index 0：纯文本
        self._stack.addWidget(self._bilingual_view)   # index 1：对照
        layout.addWidget(self._stack, 1)
        self._pairs = []

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #1a5fb4; font-weight: bold;")
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._copy_btn = QPushButton("复制结果")
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

    def _apply_task(self, task: str):
        if task in self.TASK_TITLES:
            self._task = task
            self.setWindowTitle(self.TASK_TITLES[self._task])

    def show_busy(self, page_num: int, direction: str, task: str = "translate",
                  page_label: str = None):
        self._apply_task(task)
        self._stack.setCurrentIndex(0)
        self._result_edit.clear()
        self._result_edit.setReadOnly(True)
        self._bilingual_view.clear()
        self._pairs = []
        self._status_label.setStyleSheet("color: #1a5fb4; font-weight: bold;")
        verb = self.TASK_VERBS[self._task]
        info = f"（{direction}）" if self._task == "translate" and direction else ""
        pos_text = page_label or f"第 {page_num + 1} 页"
        self._status_label.setText(f"正在{verb}{pos_text}{info}……")
        self._copy_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        self.show()
        self.raise_()
        self.activateWindow()

    def set_result(self, page_num: int, text: str, task: str = None,
                   page_label: str = None):
        if task:
            self._apply_task(task)
        self._stack.setCurrentIndex(0)
        self._result_edit.setPlainText(text)
        self._result_edit.setReadOnly(False)
        self._result_edit.setFocus()
        pos_text = page_label or f"第 {page_num + 1} 页"
        self._status_label.setText(
            f"{pos_text}{self.TASK_VERBS[self._task]}完成（可直接编辑修正）"
        )
        self._copy_btn.setEnabled(True)
        self._save_btn.setEnabled(True)
        self.show()
        self.raise_()
        self.activateWindow()

    def set_bilingual_result(self, page_num: int, pairs):
        """原文/译文逐段对照显示：原文灰字在上，译文黑字在下"""
        self._pairs = [tuple(p) for p in pairs]
        parts = []
        for src, dst in self._pairs:
            src_h = html_escape(src).replace("\n", "<br>")
            dst_h = html_escape(dst).replace("\n", "<br>")
            parts.append(
                f"<p style='margin:0 0 2px 0; color:#8a8a8a; font-size:12px;'>{src_h}</p>"
                f"<p style='margin:0 0 14px 0;'>{dst_h}</p>"
            )
        self._bilingual_view.setHtml("".join(parts))
        self._stack.setCurrentIndex(1)
        self._status_label.setText(
            f"第 {page_num + 1} 页翻译完成（原文 / 译文对照，灰色为原文）"
        )
        self._copy_btn.setEnabled(True)
        self._save_btn.setEnabled(True)
        self.show()
        self.raise_()
        self.activateWindow()

    def show_failed(self, message: str):
        self._status_label.setStyleSheet("color: #b00; font-weight: bold;")
        self._status_label.setText(f"{self.TASK_TITLES[self._task]}失败")
        self._result_edit.setPlainText("")
        self._copy_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        QMessageBox.critical(self, f"AI {self.TASK_VERBS[self._task]}失败", message)

    def _current_text(self) -> str:
        """当前显示内容的纯文本（对照视图导出为原文/译文格式）"""
        if self._stack.currentIndex() == 1:
            lines = []
            for src, dst in self._pairs:
                lines.append(f"【原文】{src}")
                lines.append(f"【译文】{dst}")
                lines.append("")
            return "\n".join(lines).rstrip()
        return self._result_edit.toPlainText()

    def copy_text(self):
        text = self._current_text()
        if text:
            QApplication.clipboard().setText(text)
            self._status_label.setText("已复制到剪贴板")

    def save_txt(self):
        text = self._current_text()
        if not text:
            return
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "保存结果", f"{self.TASK_TITLES[self._task]}_当前页.txt",
            "文本文件 (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self._status_label.setText(f"已保存：{path}")
            QMessageBox.information(self, "成功", f"译文已保存到：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{e}")


# ── 方向选择对话框 ───────────────────────────────────────────────

class DirectionPickDialog(QDialog):
    """翻译方向选择对话框：点击方向按钮立即确认"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择翻译方向")
        self.setMinimumWidth(300)
        self.selected_direction = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        tip = QLabel("请选择翻译方向：")
        layout.addWidget(tip)
        for d in DIRECTIONS:
            btn = QPushButton(d)
            btn.setMinimumHeight(38)
            btn.clicked.connect(lambda _=False, dir_=d: self._pick(dir_))
            layout.addWidget(btn)

    def _pick(self, direction: str):
        self.selected_direction = direction
        self.accept()


# ── 总结范围选择对话框 ───────────────────────────────────────────

class SummaryRangeDialog(QDialog):
    """AI 总结范围选择：总结当前页，或自选页码范围（最多 MAX_RANGE_PAGES 页）"""

    MAX_RANGE_PAGES = 30

    def __init__(self, current_page: int, page_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 总结")
        self.setMinimumWidth(340)
        self.mode = "page"          # "page"=当前页 / "range"=范围
        self.start_page = current_page   # 0-based
        self.end_page = current_page

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        tip = QLabel(
            f"一页内容可能不完整，可选择页码范围一起总结"
            f"（最多 {self.MAX_RANGE_PAGES} 页）："
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        row = QHBoxLayout()
        row.addWidget(QLabel("从第"))
        self._start_spin = QSpinBox()
        self._start_spin.setRange(1, page_count)
        self._start_spin.setValue(current_page + 1)
        row.addWidget(self._start_spin)
        row.addWidget(QLabel("页  至"))
        self._end_spin = QSpinBox()
        self._end_spin.setRange(1, page_count)
        self._end_spin.setValue(current_page + 1)
        row.addWidget(self._end_spin)
        row.addWidget(QLabel("页"))
        row.addStretch()
        layout.addLayout(row)

        cur_btn = QPushButton(f"只总结当前页（第 {current_page + 1} 页）")
        cur_btn.setMinimumHeight(34)
        cur_btn.clicked.connect(self._pick_current)
        layout.addWidget(cur_btn)

        range_btn = QPushButton("总结所选范围")
        range_btn.setMinimumHeight(34)
        range_btn.clicked.connect(self._pick_range)
        layout.addWidget(range_btn)

    def _pick_current(self):
        self.mode = "page"
        self.accept()

    def _pick_range(self):
        s = self._start_spin.value() - 1
        e = self._end_spin.value() - 1
        if e < s:
            s, e = e, s
        if e - s + 1 > self.MAX_RANGE_PAGES:
            QMessageBox.warning(
                self, "提示", f"一次最多总结 {self.MAX_RANGE_PAGES} 页，请缩小范围"
            )
            return
        self.mode = "range"
        self.start_page, self.end_page = s, e
        self.accept()


# ── 后台翻译线程 ─────────────────────────────────────────────────

class PageTranslateWorker(QThread):
    """当前页 AI 处理线程：提取文字（可选区域/无文字层 OCR）→ 调大模型

    task="translate" 翻译；task="summary" 总结；task="explain" 解释选中文本。
    clip_rect 不为空时只处理该区域（划词场景），区域无文字层时自动 OCR。
    """

    succeeded = Signal(str)   # 处理结果（纯文本）
    bilingual = Signal(list)  # 对照结果：[(原文, 译文), ...]
    failed = Signal(str)      # 错误信息

    def __init__(self, document, page_num: int, cfg: dict, parent=None,
                 task: str = "translate", clip_rect=None):
        super().__init__(parent)
        self._document = document
        self._page_num = page_num
        self._cfg = cfg
        self._task = task
        self._clip_rect = clip_rect

    def run(self):
        try:
            if self._clip_rect is not None:
                text = self._document.get_text_in_rect(
                    self._page_num, self._clip_rect
                ).strip()
                if not text:
                    # 选中区域无文字层（扫描/图片）：区域 OCR 后再处理
                    from ocr import ocr_region_text
                    text = ocr_region_text(
                        self._document, self._page_num, self._clip_rect
                    )
            else:
                text = self._document.get_page_text(self._page_num).strip()
                if not text:
                    # 扫描页：整页 OCR 后再处理
                    text = ocr_page_text(self._document, self._page_num)
            if not text:
                self.failed.emit("未识别到任何文字（可能为空白区域）")
                return
            if self._task == "summary":
                # 中→英模式下总结也用英文，其余用简体中文
                direction = self._cfg.get("direction") or DIRECTION_AUTO
                summary_target = (
                    SUMMARY_TARGET_ZH2EN if direction == DIRECTION_ZH2EN
                    else SUMMARY_TARGET_DEFAULT
                )
                prompt = SUMMARY_PROMPT.format(target=summary_target)
                result = translate_once(text, self._cfg, system_prompt=prompt)
            elif self._task == "explain":
                result = translate_once(
                    text, self._cfg, system_prompt=EXPLAIN_PROMPT
                )
            else:
                pairs = self._translate_bilingual(text)
                if pairs:
                    self.bilingual.emit(pairs)
                    return
                result = translate_once(text, self._cfg)
            if not result:
                self.failed.emit("接口返回了空结果")
                return
            self.succeeded.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

    def _translate_bilingual(self, text: str):
        """编号分段对照翻译；返回 [(原文, 译文), ...] 或 None（回退整页翻译）

        段落过多时不走对照（输出过长易截断）；接口异常直接向上抛出。
        """
        segs = split_bilingual_segments(text)
        if len(segs) < 2 or len(segs) > _MAX_BILINGUAL_SEGS:
            return None
        direction = self._cfg.get("direction") or DIRECTION_AUTO
        prompt = TRANSLATE_NUMBERED_PROMPTS.get(
            direction, TRANSLATE_NUMBERED_PROMPTS[DIRECTION_AUTO]
        )
        numbered = "\n".join(f"[{i + 1}] {s}" for i, s in enumerate(segs))
        result = translate_once(numbered, self._cfg, system_prompt=prompt)
        pairs = parse_numbered_translation(result, len(segs))
        if not pairs:
            return None
        return list(zip(segs, pairs))


class PageRangeSummaryWorker(QThread):
    """页码范围 AI 总结线程：逐页提取文字（扫描页自动 OCR）→ 拼接 → 调大模型"""

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, document, page_start: int, page_end: int, cfg: dict,
                 parent=None):
        super().__init__(parent)
        self._document = document
        self._page_start = page_start
        self._page_end = page_end
        self._cfg = cfg

    def run(self):
        try:
            engine = None
            parts = []
            for p in range(self._page_start, self._page_end + 1):
                text = self._document.get_page_text(p).strip()
                if not text:
                    # 扫描页：整页 OCR 后再纳入总结
                    if engine is None:
                        engine = get_ocr_engine()
                    text = ocr_page_text(self._document, p, engine=engine)
                if text:
                    parts.append(f"【第 {p + 1} 页】\n{text}")
            if not parts:
                self.failed.emit("所选范围未识别到任何文字")
                return
            direction = self._cfg.get("direction") or DIRECTION_AUTO
            summary_target = (
                SUMMARY_TARGET_ZH2EN if direction == DIRECTION_ZH2EN
                else SUMMARY_TARGET_DEFAULT
            )
            prompt = SUMMARY_RANGE_PROMPT.format(target=summary_target)
            result = translate_once(
                "\n\n".join(parts), self._cfg, system_prompt=prompt
            )
            if not result:
                self.failed.emit("接口返回了空结果")
                return
            self.succeeded.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class FullTranslateWorker(QThread):
    """全文翻译线程：逐页提取文字（可选 OCR）→ 逐页调用大模型翻译"""

    page_done = Signal(int, str)  # 页码(0-based), 该页译文（空白页为空串）
    all_done = Signal()
    failed = Signal(str)

    def __init__(self, document, start: int, end: int, cfg: dict,
                 ocr_enabled: bool, parent=None):
        super().__init__(parent)
        self._document = document
        self._start = start
        self._end = end
        self._cfg = cfg
        self._ocr_enabled = ocr_enabled
        self._cancelled = False

    def cancel(self):
        """请求停止（当前页处理完后退出）"""
        self._cancelled = True

    def run(self):
        engine = None  # OCR 引擎惰性加载：纯文字层文档不加载模型
        for i in range(self._start, self._end + 1):
            if self._cancelled:
                return
            try:
                text = self._document.get_page_text(i).strip()
                if not text and self._ocr_enabled:
                    if engine is None:
                        try:
                            engine = get_ocr_engine()
                        except Exception as e:
                            self.failed.emit(f"OCR 模型加载失败：{e}")
                            return
                    text = ocr_page_text(self._document, i, engine)
                text = text.strip()
                if not text:
                    self.page_done.emit(i, "")
                    continue
                translated = translate_once(text, self._cfg)
                self.page_done.emit(i, translated)
            except Exception as e:
                self.failed.emit(f"第 {i + 1} 页处理失败：{e}")
                return
        self.all_done.emit()
