"""音频探测（PyAV 自带解码器，不依赖系统 ffmpeg）。"""
from __future__ import annotations

from pathlib import Path


def duration(path: str | Path) -> float:
    try:
        import av

        with av.open(str(path)) as container:
            if container.duration:
                return float(container.duration / av.time_base)
            # 某些容器没有 duration，退化为读最后一帧
            last = 0.0
            for frame in container.decode(audio=0):
                if frame.pts is not None and frame.time_base:
                    last = float(frame.pts * frame.time_base)
            return last
    except Exception:
        return 0.0


def has_audio(path: str | Path) -> bool:
    try:
        import av

        with av.open(str(path)) as container:
            return len(container.streams.audio) > 0
    except Exception:
        return False


def fmt_hms(seconds: float, hour: bool = False) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    if hour or h:
        return f"{h:02d}:{m:02d}:{s:05.2f}"
    return f"{m:02d}:{s:05.2f}"
