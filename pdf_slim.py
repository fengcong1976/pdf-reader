"""PDF 阅读器 2.1 —— PDF 瘦身引擎（纯 Python，无 Qt 依赖，全程 0 联网）。

设计约定（对应《创炫互动-新品立项与验收规范》）：
  * 只读用户主动给的 PDF，绝不改写原文件；结果落在原文件旁的 out/ 目录。
  * 只重写页面内嵌位图与 PDF 对象流，文字层、矢量内容、页数保持不变。
  * 有损档会在界面与报告里明确披露；压完若没变小，原样输出，绝不放大文件。
  * 每次批处理写一份 report.json，逐文件记录真实前后体积与本档参数。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import pymupdf
# 模块级导入，保证 PyInstaller 冻结环境里一定带上 Pillow（自检需要构造噪声图）
from PIL import Image

APP_NAME = "PDF 阅读器"
APP_VERSION = "2.1"

# 本模块不导入任何网络库，也不发起任何网络请求；报告里如实写 0。
NETWORK_ATTEMPTS = 0


@dataclass(frozen=True)
class SlimLevel:
    key: str
    label: str
    quality: Optional[int]
    dpi_target: Optional[int]
    hint: str


LEVELS: tuple[SlimLevel, ...] = (
    SlimLevel("lossless", "无损整理", None, None,
              "只清理冗余对象、压缩数据流，不重新编码图片，画质 100% 不变"),
    SlimLevel("light", "轻度", 82, 170,
              "轻微降采样与重编码，肉眼几乎无差"),
    SlimLevel("standard", "标准（推荐）", 70, 140,
              "扫描件常用档，体积明显下降，文字仍然清晰"),
    SlimLevel("strong", "强力", 52, 100,
              "体积最小，图片细节明显下降，适合只看个大概的存档件"),
)
LEVEL_BY_KEY = {lv.key: lv for lv in LEVELS}
AUTO_LADDER = ("lossless", "light", "standard", "strong")
DEFAULT_LEVEL = "standard"

# 有损档会重新编码内嵌位图：这是真实行为，不是措辞修饰。
LOSSY_DISCLOSURE = (
    "有损档会重新压缩页面内嵌图片（PNG 可能转为 JPEG、透明通道可能丢失），"
    "画质会下降且不可从本工具还原；文字、矢量图形、页数与原文件都不变，"
    "原文件不会被改写。重要合同请保留原件。"
)


def _text_fingerprint(doc) -> str:
    """逐页文字层指纹，用来证明瘦身没有丢字。"""
    h = hashlib.sha256()
    for page in doc:
        try:
            txt = page.get_text()
        except Exception:
            txt = ""
        h.update(txt.encode("utf-8", errors="replace"))
        h.update(b"\x1e")
    return h.hexdigest()


def inspect_pdf(path) -> dict:
    """只读探查：页数、是否加密、内嵌位图数、文字层指纹。"""
    p = Path(path)
    doc = pymupdf.open(str(p))
    try:
        if doc.needs_pass:
            return {"encrypted": True, "pages": 0, "images": 0,
                    "text_sha256": "", "bytes": p.stat().st_size}
        images = 0
        for page in doc:
            try:
                images += len(page.get_images(full=True))
            except Exception:
                pass
        return {
            "encrypted": False,
            "pages": doc.page_count,
            "images": images,
            "text_sha256": _text_fingerprint(doc),
            "bytes": p.stat().st_size,
        }
    finally:
        doc.close()


def unique_path(path: Path) -> Path:
    """不覆盖已有产物：重名时追加 -2 / -3 ……"""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for i in range(2, 10000):
        cand = parent / f"{stem}-{i}{suffix}"
        if not cand.exists():
            return cand
    raise RuntimeError("同名产物过多，请清理 out 目录")


def collect_pdfs(items: Iterable) -> tuple[list[Path], list[dict]]:
    """收集待处理 PDF：支持文件与目录；递归跳过 out/ 产物目录；去重。"""
    found: list[Path] = []
    skipped: list[dict] = []
    seen: set[str] = set()

    def add(p: Path):
        key = os.path.normcase(str(p.resolve()))
        if key in seen:
            return
        seen.add(key)
        found.append(p)

    for raw in items:
        s = str(raw).strip()
        if not s:
            continue
        p = Path(s)
        if p.is_file():
            if p.suffix.lower() == ".pdf":
                add(p)
            else:
                skipped.append({"source": s, "reason": "不是 PDF 文件"})
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if not f.is_file() or f.suffix.lower() != ".pdf":
                    continue
                # 跳过本工具自己的产物目录，避免把压缩结果再压一遍
                rel_parts = {part.lower() for part in f.relative_to(p).parts[:-1]}
                if "out" in rel_parts:
                    continue
                add(f)
        else:
            skipped.append({"source": s, "reason": "路径不存在或不是文件/目录"})
    return found, skipped


def _save_clean(doc, dst: Path, level: SlimLevel) -> bool:
    """按档位重写图片并另存；返回是否真的调用了有损重写。"""
    rewritten = False
    if level.quality is not None:
        func = getattr(doc, "rewrite_images", None)
        if callable(func):
            kwargs = dict(
                dpi_threshold=0,
                dpi_target=level.dpi_target,
                quality=level.quality,
                lossy=True, lossless=True, bitonal=True,
                color=True, gray=True,
            )
            try:
                func(**kwargs)
                rewritten = True
            except TypeError:
                # 老版本 PyMuPDF 参数较少，退到最小参数集
                try:
                    func(dpi_target=level.dpi_target, quality=level.quality)
                    rewritten = True
                except Exception:
                    rewritten = False
            except Exception:
                rewritten = False
    doc.save(str(dst), garbage=4, deflate=True, deflate_images=True,
             deflate_fonts=True, clean=True)
    return rewritten


def _attempt(src: Path, level: SlimLevel, tmp: Path) -> tuple[int, bool]:
    # mkstemp 先建了空文件，PyMuPDF 对已存在目标可能拒绝写入，先删掉
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    doc = pymupdf.open(str(src))
    try:
        rewritten = _save_clean(doc, tmp, level)
    finally:
        doc.close()
    return tmp.stat().st_size, rewritten


def _tmp_pdf(out_dir: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=".slim-", suffix=".pdf", dir=str(out_dir))
    os.close(fd)
    return Path(name)


def slim_one(src, *, level: str = DEFAULT_LEVEL, target_bytes: int = 0,
             out_dir=None, cancelled: Optional[Callable[[], bool]] = None) -> dict:
    """瘦身单个 PDF，返回逐文件报告字典。"""
    src = Path(src)
    rec = {
        "source": str(src), "output": "", "status": "", "message": "",
        "before_bytes": 0, "after_bytes": 0, "saved_bytes": 0, "ratio": 0.0,
        "pages": 0, "images": 0, "text_layer_same": True,
        "level_used": "", "quality": None, "dpi_target": None,
        "target_reached": None,
    }
    if not src.is_file():
        rec.update(status="skipped", message="文件不存在")
        return rec
    rec["before_bytes"] = src.stat().st_size
    try:
        info = inspect_pdf(src)
    except Exception as e:
        rec.update(status="skipped", message=f"无法打开：{type(e).__name__}: {e}")
        return rec
    if info["encrypted"]:
        rec.update(status="skipped", message="加密 PDF，请先解密后再瘦身")
        return rec
    rec["pages"], rec["images"] = info["pages"], info["images"]

    out = Path(out_dir) if out_dir else (src.parent / "out")
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        rec.update(status="failed", message=f"无法创建输出目录：{e}")
        return rec
    dst = unique_path(out / f"{src.stem}-瘦身.pdf")

    ladder = list(AUTO_LADDER) if target_bytes > 0 else [level]
    ladder = [k for k in ladder if k in LEVEL_BY_KEY] or [DEFAULT_LEVEL]
    best: Optional[tuple[int, SlimLevel, Path]] = None
    temps: list[Path] = []
    cancelled_flag = False

    for key in ladder:
        if cancelled is not None and cancelled():
            cancelled_flag = True
            break
        lv = LEVEL_BY_KEY[key]
        tmp = _tmp_pdf(out)
        temps.append(tmp)
        try:
            size, rewritten = _attempt(src, lv, tmp)
            if not rewritten and lv.quality is not None:
                # 当前 PyMuPDF 不支持图片重写时，如实当作无损档记
                lv = LEVEL_BY_KEY["lossless"]
        except Exception as e:
            rec["message"] = f"档位 {lv.label} 失败：{type(e).__name__}: {e}"
            continue
        if best is None or size < best[0]:
            best = (size, lv, tmp)
        if target_bytes > 0 and size <= target_bytes:
            break

    if cancelled_flag or best is None:
        for t in temps:
            try:
                t.unlink(missing_ok=True)
            except OSError:
                pass
        rec.update(status="cancelled" if cancelled_flag else "failed",
                   message="已取消，未产出文件" if cancelled_flag
                           else (rec["message"] or "所有档位都未能生成结果"))
        return rec

    size, lv, tmp = best
    fallback_reason = ""
    if size >= rec["before_bytes"]:
        fallback_reason = "各档都没能变小，已原样输出（画质 100% 不变）"
    else:
        try:
            check = inspect_pdf(tmp)
            if (check["pages"] != info["pages"]
                    or check["text_sha256"] != info["text_sha256"]):
                fallback_reason = "校验到页数或文字层变化，已回退为原样输出"
            elif check["encrypted"]:
                fallback_reason = "输出异常加密，已回退为原样输出"
        except Exception as e:
            fallback_reason = f"输出校验失败（{type(e).__name__}），已回退为原样输出"

    try:
        if fallback_reason:
            shutil.copyfile(src, dst)
            after = dst.stat().st_size
            rec.update(status="ok-no-gain", message=fallback_reason,
                       level_used="原样输出", quality=None, dpi_target=None)
        else:
            os.replace(tmp, dst)
            after = dst.stat().st_size
            rec.update(status="ok", message="瘦身完成",
                       level_used=lv.key, quality=lv.quality,
                       dpi_target=lv.dpi_target)
        rec["after_bytes"] = after
        rec["saved_bytes"] = max(0, rec["before_bytes"] - after)
        rec["ratio"] = (round(rec["saved_bytes"] / rec["before_bytes"], 4)
                        if rec["before_bytes"] else 0.0)
        if target_bytes > 0:
            rec["target_reached"] = bool(after <= target_bytes)
        rec["output"] = str(dst)
    except Exception as e:
        rec.update(status="failed", message=f"写出失败：{type(e).__name__}: {e}")
    finally:
        for t in temps:
            try:
                t.unlink(missing_ok=True)
            except OSError:
                pass

    if rec["output"] and rec["status"].startswith("ok"):
        try:
            Path(rec["output"]).with_suffix(".report.json").write_text(
                json.dumps({"app": APP_NAME, "version": APP_VERSION,
                            "network_attempts": NETWORK_ATTEMPTS, "item": rec},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            pass
    return rec


def slim_batch(items, *, level: str = DEFAULT_LEVEL, target_kb: int = 0,
               out_dir=None, progress: Optional[Callable[[int, int, str], None]] = None,
               cancelled: Optional[Callable[[], bool]] = None,
               write_report: bool = True) -> dict:
    """批量瘦身；返回汇总报告（同时落盘 report.json）。"""
    paths, skipped = collect_pdfs(items)
    target_bytes = int(target_kb) * 1024 if target_kb and target_kb > 0 else 0
    reports: list[dict] = []
    out_root = Path(out_dir) if out_dir else (
        paths[0].parent / "out" if paths else Path("."))
    total = len(paths)

    for i, p in enumerate(paths, 1):
        if cancelled is not None and cancelled():
            break
        rec = slim_one(p, level=level, target_bytes=target_bytes,
                       out_dir=out_dir, cancelled=cancelled)
        reports.append(rec)
        if progress is not None:
            progress(i, total, p.name)

    was_cancelled = bool(cancelled is not None and cancelled())
    if was_cancelled:
        # 取消不留半截产物：本轮已写出的 PDF 与逐文件报告一并回滚
        for rec in reports:
            if rec.get("output"):
                for f in (Path(rec["output"]),
                          Path(rec["output"]).with_suffix(".report.json")):
                    try:
                        f.unlink(missing_ok=True)
                    except OSError:
                        pass
        reports = []

    ok = [r for r in reports if r["status"].startswith("ok")]
    # 只统计真正产出结果的文件；跳过/失败的文件不能算成「省下来的体积」
    before = sum(r["before_bytes"] for r in ok)
    after = sum(r["after_bytes"] for r in ok)
    saved = before - after
    report = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        # 自动模式逐档挑选，实际档位写在每个 item 里；这里不能谎称用了 level
        "level": "auto" if target_bytes > 0 else level,
        "requested_level": level,
        "target_bytes": target_bytes,
        "network_attempts": NETWORK_ATTEMPTS,
        "lossy_disclosure": LOSSY_DISCLOSURE,
        "cancelled": was_cancelled,
        "items": reports,
        "skipped": skipped,
        "summary": {
            "total": total, "processed": len(reports), "ok": len(ok),
            "skipped": sum(1 for r in reports if r["status"] == "skipped")
                       + len(skipped),
            "failed": sum(1 for r in reports if r["status"] == "failed"),
            "input_bytes": sum(r["before_bytes"] for r in reports),
            "before_bytes": before, "after_bytes": after,
            "saved_bytes": saved,
            "ratio": round(saved / before, 4) if before else 0.0,
            "target_reached": (all(r["target_reached"] for r in ok)
                               if target_bytes > 0 and ok else None),
        },
    }
    if write_report and not was_cancelled and reports:
        try:
            out_root.mkdir(parents=True, exist_ok=True)
            (out_root / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            pass
    return report


def format_size(n: int) -> str:
    n = int(n)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def selftest() -> tuple[int, int, list[str]]:
    """冻结环境自检：构造真实 PDF 并跑一次瘦身，不依赖 Qt / 界面。"""
    lines: list[str] = []
    passed = total = 0

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
            lines.append(f"  [OK] {name}")
        else:
            lines.append(f"  [FAIL] {name} {detail}")

    import pymupdf as _m
    lines.append(f"pymupdf {_m.VersionBind} | frozen={getattr(__import__('sys'), 'frozen', False)}")
    check("PyMuPDF 可用", hasattr(_m, "open"))
    lines.append("构造测试 PDF ……")
    with tempfile.TemporaryDirectory(prefix="pdfslim_self_") as td:
        root = Path(td)
        noise = root / "noise.png"
        Image.frombytes("RGB", (900, 1200), os.urandom(900 * 1200 * 3)).save(noise)
        src = root / "scan.pdf"
        doc = _m.open()
        for i in range(2):
            pg = doc.new_page(width=595, height=842)
            pg.insert_text((60, 80), f"SELFTEST PAGE {i + 1} ABC 123", fontsize=14)
            pg.insert_image(_m.Rect(40, 120, 555, 780), filename=str(noise))
        doc.save(str(src), garbage=4, deflate=True)
        doc.close()
        before = src.stat().st_size
        info = inspect_pdf(src)
        r = slim_one(src, level="standard")
        out = Path(r["output"]) if r["output"] else None
        check("产出文件存在", bool(out and out.is_file()), str(r))
        check("原文件未被改写", src.stat().st_size == before)
        if out and out.is_file():
            got = inspect_pdf(out)
            check("页数不变", got["pages"] == info["pages"])
            check("文字层不变", got["text_sha256"] == info["text_sha256"])
            check("结果落在原文件旁 out/", out.parent.name == "out")
            check("报告字段真实", r["after_bytes"] == out.stat().st_size)
        check("结果不比原文件大", (out.stat().st_size <= before)
              if out and out.is_file() else False,
              f"before={before}")
        check("四档定义齐全", len(LEVELS) == 4)
        check("报告标记 0 次联网", NETWORK_ATTEMPTS == 0)
        check("版本号 2.1", APP_VERSION == "2.1")
        lines.append(f"体积：{format_size(before)} → "
                     f"{format_size(r['after_bytes'])}（{r['status']} / {r['level_used']}）")
    lines.append(f"结论：{'全部通过' if passed == total else '有失败项'}（{passed}/{total}）")
    return passed, total, lines
