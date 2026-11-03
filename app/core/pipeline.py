"""单文件处理管线：探测 → 转写 → 后处理 → 写出。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import Settings
from . import audio, formatter
from .engine import AsrEngine
from .models import MODEL_SPECS, installed, model_key_for
from .postprocess import Line, build_lines

log = logging.getLogger(__name__)


class Cancelled(Exception):
    pass


@dataclass
class Job:
    path: Path
    root: Path | None = None
    language: str | None = None
    status: str = "pending"     # pending / running / done / skipped / failed
    progress: int = 0
    message: str = ""
    elapsed: float = 0.0
    duration: float = 0.0
    tokens: int = 0
    tps: float = 0.0

    @property
    def display_name(self) -> str:
        return self.path.name


@dataclass
class Result:
    status: str
    lines: list[Line] = field(default_factory=list)
    outputs: list[Path] = field(default_factory=list)
    elapsed: float = 0.0
    duration: float = 0.0
    message: str = ""
    tokens: int = 0
    tps: float = 0.0


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
    return path


def _pick_model(settings: Settings, language: str):
    key = model_key_for(settings, language)
    spec = MODEL_SPECS.get(key)
    if spec is None:
        raise RuntimeError(f"未知模型：{key}")
    if not installed(spec):
        raise RuntimeError(f"模型未下载：{spec.label}，请先在「模型管理」中下载")
    return spec


def _estimate_need_mb(spec) -> int:
    """按权重体积估算 fp16 运行所需显存（含激活余量）。"""
    try:
        size = (spec.path / "model.bin").stat().st_size
        return int(size / 1024 / 1024 * 1.4)
    except Exception:
        return 2600


def process_file(
    job: Job,
    settings: Settings,
    engine: AsrEngine,
    *,
    progress: Callable[[int, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> Result:
    t0 = time.time()
    language = job.language or settings.language
    lang_for_model = "auto" if language == "auto" else language
    spec = _pick_model(settings, lang_for_model)

    fmt_list = [f for f in settings.formats if f in formatter.FORMAT_EXT]
    if not fmt_list:
        raise RuntimeError("未选择输出格式")

    dur = job.duration or audio.duration(job.path)
    job.duration = dur
    outputs = formatter.output_paths(
        job.path, fmt_list, settings.output_mode, settings.output_dir,
        settings.keep_structure, job.root,
    )

    # 已存在则按策略处理
    if settings.overwrite == "skip" and all(p.exists() for p in outputs):
        if progress:
            progress(100, "已存在，跳过")
        return Result("skipped", outputs=outputs, duration=dur, message="已存在同名文件")
    if settings.overwrite == "rename":
        outputs = [_unique(p) for p in outputs]

    if cancel and cancel():
        raise Cancelled()

    if progress:
        progress(1, "加载模型…")
    # 可用显存由 engine.load 在释放上一个模型之后自行测量
    dev, compute = engine.load(spec.path, settings.compute_mode,
                               need_mb=_estimate_need_mb(spec))
    if on_log:
        on_log(f"[{job.path.name}] 模型 {spec.key}  device={dev} compute={compute}")

    if progress:
        progress(3, f"识别中（{dev}/{compute}）…")

    engine.metrics.reset()
    t_asr = time.time()
    gen, info = engine.transcribe(
        str(job.path),
        None if lang_for_model == "auto" else lang_for_model,
        beam_size=settings.beam_size,
        vad=settings.vad,
        vad_threshold=settings.vad_threshold,
        condition_on_previous=settings.condition_on_previous,
        chunked=getattr(spec, "broken_timestamps", False),
        word_timestamps=getattr(spec, "word_timestamps", False),
    )
    detected = getattr(info, "language", language)
    if on_log and lang_for_model == "auto":
        on_log(f"[{job.path.name}] 检测语言：{detected}")

    segs = []
    for seg in gen:
        if cancel and cancel():
            raise Cancelled()
        segs.append(seg)
        if dur > 0:
            pct = 3 + int(min(0.92, seg.end / dur) * 92)
            if progress:
                progress(min(95, pct), f"识别中 {seg.end/60:.1f}/{dur/60:.1f} 分钟")
    asr_elapsed = time.time() - t_asr

    if progress:
        progress(96, "整理断句与时间轴…")
    lang_used = detected if lang_for_model == "auto" else lang_for_model
    max_chars = settings.max_chars
    if str(lang_used).startswith("en") and max_chars < 32:
        max_chars = 42  # 英语按单词排版，28 字符会切碎句子
    elif str(lang_used).startswith("zh") and max_chars > 20:
        max_chars = 20  # 中文一行 20 字以内更接近常见 LRC 观感
    spans = None
    use_words = getattr(spec, "word_timestamps", False)
    chunked = getattr(spec, "broken_timestamps", False)
    if not chunked and not use_words and dur > 15:
        spans = engine.speech_spans(str(job.path), settings.vad_threshold)
    lines = build_lines(
        segs,
        lang=lang_used,
        max_chars=max_chars,
        max_line_sec=settings.max_line_sec,
        merge_gap=settings.merge_gap,
        pre_roll=settings.pre_roll,
        offset=settings.offset,
        blank_on_silence=settings.blank_on_silence,
        speech_spans=spans,
    )
    if not lines:
        return Result("failed", duration=dur, elapsed=time.time() - t0,
                      message="未识别到有效语音")

    if progress:
        progress(98, "写出文件…")
    total = dur or (lines[-1].end if lines else 0)
    for fmt, path in zip(fmt_list, outputs):
        if fmt == "lrc":
            content = formatter.make_lrc(lines, job.path.stem, total, settings.hour_timestamp)
        elif fmt == "txt":
            content = formatter.make_txt(lines)
        else:
            content = formatter.make_srt(lines)
        formatter.write_text(path, content, settings.encoding)

    elapsed = time.time() - t0
    rtf = elapsed / dur if dur else 0
    tokens = engine.metrics.tokens
    tps = engine.metrics.tps
    if tps <= 0 and tokens >= 8 and asr_elapsed > 0.2:
        tps = tokens / asr_elapsed  # 只出 1 段时用整体耗时兜底
    speed = f" · {tps:.0f} tok/s" if tokens >= 8 else ""
    if progress:
        progress(100, f"完成 {len(lines)} 行，用时 {elapsed:.1f}s")
    return Result("done", lines=lines, outputs=outputs, elapsed=elapsed,
                  duration=dur, message=f"{len(lines)} 行 / RTF {rtf:.3f}{speed}",
                  tokens=tokens, tps=tps)
