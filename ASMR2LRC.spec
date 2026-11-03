# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：python -m PyInstaller ASMR2LRC.spec --noconfirm"""
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

ROOT = Path(SPECPATH)
# 取当前解释器（虚拟环境）的 site-packages，避免写死 .venv 路径
SITE = Path(sysconfig.get_paths()["purelib"])
ICON = ROOT / "ASMR2LRC.ico"

datas, binaries, hiddenimports = [], [], []
for pkg in ("ctranslate2", "av", "faster_whisper", "onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] collect_all {pkg} failed: {exc}")

for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] {pkg}: {exc}")

# collect_dynamic_libs 会把 DLL 平铺；再补一份带目录的结构给 cuda_dlls 搜索
for sub in ("cublas", "cudnn", "cuda_nvrtc"):
    bin_dir = SITE / "nvidia" / sub / "bin"
    if bin_dir.is_dir():
        for f in bin_dir.glob("*.dll"):
            binaries.append((str(f), f"nvidia/{sub}/bin"))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["app.core.cuda_dlls", "app.ui.main_window"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "torchaudio", "transformers",
        "matplotlib", "scipy", "pandas", "tkinter", "IPython",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick", "PySide6.Qt3DCore", "PySide6.QtQuick",
        "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtPdf",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ASMR2LRC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON) if ICON.exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ASMR2LRC",
)
