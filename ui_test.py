"""PDF 阅读器 2.1 —— 界面自检（真实建窗口、切页签、点按钮、跑后台线程）。

跑法：venv\\Scripts\\python.exe ui_test.py
用 offscreen 平台，不打扰桌面、不弹真实模态框；不做截图，所以字体渲染不影响断言。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pymupdf
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox

import pdf_slim as slim
import tools as tools_module
from tools import PDFToolsDialog, SlimWorker

app = QApplication([])
ROOT = Path(__file__).resolve().parent
_passed = 0
_failed = 0
_fail_lines: list[str] = []
_box_calls: list[tuple] = []


def check(name: str, cond: bool, detail: str = ""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [OK] {name}")
    else:
        _failed += 1
        msg = f"  [FAIL] {name} {detail}"
        _fail_lines.append(msg)
        print(msg)


def section(title: str):
    print(f"\n==== {title} ====")


# 把模态提示换成记录，避免自检卡在弹窗上；失败时由定时器兜底关窗
def fake_box(title, *a, **k):
    _box_calls.append((str(title),) + tuple(str(x) for x in a))
    return QMessageBox.StandardButton.Ok


try:
    QMessageBox.information = staticmethod(fake_box)
    QMessageBox.warning = staticmethod(fake_box)
    QMessageBox.critical = staticmethod(fake_box)
    QMessageBox.question = staticmethod(fake_box)
except (TypeError, AttributeError):
    def auto_close():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMessageBox) and w.isVisible():
                w.accept()
        QTimer.singleShot(50, auto_close)
    QTimer.singleShot(50, auto_close)


class DummyDoc:
    is_loaded = True
    page_count = 8
    file_path = r"D:\文档\合同.pdf"


def make_pdf(path: Path, pages=2):
    noise = path.with_suffix(".png")
    Image.frombytes("RGB", (700, 1000), os.urandom(700 * 1000 * 3)).save(noise)
    doc = pymupdf.open()
    for i in range(pages):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((60, 80), f"UI TEST page {i + 1} ABC-888", fontsize=14)
        pg.insert_image(pymupdf.Rect(40, 120, 555, 780), filename=str(noise))
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()
    return path


def main() -> int:
    section("工具箱结构与瘦身页签")
    d = PDFToolsDialog(DummyDoc())
    combo = d._tool_combo
    items = [combo.itemText(i) for i in range(combo.count())]
    check("工具项共 8 个", len(items) == 8, str(items))
    check("最后一项是 PDF 瘦身", items[-1] == "PDF 瘦身（压缩体积）")
    check("初始所有工具面板隐藏",
          all(p.isHidden() for p in (d._split_panel, d._merge_panel,
                                     d._encrypt_panel, d._text_panel,
                                     d._aitrans_panel, d._img_panel,
                                     d._slim_panel)))
    combo.setCurrentIndex(7)
    check("切到瘦身只显示瘦身面板",
          not d._slim_panel.isHidden() and all(
              p.isHidden() for p in (d._split_panel, d._merge_panel,
                                     d._encrypt_panel, d._text_panel,
                                     d._aitrans_panel, d._img_panel)))
    combo.setCurrentIndex(6)
    check("切回转图片会隐藏瘦身面板", d._slim_panel.isHidden()
          and not d._img_panel.isHidden())
    combo.setCurrentIndex(0)
    check("切回选择工具全部隐藏", d._slim_panel.isHidden()
          and d._img_panel.isHidden())
    combo.setCurrentIndex(7)

    section("文件列表")
    check("打开时预填当前文档", d._slim_list.count() == 1
          and "合同.pdf" in d._slim_list.item(0).text())
    d2 = PDFToolsDialog(None)
    check("未打开文档时列表为空", d2._slim_list.count() == 0)

    orig_open = QFileDialog.getOpenFileNames
    dup_a = r"D:\文档\a.pdf"
    dup_a_upper = r"D:\文档\A.PDF"
    new_b = r"D:\文档\b.pdf"
    QFileDialog.getOpenFileNames = staticmethod(
        lambda *a, **k: ([dup_a, dup_a, dup_a_upper, new_b], ""))
    try:
        d._slim_add_files()
    finally:
        QFileDialog.getOpenFileNames = orig_open
    texts = [d._slim_list.item(i).text() for i in range(d._slim_list.count())]
    check("添加后列表为 3 项（含预填）", len(texts) == 3, str(texts))
    check("重复路径与大小写差异被去重",
          sum(1 for t in texts if t.lower().endswith("a.pdf")) == 1, str(texts))
    check("新文件确实加进来了", any(t == new_b for t in texts))
    d._slim_list.setCurrentRow(1)
    d._slim_del_files()
    check("移除选中生效", d._slim_list.count() == 2)
    d._slim_list.clear()
    check("清空生效", d._slim_list.count() == 0)

    section("档位 / 目标体积 / 披露文案")
    levels = [(d._slim_level.itemText(i), d._slim_level.itemData(i))
              for i in range(d._slim_level.count())]
    check("档位共 5 项", len(levels) == 5, str(levels))
    check("默认档是 standard", d._slim_level.currentData() == "standard")
    check("四档 key 与引擎一致",
          {k for _, k in levels} == {"standard", "lossless", "light",
                                     "strong", "auto"})
    check("默认目标体积禁用", not d._slim_target.isEnabled())
    d._slim_level.setCurrentIndex(4)
    check("自动档启用目标体积", d._slim_target.isEnabled())
    d._slim_level.setCurrentIndex(0)
    check("切回标准档重新禁用", not d._slim_target.isEnabled())
    check("目标体积默认 2048 KB", d._slim_target.value() == 2048)
    labels = [w.text() for w in d._slim_panel.findChildren(QLabel)]
    check("面板有有损披露", any("画质会下降" in t and "不可" in t for t in labels))
    check("披露写清透明通道风险", any("透明" in t for t in labels))
    check("披露写明原文件不改写", any("原文件" in t for t in labels))
    check("面板说明输出目录与报告",
          any("out" in t and "report.json" in t for t in labels))
    check("面板标注 2.1 新增", "2.1 新增" in d._slim_panel.title())

    section("空列表与按钮状态")
    _box_calls.clear()
    d._do_slim()
    check("空列表会提示先添加文件", bool(_box_calls))
    check("空列表不会启动线程", not hasattr(d, "_slim_worker"))

    section("真实跑一次瘦身（建窗口 → 加文件 → 点按钮 → 等线程）")
    with tempfile.TemporaryDirectory(prefix="pdfslim_ui_") as td:
        root = Path(td)
        src = make_pdf(root / "合同扫描件.pdf")
        before = src.stat().st_size
        before_info = slim.inspect_pdf(src)
        d._slim_list.clear()
        d._slim_list.addItem(str(src))
        d._slim_auto_open = False      # 自检不真的打开资源管理器
        _box_calls.clear()
        d._do_slim()
        w = d._slim_worker
        check("创建了后台瘦身线程", isinstance(w, SlimWorker))
        check("进度对话框已建立", getattr(d, "_slim_progress", None) is not None)
        check("运行中按钮被禁用", not d._slim_btn.isEnabled())
        if w.isRunning():
            loop = QEventLoop()
            w.done.connect(loop.quit)
            QTimer.singleShot(30000, loop.quit)
            loop.exec()
        for _ in range(30):
            app.processEvents()
        check("线程已结束", not w.isRunning())
        check("按钮恢复可用", d._slim_btn.isEnabled())
        check("进度对话框已关闭", getattr(d, "_slim_progress", None) is None)
        check("弹出了完成提示", bool(_box_calls), str(_box_calls))
        if _box_calls:
            body = "\n".join(_box_calls[-1])
            check("完成提示里写了前后体积", "→" in body and "MB" in body)
            check("完成提示写了 report.json", "report.json" in body)
            check("完成提示没有谎称自动打开", "已自动打开" not in body)
        out_dir = root / "out"
        outs = list(out_dir.glob("*-瘦身*.pdf"))
        check("out 目录产出了结果 PDF", len(outs) == 1, str(outs))
        if outs:
            got = slim.inspect_pdf(outs[0])
            check("结果页数不变", got["pages"] == before_info["pages"])
            check("结果文字层不变",
                  got["text_sha256"] == before_info["text_sha256"])
            check("结果体积不放大", outs[0].stat().st_size <= before)
            check("结果确实压小了", outs[0].stat().st_size < before)
        check("原文件未被改写", src.stat().st_size == before)
        rp = out_dir / "report.json"
        check("汇总 report.json 落盘", rp.is_file())
        if rp.is_file():
            data = json.loads(rp.read_text(encoding="utf-8"))
            check("报告版本 2.1", data["version"] == "2.1")
            check("报告 0 次联网", data["network_attempts"] == 0)
            check("报告逐文件数正确", len(data["items"]) == 1)
            check("报告汇总体积真实",
                  data["summary"]["after_bytes"] ==
                  (outs[0].stat().st_size if outs else -1))
        check("线程引用已从托底集合移除",
              w not in tools_module._SLIM_THREADS)

        section("结果弹窗各分支")
        _box_calls.clear()
        d._on_slim_done({"cancelled": True, "items": [],
                         "summary": {"total": 1, "ok": 0, "skipped": 0,
                                     "failed": 0, "before_bytes": 0,
                                     "after_bytes": 0, "saved_bytes": 0,
                                     "ratio": 0}})
        check("取消时提示已取消",
              bool(_box_calls) and "已取消" in "\n".join(_box_calls[-1]))
        _box_calls.clear()
        d._on_slim_done({"cancelled": False, "items": [],
                         "summary": {"total": 1, "ok": 1, "skipped": 0,
                                     "failed": 0, "before_bytes": 1000,
                                     "after_bytes": 900, "saved_bytes": 100,
                                     "ratio": 0.1, "target_reached": False}})
        check("未达目标体积会如实提示",
              bool(_box_calls) and "没达到目标体积" in "\n".join(_box_calls[-1]))
        _box_calls.clear()
        d._on_slim_done({
            "cancelled": False,
            "items": [{"source": "x.pdf", "output": "",
                       "status": "ok-no-gain", "message": ""}],
            "summary": {"total": 1, "ok": 1, "skipped": 0, "failed": 0,
                        "before_bytes": 1000, "after_bytes": 1000,
                        "saved_bytes": 0, "ratio": 0}})
        check("无收益文件会提示原样输出",
              bool(_box_calls) and "原样输出" in "\n".join(_box_calls[-1]))
        _box_calls.clear()
        d._on_slim_done({"cancelled": False, "items": [], "summary": {},
                         "error": "boom"})
        check("异常时给出错误提示",
              bool(_box_calls) and "boom" in "\n".join(_box_calls[-1]))

    section("线程与版本")
    check("SlimWorker 有 progress 信号", hasattr(SlimWorker, "progress"))
    check("SlimWorker 有 done 信号", hasattr(SlimWorker, "done"))
    check("SlimWorker 可取消", hasattr(SlimWorker, "cancel"))
    check("引擎版本 2.1", slim.APP_VERSION == "2.1")
    check("工具箱源码标注 2.1 新增",
          "2.1 新增" in (ROOT / "tools.py").read_text(encoding="utf-8"))
    check("主程序源码版本 2.1",
          "版本：</b>2.1" in (ROOT / "main.py").read_text(encoding="utf-8"))
    section("关窗口")
    d.close()
    d2.close()
    check("关闭工具箱不抛异常", True)

    print(f"\n合计 {_passed}/{_passed + _failed} 项通过")
    if _failed:
        print("\n失败清单：")
        for line in _fail_lines:
            print(line)
    print("结论：" + ("全部通过" if _failed == 0 else f"{_failed} 项未通过"))
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    rc = main()
    # Qt 对象销毁顺序不可控，显式清场后硬退出，避免解释器收尾崩溃
    try:
        app = None
        globals().pop("d", None)
    except Exception:
        pass
    sys.stdout.flush() if sys.stdout is not None else None
    os._exit(rc)
