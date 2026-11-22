"""PDF 阅读器 2.1 —— 核心引擎自检（纯 Python，不建窗口）。

跑法：venv\\Scripts\\python.exe verify.py
覆盖：四档瘦身、文字层/页数不变量、不放大回退、目标体积阶梯、批量与报告、
      取消回滚、加密/损坏跳过、0 联网、版本一致性。
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import pymupdf
from PIL import Image

import pdf_slim as slim

ROOT = Path(__file__).resolve().parent
_passed = 0
_failed = 0
_fail_lines: list[str] = []


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


def noise_png(path: Path, w=900, h=1200, alpha=False):
    mode = "RGBA" if alpha else "RGB"
    data = os.urandom(w * h * (4 if alpha else 3))
    Image.frombytes(mode, (w, h), data).save(path)


def build_pdf(path: Path, pages=3, with_text=True, img: Path | None = None,
              password: str | None = None):
    doc = pymupdf.open()
    for i in range(pages):
        pg = doc.new_page(width=595, height=842)
        if with_text:
            pg.insert_text((60, 80),
                           f"Contract page {i + 1} ABC-123456 number {i:03d}",
                           fontsize=14)
        if img is not None:
            pg.insert_image(pymupdf.Rect(40, 120, 555, 780), filename=str(img))
    kw = {}
    if password:
        kw = dict(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                  user_pw=password, owner_pw=password)
    doc.save(str(path), garbage=4, deflate=True, **kw)
    doc.close()


def section(title: str):
    print(f"\n==== {title} ====")


def main() -> int:
    section("环境与常量")
    check("PyMuPDF 可用", hasattr(pymupdf, "open"))
    check("版本号 2.1", slim.APP_VERSION == "2.1")
    check("四档齐全", len(slim.LEVELS) == 4)
    keys = [lv.key for lv in slim.LEVELS]
    check("档位 key 不重复", len(set(keys)) == 4, str(keys))
    check("有默认档", slim.DEFAULT_LEVEL in slim.LEVEL_BY_KEY)
    lossy = [lv for lv in slim.LEVELS if lv.quality is not None]
    qs = [lv.quality for lv in lossy]
    dpis = [lv.dpi_target for lv in lossy]
    check("质量与 DPI 逐级下降", qs == sorted(qs, reverse=True)
          and dpis == sorted(dpis, reverse=True), f"q={qs} dpi={dpis}")
    check("无损档不重编码", slim.LEVEL_BY_KEY["lossless"].quality is None
          and slim.LEVEL_BY_KEY["lossless"].dpi_target is None)
    check("有损披露写实（画质/不可还原/原文件）",
          all(k in slim.LOSSY_DISCLOSURE
              for k in ("画质", "不可", "原文件", "透明")))
    check("联网次数为 0", slim.NETWORK_ATTEMPTS == 0)

    section("版本一致性（源码 / 安装包脚本）")
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    check("关于窗口版本 2.1", "<b>版本：</b>2.1" in main_py)
    check("使用说明版本 2.1", "版本 2.1" in main_py)
    check("关于里写了 2.1 新增", "2.1 新增" in main_py)
    check("使用说明里有损披露", "瘦身有损披露" in main_py)
    check("安装包版本 2.1", '#define MyAppVersion "2.1"' in iss)
    check("安装包输出名跟随版本", "PDF阅读器_Setup_{#MyAppVersion}" in iss)
    check("工具箱有瘦身入口", "PDF 瘦身" in (ROOT / "tools.py").read_text(encoding="utf-8"))

    section("0 联网（静态 + 动态）")
    src = (ROOT / "pdf_slim.py").read_text(encoding="utf-8")
    cli_src = (ROOT / "cli_slim.py").read_text(encoding="utf-8")
    banned = ("import requests", "urllib.request", "http.client",
              "socket.create_connection", "urlopen", "ftplib")
    check("引擎源码无网络调用", not any(k in src for k in banned))
    check("CLI 源码无网络调用", not any(k in cli_src for k in banned))

    with tempfile.TemporaryDirectory(prefix="pdfslim_verify_") as td:
        root = Path(td)
        noise = root / "noise.png"
        alpha = root / "alpha.png"
        noise_png(noise)
        noise_png(alpha, w=500, h=700, alpha=True)
        scan = root / "scan.pdf"
        text = root / "text.pdf"
        mixed = root / "mixed.pdf"
        alpha_pdf = root / "alpha.pdf"
        enc = root / "encrypted.pdf"
        broken = root / "broken.pdf"
        build_pdf(scan, pages=3, with_text=False, img=noise)
        build_pdf(text, pages=3, with_text=True, img=None)
        build_pdf(mixed, pages=3, with_text=True, img=noise)
        build_pdf(alpha_pdf, pages=2, with_text=True, img=alpha)
        build_pdf(enc, pages=2, with_text=True, img=noise, password="secret")
        broken.write_bytes(os.urandom(1024))
        not_pdf = root / "readme.txt"
        not_pdf.write_text("hello", encoding="utf-8")

        section("0 联网（运行时真的掐断连接）")
        orig_cc = socket.create_connection
        orig_connect = socket.socket.connect
        patched_connect = False
        def blocked_cc(*a, **k):
            raise AssertionError("瘦身过程发生联网")
        def blocked_connect(self, addr):
            raise AssertionError("瘦身过程发生联网")
        socket.create_connection = blocked_cc
        try:
            socket.socket.connect = blocked_connect
            patched_connect = True
        except (TypeError, AttributeError):
            pass
        try:
            r_net = slim.slim_one(scan, level="standard")
            net_ok = r_net["status"].startswith("ok")
        except AssertionError:
            net_ok = False
            r_net = {}
        finally:
            socket.create_connection = orig_cc
            if patched_connect:
                socket.socket.connect = orig_connect
        check("掐断网络连接仍能完成瘦身", net_ok,
              str(r_net.get("message", "")))
        if net_ok:
            Path(r_net["output"]).unlink(missing_ok=True)
            Path(r_net["output"]).with_suffix(".report.json").unlink(missing_ok=True)

        section("inspect_pdf 只读探查")
        i_scan = slim.inspect_pdf(scan)
        i_text = slim.inspect_pdf(text)
        i_enc = slim.inspect_pdf(enc)
        check("页数正确", i_scan["pages"] == 3 and i_text["pages"] == 3)
        check("图片数正确", i_scan["images"] == 3 and i_text["images"] == 0)
        check("文字层指纹非空", len(i_text["text_sha256"]) == 64
              and len(i_scan["text_sha256"]) == 64)
        check("加密文件被识别", i_enc["encrypted"] is True)
        check("未加密文件标记正确", i_scan["encrypted"] is False)

        section("collect_pdfs 收集与跳过")
        batch = root / "batch"
        (batch / "out").mkdir(parents=True)
        (batch / "sub").mkdir()
        for name in ("a.pdf", "b.pdf", "sub/c.pdf"):
            p = batch / name
            p.write_bytes(scan.read_bytes())
        (batch / "out" / "a-瘦身.pdf").write_bytes(scan.read_bytes())
        found, skipped = slim.collect_pdfs([batch])
        check("目录递归找到 3 个 PDF", len(found) == 3, str(found))
        check("跳过 out 产物目录", all("out" not in f.parts for f in found))
        found2, _ = slim.collect_pdfs([scan, scan, str(scan).upper()])
        check("同一路径去重（含大小写）", len(found2) == 1, str(found2))
        _, sk = slim.collect_pdfs([not_pdf, root / "不存在.pdf"])
        check("非 PDF 与不存在路径进 skipped", len(sk) == 2, str(sk))
        check("skipped 带原因", all("reason" in x for x in sk))

        section("四档瘦身：文字层 / 页数 / 不放大 / 原文件不动")
        before_scan = scan.stat().st_size
        before_fp = i_scan["text_sha256"]
        results = {}
        for key in ("lossless", "light", "standard", "strong"):
            r = slim.slim_one(scan, level=key)
            results[key] = r
            out = Path(r["output"]) if r["output"] else None
            ok = out is not None and out.is_file()
            check(f"{key}: 产出文件", ok, str(r))
            if not ok:
                continue
            got = slim.inspect_pdf(out)
            check(f"{key}: 落在原文件旁 out/", out.parent.name == "out")
            check(f"{key}: 页数不变", got["pages"] == 3)
            check(f"{key}: 文字层指纹不变", got["text_sha256"] == before_fp)
            check(f"{key}: 图片数不变", got["images"] == 3)
            check(f"{key}: 不比原文件大", out.stat().st_size <= before_scan)
            check(f"{key}: 报告里 after_bytes 真实",
                  r["after_bytes"] == out.stat().st_size)
            check(f"{key}: saved_bytes 计算正确",
                  r["saved_bytes"] == before_scan - r["after_bytes"])
            check(f"{key}: ratio 计算正确",
                  abs(r["ratio"] - round(r["saved_bytes"] / before_scan, 4)) < 1e-9)
            every = out.with_suffix(".report.json")
            check(f"{key}: 逐文件 report.json 落盘", every.is_file())
            if every.is_file():
                d = json.loads(every.read_text(encoding="utf-8"))
                check(f"{key}: 逐文件报告字段一致",
                      d["item"]["output"] == r["output"]
                      and d["item"]["after_bytes"] == r["after_bytes"]
                      and d["network_attempts"] == 0)
        check("原文件大小未变", scan.stat().st_size == before_scan)
        check("原文件内容未变", slim.inspect_pdf(scan)["text_sha256"] == before_fp)
        sizes = {k: v["after_bytes"] for k, v in results.items()
                 if v["after_bytes"]}
        check("有损档确实压小了扫描件",
              results["strong"]["after_bytes"] < before_scan,
              f"{before_scan} -> {results['strong']['after_bytes']}")
        check("强力档不大于标准档",
              sizes.get("strong", 1 << 60) <= sizes.get("standard", 0),
              str(sizes))
        check("标准档不大于轻度档",
              sizes.get("standard", 1 << 60) <= sizes.get("light", 0),
              str(sizes))
        check("有损档记录了真实档位参数",
              results["standard"]["quality"] == 70
              and results["standard"]["dpi_target"] == 140,
              str(results["standard"]))
        check("无损档 quality/dpi 为空",
              results["lossless"]["quality"] is None
              and results["lossless"]["dpi_target"] is None)

        section("纯文字 PDF：不放大 / 原样输出契约")
        before_text = text.stat().st_size
        r_text = slim.slim_one(text, level="strong")
        contract_ok = (
            # 有小幅收益就如实输出，没收益就原样输出，两种都是正确行为
            (r_text["status"] == "ok"
             and 0 < r_text["after_bytes"] <= before_text)
            or (r_text["status"] == "ok-no-gain"
                and r_text["after_bytes"] == before_text
                and r_text["level_used"] == "原样输出")
        )
        check("纯文字 PDF 结果不放大且状态自洽", contract_ok, str(r_text))
        check("纯文字 PDF 文字层仍不变",
              r_text["output"] and
              slim.inspect_pdf(r_text["output"])["text_sha256"]
              == i_text["text_sha256"])
        check("纯文字 PDF 页数仍不变",
              r_text["output"] and
              slim.inspect_pdf(r_text["output"])["pages"] == 3)

        # 确定性验证安全网：若输出校验发现页数变化，必须回退成原样输出
        orig_inspect = slim.inspect_pdf
        def lying_inspect(path):
            d = dict(orig_inspect(path))
            if ".slim-" in Path(path).name:
                d["pages"] = d["pages"] + 1
            return d
        slim.inspect_pdf = lying_inspect
        try:
            r_guard = slim.slim_one(scan, level="standard")
        finally:
            slim.inspect_pdf = orig_inspect
        check("校验到页数变化会回退原样输出",
              r_guard["status"] == "ok-no-gain"
              and r_guard["level_used"] == "原样输出"
              and r_guard["after_bytes"] == before_scan,
              str(r_guard))
        check("回退时说明文字写实", "回退" in r_guard["message"],
              r_guard["message"])

        section("透明 PNG / 混合型 PDF 边界")
        r_alpha = slim.slim_one(alpha_pdf, level="standard")
        check("带透明通道的 PDF 能处理", r_alpha["status"].startswith("ok"),
              str(r_alpha.get("message", "")))
        if r_alpha["output"]:
            a = slim.inspect_pdf(r_alpha["output"])
            check("透明 PNG 页页数不变", a["pages"] == 2)
            check("透明 PNG 页文字层不变",
                  a["text_sha256"] == slim.inspect_pdf(alpha_pdf)["text_sha256"])
        r_mixed = slim.slim_one(mixed, level="standard")
        check("混合型 PDF 文字层不变",
              slim.inspect_pdf(r_mixed["output"])["text_sha256"]
              == slim.inspect_pdf(mixed)["text_sha256"])

        section("加密 / 损坏 / 不存在")
        r_enc = slim.slim_one(enc, level="standard")
        check("加密 PDF 跳过", r_enc["status"] == "skipped")
        check("加密 PDF 跳过原因写实", "加密" in r_enc["message"])
        check("加密 PDF 不产出文件", not r_enc["output"])
        r_broken = slim.slim_one(broken, level="standard")
        check("损坏 PDF 跳过", r_broken["status"] == "skipped", str(r_broken))
        check("损坏 PDF 不产出文件", not r_broken["output"])
        r_missing = slim.slim_one(root / "没有.pdf", level="standard")
        check("不存在的文件跳过", r_missing["status"] == "skipped")

        section("输出不覆盖已有产物")
        probe = root / "uprobe"
        probe.mkdir()
        p0 = probe / "x.pdf"
        check("文件不存在时原样返回", slim.unique_path(p0).name == "x.pdf")
        p0.write_bytes(b"pdf")
        u1 = slim.unique_path(p0)
        check("已存在时追加 -2", u1.name == "x-2.pdf", u1.name)
        u1.write_bytes(b"one")
        u2 = slim.unique_path(p0)
        check("再重名时追加 -3", u2.name == "x-3.pdf", u2.name)
        u2.write_bytes(b"two")
        u3 = slim.unique_path(p0)
        check("继续重名时追加 -4", u3.name == "x-4.pdf", u3.name)
        r1 = slim.slim_one(scan, level="lossless")
        r2 = slim.slim_one(scan, level="lossless")
        check("连续两次瘦身不互相覆盖", r1["output"] != r2["output"]
              and Path(r1["output"]).is_file() and Path(r2["output"]).is_file())

        section("目标体积自动阶梯")
        r_big = slim.slim_one(scan, level="standard", target_bytes=100 * 1024 * 1024)
        check("目标很大时用最轻档即可达标",
              r_big["target_reached"] is True
              and r_big["level_used"] in ("lossless", "light"),
              str(r_big["level_used"]))
        r_small = slim.slim_one(scan, level="standard", target_bytes=1024)
        check("目标极小时如实标记未达标", r_small["target_reached"] is False)
        check("目标极小时用到最强档",
              r_small["level_used"] in ("strong", "原样输出"),
              str(r_small["level_used"]))
        check("自动阶梯结果不大于单跑标准档",
              r_small["after_bytes"] <= results["standard"]["after_bytes"],
              f"{r_small['after_bytes']} vs {results['standard']['after_bytes']}")

        section("批量报告与汇总真实性")
        rep = slim.slim_batch([scan, text, broken, not_pdf], level="standard")
        s = rep["summary"]
        ok_items = [r for r in rep["items"] if r["status"].startswith("ok")]
        check("批量处理数 = 3 个有效 PDF", s["processed"] == 3, str(s))
        check("skipped 计入非 PDF", s["skipped"] >= 2, str(s))
        check("汇总 before/after 与逐文件一致",
              s["before_bytes"] == sum(r["before_bytes"] for r in ok_items)
              and s["after_bytes"] == sum(r["after_bytes"] for r in ok_items))
        check("汇总 saved/ratio 计算正确",
              s["saved_bytes"] == s["before_bytes"] - s["after_bytes"]
              and s["ratio"] >= 0)
        check("跳过文件不算进节省", s["input_bytes"] >= s["before_bytes"])
        check("报告标记 0 次联网", rep["network_attempts"] == 0)
        check("报告带有损披露", "画质" in rep["lossy_disclosure"])
        check("报告版本 2.1", rep["version"] == "2.1")
        rp = root / "out" / "report.json"
        check("汇总 report.json 落盘", rp.is_file())
        if rp.is_file():
            d = json.loads(rp.read_text(encoding="utf-8"))
            check("落盘报告与返回值一致",
                  d["summary"] == s and len(d["items"]) == len(rep["items"]))

        rep_auto = slim.slim_batch([scan], level="standard", target_kb=400)
        check("自动模式报告写 level=auto", rep_auto["level"] == "auto")
        check("自动模式保留原请求档位",
              rep_auto["requested_level"] == "standard")
        check("自动模式汇总带 target_reached",
              "target_reached" in rep_auto["summary"])

        section("取消：不留半截产物")
        cancel_root = root / "cancel"
        cancel_root.mkdir()
        c1 = cancel_root / "c1.pdf"
        c2 = cancel_root / "c2.pdf"
        c1.write_bytes(scan.read_bytes())
        c2.write_bytes(scan.read_bytes())
        state = {"cancel": False}
        def on_progress(i, n, name):
            # 第一个文件已经真实产出之后再取消，才能验证「回滚已写文件」
            if i >= 1:
                state["cancel"] = True
        rep_cancel = slim.slim_batch([c1, c2], level="standard",
                                    progress=on_progress,
                                    cancelled=lambda: state["cancel"])
        check("取消标记为真", rep_cancel["cancelled"] is True)
        check("取消后 items 清空", rep_cancel["items"] == [])
        left = list((cancel_root / "out").glob("*")) if (cancel_root / "out").is_dir() else []
        check("取消后 out 目录无残留 PDF / 报告",
              not [p for p in left if p.suffix in (".pdf", ".json")], str(left))
        check("取消后汇总不虚报节省",
              rep_cancel["summary"]["saved_bytes"] == 0)

        section("format_size 边界")
        check("字节", slim.format_size(999) == "999 B")
        check("KB", "KB" in slim.format_size(2048))
        check("MB", "MB" in slim.format_size(3 * 1024 * 1024))
        check("0", slim.format_size(0) == "0 B")

    print(f"\n合计 {_passed}/{_passed + _failed} 项通过")
    if _failed:
        print("\n失败清单：")
        for line in _fail_lines:
            print(line)
    print("结论：" + ("全部通过" if _failed == 0 else f"{_failed} 项未通过"))
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
