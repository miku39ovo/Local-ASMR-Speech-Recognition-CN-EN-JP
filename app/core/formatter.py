"""LRC / TXT / SRT 生成。"""
from __future__ import annotations

from pathlib import Path

from .postprocess import Line

FORMAT_EXT = {"lrc": ".lrc", "txt": ".txt", "srt": ".srt"}
FORMAT_LABEL = {"lrc": "LRC 歌词", "txt": "纯文本", "srt": "SRT 字幕"}


def _ts_lrc(sec: float, hour: bool) -> str:
    sec = max(0.0, sec)
    if hour:
        h = int(sec // 3600)
        m = int(sec % 3600 // 60)
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:05.2f}"
    m = int(sec // 60)
    s = sec % 60
    return f"{m:02d}:{s:05.2f}"


def _ts_srt(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_lrc(lines: list[Line], title: str, total: float, hour: bool = False) -> str:
    head = [f"[ti:{title}]", "[by:ASMR2LRC]"]
    if total > 0:
        sec = int(total)
        h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
        head.append(f"[length:{h:02d}:{m:02d}:{s:02d}]" if h else f"[length:{m:02d}:{s:02d}]")
    body = [f"[{_ts_lrc(ln.start, hour or total >= 3600)}]{ln.text}" for ln in lines]
    return "\r\n".join(head + [""] + body) + "\r\n"


def make_txt(lines: list[Line]) -> str:
    return "\r\n".join(ln.text for ln in lines if ln.text) + "\r\n"


def make_srt(lines: list[Line]) -> str:
    out = []
    idx = 0
    for ln in lines:
        if not ln.text:
            continue
        idx += 1
        out.append(str(idx))
        out.append(f"{_ts_srt(ln.start)} --> {_ts_srt(ln.end)}")
        out.append(ln.text)
        out.append("")
    return "\r\n".join(out)


def write_text(path: Path, content: str, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding, errors="replace")


def output_paths(
    audio: Path,
    formats: list[str],
    output_mode: str,
    output_dir: str,
    keep_structure: bool,
    root: Path | None,
) -> list[Path]:
    if output_mode == "custom" and output_dir:
        base = Path(output_dir)
        rel_parent = Path()
        if keep_structure and root:
            try:
                rel_parent = audio.parent.relative_to(root)
            except ValueError:
                rel_parent = Path()
        target_dir = base / rel_parent
    else:
        target_dir = audio.parent
    return [target_dir / (audio.stem + FORMAT_EXT[f]) for f in formats if f in FORMAT_EXT]
