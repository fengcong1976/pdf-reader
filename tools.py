"""高级工具模块 - PDF 拆分、合并、加密、文本提取、转图片、瘦身"""

import os
import pymupdf
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QListWidget, QSpinBox, QComboBox, QProgressBar,
    QMessageBox, QGroupBox, QFormLayout, QCheckBox, QListWidgetItem,
    QInputDialog, QProgressDialog
)
from typing import List
from ocr import BatchTextWorker
import translator as ai_module
from translator import FullTranslateWorker, APISettingsDialog, is_configured as ai_is_configured
import pdf_slim as slim

# QThread 在窗口析构时不能提前被 Python 回收，用模块级集合托住正在跑的线程
_SLIM_THREADS = set()


class SlimWorker(QThread):
    """后台跑 PDF 瘦身，避免大文件卡住界面。"""

    progress = Signal(int, int, str)
    done = Signal(dict)

    def __init__(self, paths, level: str, target_kb: int, parent=None):
        super().__init__(parent)
        self._paths = list(paths)
        self._level = level
        self._target_kb = int(target_kb)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            report = slim.slim_batch(
                self._paths,
                level=self._level,
                target_kb=self._target_kb,
                progress=lambda i, n, name: self.progress.emit(i, n, name),
                cancelled=lambda: self._cancelled,
            )
        except Exception as e:
            report = {"cancelled": False, "items": [], "skipped": [],
                      "summary": {"total": 0, "processed": 0, "ok": 0,
                                  "skipped": 0, "failed": 1, "input_bytes": 0,
                                  "before_bytes": 0, "after_bytes": 0,
                                  "saved_bytes": 0, "ratio": 0.0,
                                  "target_reached": None},
                      "error": f"{type(e).__name__}: {e}"}
        self.done.emit(report)


class PDFToolsDialog(QDialog):
    """高级工具对话框"""

    def __init__(self, document, parent=None):
        super().__init__(parent)
        self._document = document
        self.setWindowTitle("PDF 工具箱")
        self.setMinimumWidth(500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 工具选择
        self._tool_combo = QComboBox()
        self._tool_combo.addItems([
            "── 选择工具 ──",
            "拆分 PDF（提取页面范围）",
            "合并 PDF（多个文件）",
            "加密 PDF（设置密码）",
            "提取文本（导出为 TXT）",
            "AI 全文翻译（导出 TXT）",
            "PDF 转图片",
            "PDF 瘦身（压缩体积）",
        ])
        self._tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        layout.addWidget(QLabel("请选择工具："))
        layout.addWidget(self._tool_combo)

        # ── 拆分工具面板 ──
        self._split_panel = QGroupBox("拆分 PDF")
        split_layout = QFormLayout(self._split_panel)
        self._split_start = QSpinBox()
        self._split_start.setMinimum(1)
        if self._document and self._document.is_loaded:
            self._split_start.setMaximum(self._document.page_count)
        self._split_end = QSpinBox()
        self._split_end.setMinimum(1)
        if self._document and self._document.is_loaded:
            self._split_end.setMaximum(self._document.page_count)
            self._split_end.setValue(self._document.page_count)
        split_layout.addRow("起始页：", self._split_start)
        split_layout.addRow("结束页：", self._split_end)
        self._split_btn = QPushButton("选择输出路径并拆分")
        self._split_btn.clicked.connect(self._do_split)
        split_layout.addRow(self._split_btn)
        layout.addWidget(self._split_panel)

        # ── 合并工具面板 ──
        self._merge_panel = QGroupBox("合并 PDF")
        merge_layout = QVBoxLayout(self._merge_panel)
        merge_btn_row = QHBoxLayout()
        self._merge_add_btn = QPushButton("添加文件")
        self._merge_add_btn.clicked.connect(self._merge_add_files)
        self._merge_del_btn = QPushButton("移除选中")
        self._merge_del_btn.clicked.connect(self._merge_del_file)
        merge_btn_row.addWidget(self._merge_add_btn)
        merge_btn_row.addWidget(self._merge_del_btn)
        merge_btn_row.addStretch()
        merge_layout.addLayout(merge_btn_row)
        self._merge_list = QListWidget()
        merge_layout.addWidget(self._merge_list)
        self._merge_btn = QPushButton("选择输出路径并合并")
        self._merge_btn.clicked.connect(self._do_merge)
        merge_layout.addWidget(self._merge_btn)
        layout.addWidget(self._merge_panel)

        # ── 加密工具面板 ──
        self._encrypt_panel = QGroupBox("加密 PDF")
        encrypt_layout = QFormLayout(self._encrypt_panel)
        self._encrypt_pwd = QLineEdit()
        self._encrypt_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._encrypt_pwd2 = QLineEdit()
        self._encrypt_pwd2.setEchoMode(QLineEdit.EchoMode.Password)
        self._encrypt_method = QComboBox()
        self._encrypt_method.addItems(["RC4-128", "AES-256"])
        encrypt_layout.addRow("密码：", self._encrypt_pwd)
        encrypt_layout.addRow("确认密码：", self._encrypt_pwd2)
        encrypt_layout.addRow("加密方式：", self._encrypt_method)
        self._encrypt_btn = QPushButton("选择输出路径并加密")
        self._encrypt_btn.clicked.connect(self._do_encrypt)
        encrypt_layout.addRow(self._encrypt_btn)
        layout.addWidget(self._encrypt_panel)

        # ── 文本提取面板 ──
        self._text_panel = QGroupBox("提取文本")
        text_layout = QFormLayout(self._text_panel)
        self._text_start = QSpinBox()
        self._text_start.setMinimum(1)
        if self._document and self._document.is_loaded:
            self._text_start.setMaximum(self._document.page_count)
        self._text_end = QSpinBox()
        self._text_end.setMinimum(1)
        if self._document and self._document.is_loaded:
            self._text_end.setMaximum(self._document.page_count)
            self._text_end.setValue(self._document.page_count)
        text_layout.addRow("起始页：", self._text_start)
        text_layout.addRow("结束页：", self._text_end)
        self._text_ocr = QCheckBox("扫描件自动 OCR（无文字层的页用 OCR 识别，速度较慢）")
        self._text_ocr.setChecked(True)
        text_layout.addRow(self._text_ocr)
        self._text_btn = QPushButton("选择输出路径并提取")
        self._text_btn.clicked.connect(self._do_extract_text)
        text_layout.addRow(self._text_btn)
        layout.addWidget(self._text_panel)

        # ── AI 全文翻译面板 ──
        self._aitrans_panel = QGroupBox("AI 全文翻译")
        aitrans_layout = QFormLayout(self._aitrans_panel)
        self._aitrans_start = QSpinBox()
        self._aitrans_start.setMinimum(1)
        if self._document and self._document.is_loaded:
            self._aitrans_start.setMaximum(self._document.page_count)
        self._aitrans_end = QSpinBox()
        self._aitrans_end.setMinimum(1)
        if self._document and self._document.is_loaded:
            self._aitrans_end.setMaximum(self._document.page_count)
            self._aitrans_end.setValue(self._document.page_count)
        aitrans_layout.addRow("起始页：", self._aitrans_start)
        aitrans_layout.addRow("结束页：", self._aitrans_end)
        self._aitrans_ocr = QCheckBox("扫描件自动 OCR（无文字层的页先识别再翻译）")
        self._aitrans_ocr.setChecked(True)
        aitrans_layout.addRow(self._aitrans_ocr)
        aitrans_hint = QLabel("使用大模型 API 逐页翻译（菜单：工具 → AI 大模型Key设置 可修改接口，方向跟随最近一次选择）")
        aitrans_hint.setWordWrap(True)
        aitrans_hint.setStyleSheet("color: #666;")
        aitrans_layout.addRow(aitrans_hint)
        self._aitrans_btn = QPushButton("选择输出路径并翻译")
        self._aitrans_btn.clicked.connect(self._do_ai_translate)
        aitrans_layout.addRow(self._aitrans_btn)
        layout.addWidget(self._aitrans_panel)

        # ── PDF 转图片面板 ──
        self._img_panel = QGroupBox("PDF 转图片")
        img_layout = QFormLayout(self._img_panel)
        size_row = QHBoxLayout()
        self._img_width = QSpinBox()
        self._img_width.setRange(100, 10000)
        self._img_width.setValue(1240)
        self._img_width.setSuffix(" px")
        self._img_height = QSpinBox()
        self._img_height.setRange(100, 10000)
        self._img_height.setValue(1754)
        self._img_height.setSuffix(" px")
        size_row.addWidget(self._img_width)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self._img_height)
        img_layout.addRow("图片尺寸（宽×高）：", size_row)
        self._img_start = QSpinBox()
        self._img_start.setMinimum(1)
        if self._document and self._document.is_loaded:
            self._img_start.setMaximum(self._document.page_count)
        img_layout.addRow("起始页：", self._img_start)
        self._img_pages = QSpinBox()
        self._img_pages.setMinimum(1)
        if self._document and self._document.is_loaded:
            self._img_pages.setMaximum(self._document.page_count)
            self._img_pages.setValue(self._document.page_count)
        img_layout.addRow("总页数：", self._img_pages)
        self._img_format = QComboBox()
        self._img_format.addItems(["PNG", "JPG"])
        img_layout.addRow("输出格式：", self._img_format)
        path_row = QHBoxLayout()
        self._img_path = QLineEdit()
        self._img_path.setPlaceholderText("选择保存文件夹")
        self._img_browse = QPushButton("浏览...")
        self._img_browse.clicked.connect(self._img_choose_dir)
        path_row.addWidget(self._img_path)
        path_row.addWidget(self._img_browse)
        img_layout.addRow("保存路径：", path_row)
        self._img_btn = QPushButton("开始转换")
        self._img_btn.clicked.connect(self._do_to_images)
        img_layout.addRow(self._img_btn)
        layout.addWidget(self._img_panel)

        # ── PDF 瘦身面板（2.1 新增）──
        self._slim_panel = QGroupBox("PDF 瘦身（2.1 新增）")
        slim_layout = QVBoxLayout(self._slim_panel)
        slim_layout.addWidget(QLabel("要瘦身的 PDF（可一次加多个；打开工具箱时已放入当前文档）："))
        self._slim_list = QListWidget()
        self._slim_list.setMaximumHeight(110)
        if self._document and self._document.is_loaded and self._document.file_path:
            self._slim_list.addItem(self._document.file_path)
        slim_layout.addWidget(self._slim_list)
        slim_btn_row = QHBoxLayout()
        self._slim_add_btn = QPushButton("添加 PDF")
        self._slim_del_btn = QPushButton("移除选中")
        self._slim_clear_btn = QPushButton("清空")
        self._slim_add_btn.clicked.connect(self._slim_add_files)
        self._slim_del_btn.clicked.connect(self._slim_del_files)
        self._slim_clear_btn.clicked.connect(self._slim_list.clear)
        slim_btn_row.addWidget(self._slim_add_btn)
        slim_btn_row.addWidget(self._slim_del_btn)
        slim_btn_row.addWidget(self._slim_clear_btn)
        slim_btn_row.addStretch()
        slim_layout.addLayout(slim_btn_row)

        slim_form = QFormLayout()
        self._slim_level = QComboBox()
        self._slim_level.addItem("标准（推荐）", "standard")
        self._slim_level.addItem("无损整理（画质不变）", "lossless")
        self._slim_level.addItem("轻度", "light")
        self._slim_level.addItem("强力（体积最小）", "strong")
        self._slim_level.addItem("自动（按目标体积挑档）", "auto")
        self._slim_level.currentIndexChanged.connect(self._on_slim_level_changed)
        slim_form.addRow("瘦身档位：", self._slim_level)
        target_row = QHBoxLayout()
        self._slim_target = QSpinBox()
        self._slim_target.setRange(50, 1000000)
        self._slim_target.setValue(2048)
        self._slim_target.setSuffix(" KB")
        self._slim_target.setEnabled(False)
        target_row.addWidget(self._slim_target)
        target_row.addWidget(QLabel("达不到目标会给出能做到的最小结果，并如实提示"))
        target_row.addStretch()
        slim_form.addRow("目标体积：", target_row)
        slim_layout.addLayout(slim_form)

        disclose = QLabel(slim.LOSSY_DISCLOSURE)
        disclose.setWordWrap(True)
        disclose.setStyleSheet("color: #a33;")
        slim_layout.addWidget(disclose)
        out_hint = QLabel(
            "结果：原文件旁的 out 文件夹，文件名「原名-瘦身.pdf」，压完自动打开；"
            "原文件不动，逐文件与汇总数据写入 report.json。")
        out_hint.setWordWrap(True)
        out_hint.setStyleSheet("color: #555;")
        slim_layout.addWidget(out_hint)
        self._slim_btn = QPushButton("开始瘦身")
        self._slim_btn.clicked.connect(self._do_slim)
        slim_layout.addWidget(self._slim_btn)
        layout.addWidget(self._slim_panel)

        # 进度条
        self._progress = QProgressBar()
        self._progress.hide()
        layout.addWidget(self._progress)

        # 初始隐藏所有面板
        self._split_panel.hide()
        self._merge_panel.hide()
        self._encrypt_panel.hide()
        self._text_panel.hide()
        self._aitrans_panel.hide()
        self._img_panel.hide()
        self._slim_panel.hide()

    def _on_tool_changed(self, index: int):
        self._split_panel.hide()
        self._merge_panel.hide()
        self._encrypt_panel.hide()
        self._text_panel.hide()
        self._aitrans_panel.hide()
        self._img_panel.hide()
        self._slim_panel.hide()
        if index == 1:
            self._split_panel.show()
        elif index == 2:
            self._merge_panel.show()
        elif index == 3:
            self._encrypt_panel.show()
        elif index == 4:
            self._text_panel.show()
        elif index == 5:
            self._aitrans_panel.show()
        elif index == 6:
            self._img_panel.show()
        elif index == 7:
            self._slim_panel.show()
        self.adjustSize()

    # ── 拆分 ──

    def _do_split(self):
        if not self._document or not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        start = self._split_start.value() - 1
        end = self._split_end.value() - 1
        if start > end:
            QMessageBox.warning(self, "提示", "起始页不能大于结束页")
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存拆分后的 PDF", "", "PDF 文件 (*.pdf)"
        )
        if not output_path:
            return
        self._progress.show()
        self._progress.setRange(0, 0)
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            if self._document.extract_page_range(start, end, output_path):
                self._progress.hide()
                QMessageBox.information(self, "成功", f"已保存到：\n{output_path}")
            else:
                self._progress.hide()
                QMessageBox.critical(self, "错误", "拆分失败，请检查参数")
        except Exception as e:
            self._progress.hide()
            QMessageBox.critical(self, "错误", f"拆分出错：\n{e}")

    # ── 合并 ──

    def _merge_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要合并的 PDF", "", "PDF 文件 (*.pdf)"
        )
        for fp in files:
            self._merge_list.addItem(fp)

    def _merge_del_file(self):
        for item in self._merge_list.selectedItems():
            self._merge_list.takeItem(self._merge_list.row(item))

    def _do_merge(self):
        if self._merge_list.count() < 2:
            QMessageBox.warning(self, "提示", "至少需要 2 个文件才能合并")
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存合并后的 PDF", "", "PDF 文件 (*.pdf)"
        )
        if not output_path:
            return
        files = [
            self._merge_list.item(i).text()
            for i in range(self._merge_list.count())
        ]
        self._progress.show()
        self._progress.setRange(0, 0)
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            new_doc = pymupdf.open()
            for fp in files:
                src = pymupdf.open(fp)
                new_doc.insert_pdf(src)
                src.close()
            new_doc.save(output_path)
            new_doc.close()
            self._progress.hide()
            QMessageBox.information(self, "成功", f"已合并保存到：\n{output_path}")
        except Exception as e:
            self._progress.hide()
            QMessageBox.critical(self, "错误", f"合并出错：\n{e}")

    # ── 加密 ──

    def _do_encrypt(self):
        if not self._document or not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        pwd = self._encrypt_pwd.text()
        pwd2 = self._encrypt_pwd2.text()
        if not pwd:
            QMessageBox.warning(self, "提示", "请输入密码")
            return
        if pwd != pwd2:
            QMessageBox.warning(self, "提示", "两次输入的密码不一致")
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存加密后的 PDF", "", "PDF 文件 (*.pdf)"
        )
        if not output_path:
            return
        self._progress.show()
        self._progress.setRange(0, 0)
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            raw_doc = self._document.get_raw_document()
            perm = (pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY | pymupdf.PDF_PERM_ANNOTATE)
            if self._encrypt_method.currentText() == "AES-256":
                crypt = pymupdf.PDF_ENCRYPT_AES_256
            else:
                crypt = pymupdf.PDF_ENCRYPT_RC4_128
            raw_doc.save(
                output_path,
                encryption=crypt,
                user_pw=pwd,
                owner_pw=pwd,
                permissions=perm,
            )
            self._progress.hide()
            QMessageBox.information(self, "成功", f"已加密保存到：\n{output_path}")
        except Exception as e:
            self._progress.hide()
            QMessageBox.critical(self, "错误", f"加密出错：\n{e}")

    # ── 文本提取 ──

    def _do_extract_text(self):
        if not self._document or not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        start = self._text_start.value() - 1
        end = self._text_end.value() - 1
        if start > end:
            QMessageBox.warning(self, "提示", "起始页不能大于结束页")
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存文本文件", "", "文本文件 (*.txt)"
        )
        if not output_path:
            return
        use_ocr = self._text_ocr.isChecked()
        total = end - start + 1

        # 后台线程逐页提取：有文字层的页直接提取，扫描页按需 OCR
        self._text_parts = [None] * total
        self._text_ocr_count = 0
        self._text_worker = BatchTextWorker(self._document, start, end, use_ocr)
        worker = self._text_worker

        self._text_progress = QProgressDialog(
            f"正在提取文本（0/{total} 页）……", "取消", 0, total, self
        )
        self._text_progress.setWindowTitle("提取文本")
        self._text_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._text_progress.setMinimumDuration(0)
        self._text_progress.setValue(0)

        def on_page_done(page_num: int, text: str, used_ocr: bool):
            if self._text_progress.wasCanceled():
                return
            self._text_parts[page_num - start] = text
            if used_ocr:
                self._text_ocr_count += 1
            done = page_num - start + 1
            self._text_progress.setLabelText(
                f"正在提取文本（{done}/{total} 页）……"
                + ("（OCR 识别中，速度较慢）" if used_ocr else "")
            )
            self._text_progress.setValue(done)

        def on_all_done():
            self._text_progress.close()
            full_text = "\n".join(p if p is not None else "" for p in self._text_parts)
            if not full_text.strip() and not use_ocr:
                QMessageBox.warning(
                    self, "提示",
                    "未提取到任何文字。\n该文件可能是扫描件/图片型 PDF，"
                    "请勾选「扫描件自动 OCR」后重试。",
                )
                return
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(full_text)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败：\n{e}")
                return
            msg = f"已提取到：\n{output_path}"
            if self._text_ocr_count:
                msg += (
                    f"\n\n其中 {self._text_ocr_count} 页为扫描页，"
                    "已通过 OCR 识别（结果可能有误差，建议核对）。"
                )
            QMessageBox.information(self, "成功", msg)

        def on_failed(message: str):
            self._text_progress.close()
            QMessageBox.critical(self, "错误", message)

        self._text_progress.canceled.connect(worker.cancel)
        worker.page_done.connect(on_page_done)
        worker.all_done.connect(on_all_done)
        worker.failed.connect(on_failed)
        worker.start()

    # ── AI 全文翻译 ──

    def _do_ai_translate(self):
        if not self._document or not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        # 未配置 API 时先弹出设置对话框
        if not ai_is_configured():
            QMessageBox.information(
                self, "AI 大模型Key设置",
                "首次使用 AI 翻译，请先填写大模型 API 信息。\n\n"
                "支持 DeepSeek / 通义千问 / Kimi / OpenAI 等\n"
                "OpenAI 兼容接口，只需接口地址 + API Key + 模型名。",
            )
            if APISettingsDialog(self).exec() != APISettingsDialog.DialogCode.Accepted:
                return
            if not ai_is_configured():
                return
        start = self._aitrans_start.value() - 1
        end = self._aitrans_end.value() - 1
        if start > end:
            QMessageBox.warning(self, "提示", "起始页不能大于结束页")
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存翻译结果", "", "文本文件 (*.txt)"
        )
        if not output_path:
            return
        use_ocr = self._aitrans_ocr.isChecked()
        total = end - start + 1
        cfg = ai_module.load_config()

        # 后台线程逐页：提取文字（扫描页可选 OCR）→ 调大模型翻译
        self._aitrans_parts = [None] * total
        self._aitrans_worker = FullTranslateWorker(
            self._document, start, end, cfg, use_ocr
        )
        worker = self._aitrans_worker

        self._aitrans_progress = QProgressDialog(
            f"AI 全文翻译（0/{total} 页）……", "取消", 0, total, self
        )
        self._aitrans_progress.setWindowTitle("AI 全文翻译")
        self._aitrans_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._aitrans_progress.setMinimumDuration(0)
        self._aitrans_progress.setValue(0)

        def on_page_done(page_num: int, text: str):
            if self._aitrans_progress.wasCanceled():
                return
            self._aitrans_parts[page_num - start] = text
            done = page_num - start + 1
            self._aitrans_progress.setLabelText(
                f"AI 全文翻译（{done}/{total} 页）……\n"
                f"翻译方向：{cfg.get('direction', '自动识别')}"
            )
            self._aitrans_progress.setValue(done)

        def on_all_done():
            self._aitrans_progress.close()
            full_text = "\n".join(
                p if p is not None else "" for p in self._aitrans_parts
            )
            if not full_text.strip():
                QMessageBox.warning(self, "提示", "翻译结果为空，请检查文档内容")
                return
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(full_text)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败：\n{e}")
                return
            QMessageBox.information(
                self, "成功",
                f"已翻译 {total} 页并保存到：\n{output_path}\n\n"
                f"翻译方向：{cfg.get('direction', '自动识别')}",
            )

        def on_failed(message: str):
            self._aitrans_progress.close()
            QMessageBox.critical(self, "AI 翻译失败", message)

        self._aitrans_progress.canceled.connect(worker.cancel)
        worker.page_done.connect(on_page_done)
        worker.all_done.connect(on_all_done)
        worker.failed.connect(on_failed)
        worker.start()

    # ── PDF 转图片 ──

    def _img_choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存文件夹")
        if d:
            self._img_path.setText(d)

    def _do_to_images(self):
        if not self._document or not self._document.is_loaded:
            QMessageBox.warning(self, "提示", "请先打开 PDF 文件")
            return
        out_dir = self._img_path.text().strip()
        if not out_dir or not os.path.isdir(out_dir):
            QMessageBox.warning(self, "提示", "请选择有效的保存文件夹")
            return
        start = self._img_start.value() - 1
        pages = self._img_pages.value()
        end = start + pages - 1
        if self._document and self._document.is_loaded:
            end = min(end, self._document.page_count - 1)
        if start > end:
            QMessageBox.warning(self, "提示", "起始页超出文档范围")
            return
        target_w = self._img_width.value()
        target_h = self._img_height.value()
        fmt = self._img_format.currentText().lower()
        ext = "png" if fmt == "png" else "jpg"

        total = end - start + 1
        self._progress.show()
        self._progress.setRange(0, total)
        self._progress.setValue(0)
        try:
            from PySide6.QtWidgets import QApplication
            raw = self._document.get_raw_document()
            base_name = os.path.splitext(os.path.basename(self._document.file_path or "pdf"))[0]
            for i in range(start, end + 1):
                page = raw[i]
                page_w = page.rect.width
                page_h = page.rect.height
                # 按目标像素尺寸计算缩放比，保持页面宽高比
                scale = min(target_w / page_w, target_h / page_h)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
                out_file = os.path.join(out_dir, f"{base_name}_第{i+1:03d}页.{ext}")
                pix.save(out_file)
                self._progress.setValue(i - start + 1)
                QApplication.processEvents()
            self._progress.hide()
            QMessageBox.information(self, "成功", f"已转换 {total} 页到：\n{out_dir}")
        except Exception as e:
            self._progress.hide()
            QMessageBox.critical(self, "错误", f"转换出错：\n{e}")

    # ── PDF 瘦身（2.1）──

    def _on_slim_level_changed(self, index: int):
        self._slim_target.setEnabled(self._slim_level.itemData(index) == "auto")

    def _slim_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要瘦身的 PDF", "", "PDF 文件 (*.pdf)"
        )
        existing = {
            os.path.normcase(os.path.abspath(self._slim_list.item(i).text()))
            for i in range(self._slim_list.count())
        }
        for fp in files:
            key = os.path.normcase(os.path.abspath(fp))
            if key not in existing:
                self._slim_list.addItem(fp)
                existing.add(key)

    def _slim_del_files(self):
        for item in self._slim_list.selectedItems():
            self._slim_list.takeItem(self._slim_list.row(item))

    def _do_slim(self):
        paths = [self._slim_list.item(i).text()
                 for i in range(self._slim_list.count())]
        if not paths:
            QMessageBox.warning(self, "提示", "请先添加要瘦身的 PDF 文件")
            return
        key = self._slim_level.currentData()
        target_kb = self._slim_target.value() if key == "auto" else 0
        level = slim.DEFAULT_LEVEL if key == "auto" else key

        worker = SlimWorker(paths, level, target_kb)
        self._slim_worker = worker
        _SLIM_THREADS.add(worker)
        worker.finished.connect(lambda w=worker: _SLIM_THREADS.discard(w))
        # 这里不要 deleteLater：closeEvent 仍会查询这个 worker 是否在跑，
        # 提前删掉 C++ 对象会让 Python 侧包装失效并抛 RuntimeError。
        # 线程结束后引用自然归零，QThread 在已停止状态下析构是安全的。

        self._slim_progress = QProgressDialog(
            f"正在瘦身（0/{len(paths)}）……", "取消", 0, len(paths), self
        )
        self._slim_progress.setWindowTitle("PDF 瘦身")
        self._slim_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._slim_progress.setMinimumDuration(0)
        self._slim_progress.setValue(0)

        self._slim_progress.canceled.connect(worker.cancel)
        worker.progress.connect(self._on_slim_progress)
        worker.done.connect(self._on_slim_done)
        self._slim_btn.setEnabled(False)
        self._slim_progress.show()
        worker.start()

    def _on_slim_progress(self, i: int, n: int, name: str):
        dlg = getattr(self, "_slim_progress", None)
        if dlg is not None:
            dlg.setLabelText(f"正在瘦身（{i}/{n}）：{name}")
            dlg.setValue(i)

    def _on_slim_done(self, report: dict):
        dlg = getattr(self, "_slim_progress", None)
        if dlg is not None:
            dlg.close()
            self._slim_progress = None
        self._slim_btn.setEnabled(True)
        s = report.get("summary", {})
        if report.get("cancelled"):
            QMessageBox.information(self, "已取消", "已取消，本轮未产出任何文件。")
            return
        if report.get("error"):
            QMessageBox.critical(self, "错误", f"瘦身失败：{report['error']}")
            return

        lines = [
            f"输入 {s.get('total', 0)} 个，成功 {s.get('ok', 0)}，"
            f"跳过 {s.get('skipped', 0)}，失败 {s.get('failed', 0)}",
            f"{slim.format_size(s.get('before_bytes', 0))} → "
            f"{slim.format_size(s.get('after_bytes', 0))}，共省 "
            f"{slim.format_size(s.get('saved_bytes', 0))}"
            f"（{s.get('ratio', 0) * 100:.1f}%）",
        ]
        if s.get("target_reached") is False:
            lines.append("已用到最强档仍没达到目标体积，输出的是能做到的最小结果。")
        no_gain = sum(1 for r in report.get("items", [])
                      if r.get("status") == "ok-no-gain")
        if no_gain:
            lines.append(f"{no_gain} 个文件压完没变小，已原样输出（画质 100% 不变）。")
        for r in report.get("items", []):
            if r.get("status") in ("failed", "skipped"):
                lines.append(f"· {os.path.basename(r['source'])}：{r.get('message', '')}")
        lines.append("结果在原文件旁的 out 文件夹，逐文件数据见 report.json。")

        outs = [r["output"] for r in report.get("items", []) if r.get("output")]
        if outs and getattr(self, "_slim_auto_open", True):
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(outs[0])))
            lines.append("已自动打开输出文件夹。")
        QMessageBox.information(self, "瘦身完成", "\n".join(lines))

    def closeEvent(self, event):
        # 关窗口时若瘦身线程还在跑，先取消并等它收尾，别让 QThread 被提前析构
        worker = getattr(self, "_slim_worker", None)
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(10000)
        super().closeEvent(event)
