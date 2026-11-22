# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

# OCR 相关库带有模型文件(yaml/onnx)和动态库，需整体收集
datas = [('icons', 'icons')]
binaries = []
hiddenimports = []
for _pkg in ('rapidocr_onnxruntime', 'onnxruntime', 'cv2', 'shapely', 'pyclipper'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onedir 模式：生成 dist/PDF阅读器/ 目录（exe + _internal 依赖），
# 启动更快、便于安装包整体分发；不用 onefile 单文件
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDF阅读器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icons/app.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PDF阅读器',
)
