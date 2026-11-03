"""faster-whisper 引擎封装：单实例、按语言换模型、显存自适应。"""
from __future__ import annotations

import gc
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .gpu import cuda_available

log = logging.getLogger(__name__)


@dataclass
class Metrics:
    """解码吞吐统计：UI 定时读取，用于显示 tok/s。

    只做 int/float 赋值，跨线程读取足够安全。
    """

    tokens: int = 0
    tps: float = 0.0
    elapsed: float = 0.0
    _t0: float = 0.0

    def reset(self) -> None:
        self.tokens = 0
        self.tps = 0.0
        self.elapsed = 0.0
        self._t0 = 0.0

    def start(self) -> None:
        """在转写开始前打点，保证「只产出 1 段」时也能算出 tok/s。"""
        if self._t0 <= 0:
            self._t0 = time.perf_counter()

    def add(self, n: int) -> None:
        if n <= 0:
            return
        if self._t0 <= 0:
            self._t0 = time.perf_counter()
        self.tokens += n
        self.elapsed = time.perf_counter() - self._t0
        if self.elapsed > 0.15:
            self.tps = self.tokens / self.elapsed


class Segment:
    __slots__ = ("start", "end", "text", "avg_logprob", "no_speech_prob", "words")

    def __init__(self, start: float, end: float, text: str,
                 avg_logprob: float = 0.0, no_speech_prob: float = 0.0,
                 words: list[tuple[float, float, str]] | None = None):
        self.start = start
        self.end = end
        self.text = text
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob
        self.words = words

    def __repr__(self) -> str:
        return f"Segment({self.start:.2f}-{self.end:.2f}, {self.text!r})"


class AsrEngine:
    """同一时间只保留一个模型，切换语言时显式释放，避免 8GB 显存被吃满。"""

    def __init__(self) -> None:
        self._model = None
        self._key: str | None = None
        self.compute_type: str = ""
        self.device: str = ""
        self.metrics = Metrics()

    def count_tokens(self, text: str) -> int:
        """统计一段文本的 token 数，用于 tok/s。

        优先用模型自带的 Whisper tokenizer；取不到时按字符数估算。
        """
        if not text:
            return 0
        model = self._model
        if model is not None:
            for attr in ("tokenizer", "hf_tokenizer"):
                tok = getattr(model, attr, None)
                if tok is None:
                    continue
                try:
                    return len(tok.encode(text))
                except Exception:
                    continue
        # 兜底估算：日语约 1.3 字符/token，英语约 3.8
        ja = any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in text)
        return max(1, int(round(len(text) / (1.3 if ja else 3.8))))

    @property
    def loaded_key(self) -> str | None:
        return self._key

    def _pick_compute(self, mode: str, free_mb: int, need_mb: int = 0) -> str:
        if mode in ("float16", "int8_float16", "int8"):
            return mode
        # auto：可用显存不足以放下 fp16 权重时降到 int8
        # （需要 ctranslate2>=4.7.1 才能在 50 系上跑 int8）
        need = max(2600, need_mb)
        return "int8_float16" if 0 < free_mb < need else "float16"

    def load(self, model_dir: Path, mode: str = "auto", free_mb: int = 0,
             need_mb: int = 0) -> tuple[str, str]:
        from faster_whisper import WhisperModel

        key = str(model_dir)
        if self._model is not None and self._key == key:
            return self.device, self.compute_type

        # 必须先释放上一个模型再测可用显存，否则会把旧模型的占用算进去，
        # 导致明明够用却降级到 int8。
        self.release()
        use_cuda = cuda_available()
        device = "cuda" if use_cuda else "cpu"
        if use_cuda and mode == "auto":
            try:
                from .gpu import query_vram

                free_mb = query_vram().free_mb
            except Exception:  # noqa: BLE001
                free_mb = free_mb or 0
        compute = self._pick_compute(mode, free_mb, need_mb) if use_cuda else "int8"
        if not use_cuda:
            compute = "int8"

        attempts = [(device, compute)]
        if use_cuda:
            attempts += [("cuda", "float16"), ("cpu", "int8")]

        last_err: Exception | None = None
        for dev, ct in attempts:
            try:
                log.info("加载模型 %s device=%s compute=%s", model_dir.name, dev, ct)
                self._model = WhisperModel(
                    str(model_dir),
                    device=dev,
                    compute_type=ct,
                    cpu_threads=4,
                    num_workers=1,
                    local_files_only=True,
                )
                self._key = key
                self.device = dev
                self.compute_type = ct
                return dev, ct
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                log.warning("加载失败 device=%s compute=%s: %s", dev, ct, exc)
                self._model = None
                gc.collect()
        raise RuntimeError(f"模型加载失败：{last_err}")

    def release(self) -> None:
        if self._model is not None:
            try:
                del self._model
            except Exception:
                pass
            self._model = None
            self._key = None
            gc.collect()

    def transcribe(
        self,
        audio_path: str,
        language: str | None,
        *,
        beam_size: int = 5,
        vad: bool = True,
        vad_threshold: float = 0.25,
        condition_on_previous: bool = False,
        initial_prompt: str | None = None,
        chunked: bool = False,
        word_timestamps: bool = False,
    ) -> tuple[Iterator[Segment], object]:
        if self._model is None:
            raise RuntimeError("模型未加载")

        # 提前打点：整段音频只出 1 个 segment 时也能算出 tok/s
        self.metrics.start()

        if chunked:
            return self._transcribe_chunked(
                audio_path, language,
                beam_size=beam_size,
                vad_threshold=vad_threshold,
            )

        segments, info = self._model.transcribe(
            audio_path,
            language=language or None,
            beam_size=beam_size,
            best_of=beam_size,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            condition_on_previous_text=condition_on_previous,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            repetition_penalty=1.05,
            no_repeat_ngram_size=5,
            word_timestamps=word_timestamps,
            vad_filter=vad,
            vad_parameters=dict(
                threshold=vad_threshold,
                min_speech_duration_ms=120,
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ) if vad else None,
            initial_prompt=initial_prompt,
        )

        def gen() -> Iterator[Segment]:
            for s in segments:
                words = None
                if getattr(s, "words", None):
                    words = [(float(w.start), float(w.end), w.word) for w in s.words]
                text = (s.text or "").strip()
                self.metrics.add(self.count_tokens(text))
                yield Segment(
                    float(s.start), float(s.end), text,
                    float(getattr(s, "avg_logprob", 0.0) or 0.0),
                    float(getattr(s, "no_speech_prob", 0.0) or 0.0),
                    words=words,
                )

        return gen(), info

    def speech_spans(self, audio_path: str, threshold: float = 0.25) -> list[tuple[float, float]]:
        """返回语音活动区间（秒），用于把行首对齐到真实开口处。"""
        try:
            from faster_whisper.audio import decode_audio
            from faster_whisper.vad import VadOptions, get_speech_timestamps

            sr = 16000
            audio = decode_audio(audio_path, sampling_rate=sr)
            spans = get_speech_timestamps(
                audio,
                VadOptions(
                    threshold=threshold,
                    min_speech_duration_ms=120,
                    min_silence_duration_ms=350,
                    speech_pad_ms=120,
                ),
                sampling_rate=sr,
            )
            return [(s["start"] / sr, s["end"] / sr) for s in spans]
        except Exception as exc:  # noqa: BLE001
            log.warning("VAD 分段失败：%s", exc)
            return []

    def _transcribe_chunked(
        self,
        audio_path: str,
        language: str | None,
        *,
        beam_size: int = 5,
        vad_threshold: float = 0.25,
        max_chunk: float = 14.0,
    ):
        """面向时间戳失效的模型（如 anime-whisper）：
        先用 VAD 切出自然语音段，再逐段识别，用段边界作为时间锚点。
        """
        import numpy as np
        from types import SimpleNamespace

        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        sr = 16000
        audio = decode_audio(audio_path, sampling_rate=sr)
        total = len(audio) / sr
        try:
            spans = get_speech_timestamps(
                audio,
                VadOptions(
                    threshold=vad_threshold,
                    min_speech_duration_ms=150,
                    min_silence_duration_ms=400,
                    speech_pad_ms=150,
                ),
                sampling_rate=sr,
            )
        except Exception:
            spans = []

        chunks: list[tuple[float, float]] = []
        if spans:
            for sp in spans:
                st, en = sp["start"] / sr, sp["end"] / sr
                if chunks and st - chunks[-1][1] < 0.35 and en - chunks[-1][0] <= max_chunk:
                    chunks[-1] = (chunks[-1][0], en)
                else:
                    chunks.append((st, en))
        else:
            step = 12.0
            chunks = [(t, min(total, t + step)) for t in np.arange(0, max(total, 0.1), step)]

        final: list[tuple[float, float]] = []
        for st, en in chunks:
            while en - st > max_chunk:
                final.append((st, st + max_chunk))
                st += max_chunk
            if en - st > 0.3:
                final.append((st, en))

        def gen() -> Iterator[Segment]:
            for st, en in final:
                piece = audio[int(st * sr):int(en * sr)]
                if len(piece) < sr * 0.2:
                    continue
                segs, _ = self._model.transcribe(
                    piece,
                    language=language or None,
                    beam_size=beam_size,
                    best_of=beam_size,
                    temperature=[0.0, 0.2, 0.4, 0.6],
                    condition_on_previous_text=False,
                    compression_ratio_threshold=2.4,
                    log_prob_threshold=-1.0,
                    no_speech_threshold=0.6,
                    repetition_penalty=1.05,
                    no_repeat_ngram_size=5,
                    word_timestamps=False,
                    vad_filter=False,
                )
                text = "".join((s.text or "") for s in segs).strip()
                if text:
                    self.metrics.add(self.count_tokens(text))
                    yield Segment(st, en, text)

        return gen(), SimpleNamespace(language=language or "ja", duration=total)
