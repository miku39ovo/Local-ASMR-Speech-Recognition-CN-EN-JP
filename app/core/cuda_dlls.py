"""把 pip 安装的 CUDA 运行库（cuBLAS / cuDNN）加入 DLL 搜索路径。

CTranslate2 的 wheel 不自带 cuBLAS，Windows 上必须能找到 cublas64_12.dll。
"""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path

_HANDLES = []


def setup() -> list[str]:
    if sys.platform != "win32":
        return []
    roots: list[Path] = []
    try:
        roots += [Path(p) for p in site.getsitepackages()]
    except Exception:
        pass
    try:
        roots.append(Path(site.getusersitepackages()))
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        roots.append(Path(sys._MEIPASS))  # type: ignore[attr-defined]

    dirs: list[str] = []
    for root in roots:
        nv = root / "nvidia"
        if not nv.is_dir():
            continue
        for bin_dir in sorted(nv.glob("*/bin")):
            if not bin_dir.is_dir():
                continue
            d = str(bin_dir)
            if d in dirs:
                continue
            dirs.append(d)
            try:
                _HANDLES.append(os.add_dll_directory(d))
            except Exception:
                pass
    if dirs:
        os.environ["PATH"] = ";".join(dirs) + ";" + os.environ.get("PATH", "")
    return dirs
