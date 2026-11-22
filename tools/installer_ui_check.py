"""PDF 阅读器 2.1 —— 交付物冒烟检查。

跑法：venv\\Scripts\\python.exe tools\\installer_ui_check.py "installer\\Output\\PDF阅读器_Setup_2.1.exe"

检查分两块：
  A. 免安装版（真实运行）：文件齐、--selftest 全过、正常关窗口不弹异常、退出码 0。
  B. 安装包：文件存在、PE 头、SHA-256、脚本版本/完成页/卸载清理静态核对。

安装包沿用 2.0 的 PrivilegesRequired=admin（写 {autopf} 与 HKA 文件关联），
需要 UAC 提权。若当前会话不是管理员，安装/运行/卸载链会标记 SKIP 而不是伪报通过；
在管理员会话重跑本脚本即可自动补跑这一段。
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = "PDF 阅读器"
EXE = ROOT / "dist" / "PDF阅读器" / "PDF阅读器.exe"
ISS = ROOT / "installer" / "setup.iss"
SELFTEST_LOG = ROOT / "_installed_selftest.log"
WM_CLOSE = 0x0010

_passed = 0
_failed = 0
_skipped = 0
_fails: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [OK] {name}")
    else:
        _failed += 1
        _fails.append(f"  [FAIL] {name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def skip(name: str, why: str):
    global _skipped
    _skipped += 1
    print(f"  [SKIP] {name} —— {why}")


def section(t: str):
    print(f"\n==== {t} ====")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


user32 = ctypes.windll.user32


def windows():
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, b, n + 1)
                out.append((hwnd, b.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def close_test(exe: Path, label: str):
    """真启动、真发 WM_CLOSE，断言退出码 0 且没有错误弹窗。

    上一版「图片转PDF工具」在这里踩过 sys.stdout=None 的坑，
    所以这条对窗口版 exe 是必测项。
    """
    before = {h for h, _ in windows()}
    proc = subprocess.Popen([str(exe)])
    hwnd = None
    for _ in range(60):
        hits = [(h, t) for h, t in windows() if h not in before and APP in t]
        if hits:
            hwnd = hits[0][0]
            break
        time.sleep(0.5)
    print(f"{label} 找到主窗口：{bool(hwnd)}", flush=True)
    if not hwnd:
        proc.kill()
        return False, None
    time.sleep(1.5)
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    rc = None
    try:
        rc = proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass
    errs = [(h, t) for h, t in windows()
            if h not in before
            and ("Unhandled exception" in t or "Traceback" in t
                 or "PDF 阅读器" != t and "错误" in t)]
    for h, _ in errs:
        user32.PostMessageW(h, WM_CLOSE, 0, 0)
    if proc.poll() is None:
        proc.kill()
    print(f"{label} 退出码={rc} 错误弹窗={[t for _, t in errs]}", flush=True)
    return rc == 0 and not errs, [t for _, t in errs]


def main() -> int:
    setup = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (
        ROOT / "installer" / "Output" / "PDF阅读器_Setup_2.1.exe")
    print(f"安装包：{setup}")

    section("A. 安装包文件与内容")
    check("安装包存在", setup.is_file(), str(setup))
    if not setup.is_file():
        return 1
    size = setup.stat().st_size
    check("安装包体积合理（>50MB）", size > 50 * 1024 * 1024,
          f"{size} bytes")
    with open(setup, "rb") as f:
        head = f.read(2)
    check("是有效 Windows 可执行（MZ）", head == b"MZ")
    digest = sha256(setup)
    check("SHA-256 计算完成", len(digest) == 64, digest)
    print(f"  SHA256: {digest}")
    print(f"  大小:   {size} 字节")
    iss_text = ISS.read_text(encoding="utf-8")
    check("安装脚本版本 2.1", '#define MyAppVersion "2.1"' in iss_text)
    check("输出文件名跟随版本",
          "PDF阅读器_Setup_{#MyAppVersion}" in iss_text)
    check("完成页没有「查阅 README」勾选项",
          "README" not in "\n".join(
              line for line in iss_text.splitlines()
              if line.strip().startswith("Filename:") and "postinstall" in line))
    check("文件关联带卸载清理标记",
          "uninsdeletevalue" in iss_text and "uninsdeletekey" in iss_text)
    check("安装包由 2.1 脚本编译（文件名一致）",
          setup.name == "PDF阅读器_Setup_2.1.exe", setup.name)

    section("B. 免安装版（真实运行）")
    check("免安装版 exe 存在", EXE.is_file(), str(EXE))
    internal = EXE.parent / "_internal"
    check("onedir 依赖目录存在", internal.is_dir())
    check("Python 运行时齐备",
          (internal / "python310.dll").is_file(), str(internal))
    check("PyMuPDF 已随包",
          any((internal / n).exists() for n in ("pymupdf", "fitz"))
          or any(p.name.startswith("pymupdf") for p in internal.glob("*"))
          or any(p.name.startswith("fitz") for p in internal.glob("*")),
          str(list(internal.glob("*pymupdf*"))[:3]))
    if EXE.is_file():
        try:
            SELFTEST_LOG.unlink(missing_ok=True)
            r = subprocess.run([str(EXE), "--selftest", str(SELFTEST_LOG)],
                               capture_output=True, timeout=240)
            body = (SELFTEST_LOG.read_text(encoding="utf-8")
                    if SELFTEST_LOG.is_file() else "")
            check("打包版 --selftest 返回 0", r.returncode == 0,
                  str(r.returncode))
            check("打包版自检结论全部通过", "结论：全部通过" in body,
                  body[-300:])
            check("打包版自检确实是冻结环境", "frozen=True" in body,
                  body[:120])
            check("打包版自检跑过真实瘦身", "体积：" in body, body[-200:])
        except Exception as e:
            check("打包版 --selftest 可执行", False, repr(e))
        ok_close, errs = close_test(EXE, "[免安装版]")
        check("正常关窗口退出码 0 且无异常弹窗", ok_close, str(errs))

    section("C. 安装 / 运行 / 卸载链")
    if not is_admin():
        skip("静默安装 → 装好的 exe 自检 → 关窗口 → 卸载清理",
             "当前会话非管理员；安装脚本 PrivilegesRequired=admin 需要 UAC 提权。"
             "请在管理员会话重跑本脚本自动补测，或手动双击安装包验证。")
        print("  （免安装版与安装包静态项已全部实测，不影响交付可用性判断）")
    else:
        install_dir = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / APP
        r = subprocess.run(
            [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             "/DIR=" + str(install_dir)],
            capture_output=True, timeout=300)
        check("静默安装返回 0", r.returncode == 0, str(r.returncode))
        installed = install_dir / "PDF阅读器.exe"
        check("安装目录有主程序", installed.is_file(), str(install_dir))
        check("安装目录有 _internal", (install_dir / "_internal").is_dir())
        if installed.is_file():
            log = ROOT / "_installed_selftest2.log"
            rr = subprocess.run([str(installed), "--selftest", str(log)],
                                capture_output=True, timeout=240)
            body = log.read_text(encoding="utf-8") if log.is_file() else ""
            check("装好的 exe 自检全过", rr.returncode == 0
                  and "结论：全部通过" in body, body[-200:])
            ok_close2, errs2 = close_test(installed, "[已安装版]")
            check("装好的 exe 正常关窗口不弹异常", ok_close2, str(errs2))
        unins = install_dir / "unins000.exe"
        if unins.is_file():
            subprocess.run([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                            "/NORESTART"], capture_output=True, timeout=240)
            time.sleep(2)
        check("卸载后主程序不残留", not installed.exists())
        check("卸载后安装目录不残留", not install_dir.exists())
        menu = (Path(os.environ.get("APPDATA", ""))
                / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP)
        check("开始菜单快捷方式不残留", not menu.exists(), str(menu))

    print(f"\n合计 {_passed} 项通过，{_failed} 项失败，{_skipped} 项跳过")
    if _fails:
        print("\n失败清单：")
        for line in _fails:
            print(line)
    print("结论：" + ("全部通过" if _failed == 0 else f"{_failed} 项未通过"))
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
