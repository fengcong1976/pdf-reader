# PDF 阅读器 2.1

> 免费下载与图文教程：<https://www.mrheedu.com/apps/pdf-reader>　·　更多免费软件：[www.mrheedu.com](https://www.mrheedu.com)
基于 PySide6 + PyMuPDF 的 Windows 离线 PDF 阅读器。**2.1 新增「PDF 瘦身」**：把一个或一批 PDF 里的内嵌图片重新压缩，文字层、矢量图形、页数、原文件都不动，结果另存到原文件旁的 `out` 文件夹。

- 官网：http://www.mrheedu.com
- 开发者：深圳市创炫互动网络科技有限公司
- 运行方式：Windows 桌面程序，无账号、无云同步、全程 0 联网

## 2.1 更新内容

| 项目 | 内容 |
|---|---|
| 新增 | 工具箱「PDF 瘦身」页签，支持批量加入多个 PDF，打开工具箱时自动放入当前文档 |
| 四档 | 无损整理 / 轻度 / 标准（推荐）/ 强力 |
| 自动模式 | 填一个目标体积（KB），从最轻档逐级尝试，第一个达标的结果就用它；都不达标则给最小结果并如实提示 |
| 交付 | 结果落在原文件旁 `out\原名-瘦身.pdf`，重名自动加 `-2`，压完自动打开输出文件夹 |
| 报告 | 每份结果旁边有 `原名-瘦身.report.json`，批次有 `out\report.json`，逐文件记录前后体积、实际档位、页数、文字层校验、联网次数 |
| 安全 | 原文件只读；任何档位压完没变小就原样输出，绝不放大；校验到页数或文字层变化也原样回退 |

**有损披露**：除「无损整理」外都会重新编码页面内嵌位图（PNG 可能转 JPEG、透明通道可能丢失），画质会下降且不可由本工具还原。重要合同请保留原件。

## 目录结构

```
main.py              主窗口、菜单、关于/使用说明、--selftest 入口
tools.py             PDF 工具箱（拆分/合并/加密/文本提取/AI翻译/转图片/瘦身）+ SlimWorker
pdf_slim.py          瘦身引擎（纯 Python，无 Qt、无网络）
cli_slim.py          命令行批量入口
pdf_document.py      文档封装
pdf_view.py          页面视图与缩放
ocr.py / translator.py / slideshow.py / sidebar.py / search_bar.py
verify.py            核心引擎自检（125 项）
ui_test.py           界面自检（60 项，真实建窗口、点控件、跑线程）
PDF阅读器.spec        PyInstaller onedir 打包配置
installer/setup.iss  Inno Setup 6 安装脚本（版本 2.1）
installer/Output/    安装包与升级说明
截图/                界面留档
```

## 使用

**图形界面**：菜单「工具 → PDF 工具箱」→ 选「PDF 瘦身（压缩体积）」→ 添加文件 → 选档位（或填目标体积）→ 点「开始瘦身」。详细说明见 [`docs/PDF瘦身-使用说明.md`](docs/PDF瘦身-使用说明.md)。

**命令行**（源码环境）：

```bat
venv\Scripts\python.exe cli_slim.py "D:\扫描件\合同.pdf" --level standard
venv\Scripts\python.exe cli_slim.py "D:\扫描件" --target-kb 2048
venv\Scripts\python.exe cli_slim.py "D:\扫描件" --level lossless --json
```

目录会递归收集 PDF 并自动跳过 `out` 产物目录。

## 验收

```bat
venv\Scripts\python.exe verify.py          :: 核心引擎 125 项
venv\Scripts\python.exe ui_test.py         :: 界面 60 项
venv\Scripts\python.exe main.py --selftest :: 出厂自检 11 项
venv\Scripts\python.exe cli_slim.py --selftest
```

引擎自检覆盖：四档压缩率单调、文字层/页数不变量、不放大回退、目标体积阶梯、批量报告真实性、取消回滚、加密/损坏跳过、运行时掐断 socket 仍能完成、版本一致性。
界面自检覆盖：页签互斥、文件去重、档位联动、有损披露文案、真实跑一次瘦身并核对产物与报告、结果弹窗各分支、关窗口不崩。

冻结版自检（窗口版 exe 无控制台，结果写日志文件）：

```bat
dist\PDF阅读器\PDF阅读器.exe --selftest selftest_exe.log
```

安装包冒烟：

```bat
venv\Scripts\python.exe tools\installer_ui_check.py "installer\Output\PDF阅读器_Setup_2.1.exe"
```

## 打包

**必须用项目自带的 `venv\Scripts\python.exe`（Python 3.10）**：OCR 依赖 `rapidocr_onnxruntime` / `shapely` / `pyclipper` 只装在这个虚拟环境里，现有 dist 也是 python310.dll。

```bat
venv\Scripts\python.exe -m PyInstaller --noconfirm PDF阅读器.spec
ISCC.exe installer\setup.iss
```

产物：`dist\PDF阅读器\`（onedir，需整目录一起拷贝）、`installer\Output\PDF阅读器_Setup_2.1.exe`。

PyInstaller 清理旧输出时会批量删几千个文件，可能触发安全策略的批量删除保护（表现为命令退出码 0 但 exe 时间戳没变）。稳妥做法：先把旧 `dist\PDF阅读器` 和 `build` 改名移走再构建。

## 依赖

`requirements.txt`：PySide6、PyMuPDF、Pillow、rapidocr-onnxruntime。瘦身引擎只用 PyMuPDF；Pillow 仅用于自检构造噪声样张。