"""PDF 阅读器 2.1 —— PDF 瘦身命令行入口（无界面、无联网）。

用法：
  python cli_slim.py 文件.pdf [另一个.pdf ...] --level standard
  python cli_slim.py D:\扫描件 --target-kb 2048        # 按目标体积自动挑档
  python cli_slim.py 文件.pdf --level lossless --out D:\输出
  python cli_slim.py --selftest                         # 跑冻结环境同款自检
"""

from __future__ import annotations

import argparse
import json
import sys

import pdf_slim as slim


def main() -> int:
    p = argparse.ArgumentParser(
        description="PDF 瘦身：只压缩页面内嵌图片，文字层与页数不变，原文件不改写")
    p.add_argument("paths", nargs="*", help="PDF 文件或文件夹（文件夹会递归跳过 out 目录）")
    p.add_argument("--level", choices=[lv.key for lv in slim.LEVELS],
                   default=slim.DEFAULT_LEVEL, help="瘦身档位，默认 standard")
    p.add_argument("--target-kb", type=int, default=0,
                   help="目标体积（KB）；>0 时自动从最轻档逐级尝试到达标")
    p.add_argument("--out", default=None, help="输出目录；默认每个原文件旁的 out 目录")
    p.add_argument("--json", action="store_true", help="只输出 report.json 内容")
    p.add_argument("--selftest", action="store_true", help="跑一次自检后退出")
    args = p.parse_args()

    if args.selftest:
        passed, total, lines = slim.selftest()
        print("\n".join(lines))
        return 0 if passed == total else 1
    if not args.paths:
        p.print_help()
        return 2

    report = slim.slim_batch(
        args.paths, level=args.level, target_kb=args.target_kb,
        out_dir=args.out,
        progress=lambda i, n, name: print(f"[{i}/{n}] {name}", flush=True),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("\n==== 逐文件 ====")
    for r in report["items"]:
        if r["status"].startswith("ok"):
            print(f"  {r['source']}\n    → {r['output']}\n"
                  f"    {slim.format_size(r['before_bytes'])} → "
                  f"{slim.format_size(r['after_bytes'])} "
                  f"（节省 {r['ratio'] * 100:.1f}%，{r['level_used']}）"
                  + ("" if r["status"] == "ok" else f"  {r['message']}"))
        else:
            print(f"  {r['source']}  [{r['status']}] {r['message']}")
    for s in report["skipped"]:
        print(f"  跳过：{s['source']} —— {s['reason']}")
    s = report["summary"]
    print("\n==== 汇总 ====")
    print(f"  输入 {s['total']} 个，成功 {s['ok']}，跳过 {s['skipped']}，失败 {s['failed']}")
    print(f"  {slim.format_size(s['before_bytes'])} → "
          f"{slim.format_size(s['after_bytes'])}，"
          f"共省 {slim.format_size(s['saved_bytes'])}（{s['ratio'] * 100:.1f}%）")
    print(f"  联网次数：{report['network_attempts']}")
    print("  " + slim.LOSSY_DISCLOSURE)
    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
