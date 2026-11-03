"""ASMR 后处理：幻觉过滤、断句、时间轴校正。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .engine import Segment

SENT_END = "。！？!?….．"
COMMA = "、,，;；:："
_SPLIT_RE = re.compile(rf"(?<=[{re.escape(SENT_END + COMMA)}])")
_WORD_RE = re.compile(r"[0-9A-Za-z\u3040-\u30ff\u4e00-\u9fff]")

# 常见 Whisper 幻觉（日语 ASMR / 英语素材）
HALLUCINATION_PATTERNS = [
    r"ご視聴ありがとうございました",
    r"ご視聴いただきありがとうございます",
    r"チャンネル登録.*(お願い|よろしく)",
    r"高評価.*(お願い|よろしく)",
    r"字幕(制作|作成|は).*",
    r"次回もお楽しみに",
    r"最後までご視聴",
    r"ありがとうございました$",
    r"^thank you for watching",
    r"^thanks for watching",
    r"subtitles? by",
    r"amara\.org",
    r"please subscribe",
    r"like and subscribe",
    # 中文素材常见幻觉
    r"请不吝(点赞|订阅|转发)",
    r"(点赞|订阅|转发|打赏).{0,6}(支持|关注)",
    r"订阅.{0,4}(频道|栏目)",
    r"字幕(由|制作|提供|组)",
    r"谢谢(观看|收看|收听)",
    r"本(期|视频|节目).{0,8}(结束|到此)",
    r"我们下(期|次)再见",
    r"明镜与点点",
    r"www\.[a-z0-9\-\.]+\.[a-z]{2,}",
    r"https?://",
    r"^\(?music\)?$",
    r"^\[?music\]?$",
    r"^♪+$",
    r"^[\.\-,、。…\s]+$",
]
_HALLU_RE = [re.compile(p, re.IGNORECASE) for p in HALLUCINATION_PATTERNS]


@dataclass
class Line:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


_CJK_SPACE_RE = re.compile(r"(?<=[\u4e00-\u9fff\u3040-\u30ff])\s+(?=[\u4e00-\u9fff\u3040-\u30ff])")
# 中文识别偶尔混入的半角片假名 / 谚文碎片，属于无意义噪声
_NOISE_CHARS_RE = re.compile(r"[\uff61-\uff9f\uac00-\ud7af\u1100-\u11ff]+")
_QUOTE_TAIL = "」』”’）)】》"


def _norm(text: str, lang: str = "") -> str:
    text = text.replace("\u200b", "").replace("\ufeff", "")
    if str(lang).startswith("zh"):
        text = _NOISE_CHARS_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = _CJK_SPACE_RE.sub("", text)   # Whisper 偶尔在汉字之间塞空格
    return text.strip(" \t-–—")


def _fix_quotes(pieces: list[str]) -> list[str]:
    """把被切到下一行开头的右引号挪回上一行末尾。"""
    out: list[str] = []
    for p in pieces:
        if out and p and p[0] in _QUOTE_TAIL:
            k = 0
            while k < len(p) and p[k] in _QUOTE_TAIL:
                k += 1
            out[-1] += p[:k]
            p = p[k:]
            if not p:
                continue
        out.append(p)
    return out


def _is_noise(text: str) -> bool:
    if not text:
        return True
    if not _WORD_RE.search(text):
        return True
    return any(r.search(text) for r in _HALLU_RE)


def split_text(text: str, max_chars: int, lang: str) -> list[str]:
    """按标点优先、空格次之、硬切兜底的顺序切成不超过 max_chars 的片段。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    for chunk in _SPLIT_RE.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) <= max_chars:
            pieces.append(chunk)
            continue
        if lang.startswith("en"):
            words = chunk.split(" ")
            buf = ""
            for w in words:
                candidate = f"{buf} {w}".strip()
                if len(candidate) <= max_chars:
                    buf = candidate
                else:
                    if buf:
                        pieces.append(buf)
                    buf = w
            if buf:
                pieces.append(buf)
        else:
            for i in range(0, len(chunk), max_chars):
                pieces.append(chunk[i:i + max_chars])

    # 贪心合并过短的片段（不跨句末标点合并，避免把两句粘成一行）
    merged: list[str] = []
    sep = " " if lang.startswith("en") else ""
    for p in pieces:
        prev_ok = (
            merged
            and not merged[-1].endswith(tuple(SENT_END))
            and len(merged[-1]) + len(p) <= max_chars
            and len(merged[-1]) < max_chars * 0.4
        )
        if prev_ok:
            merged[-1] = merged[-1] + sep + p
        else:
            merged.append(p)
    return _fix_quotes([m for m in merged if m])


def _words_len(words: list[tuple[float, float, str]], sep: str) -> int:
    return sum(len(w[2]) + (1 if sep else 0) for w in words)


def _find_break(words: list[tuple[float, float, str]], ratio: float = 0.45) -> int:
    """在缓冲里回退找最近的标点位置，避免把词从中间切开。"""
    floor = max(1, int(len(words) * ratio))
    for i in range(len(words) - 1, floor - 1, -1):
        if words[i][2].endswith(tuple(SENT_END + COMMA)):
            return i + 1
    return 0


def _group_words(
    words: list[tuple[float, float, str]], max_chars: int, lang: str
) -> list[Line]:
    """用词级时间戳拼行：行首/行尾直接取首末词的真实时间。"""
    sep = " " if lang.startswith("en") else ""
    lines: list[Line] = []
    cur: list[tuple[float, float, str]] = []
    length = 0

    def emit(items: list[tuple[float, float, str]]) -> None:
        if not items:
            return
        text = sep.join(w[2] for w in items).strip()
        if text:
            lines.append(Line(items[0][0], items[-1][1], text))

    for st, en, raw in words:
        bare = (raw or "").strip()
        if not bare:
            continue
        if cur and st - cur[-1][1] > 0.9:  # 明显停顿处断行
            emit(cur)
            cur, length = [], 0
        add = len(bare) + (1 if sep else 0)
        if cur and length + add > max_chars:
            cut = _find_break(cur)
            if cut:
                emit(cur[:cut])
                cur = cur[cut:]
                length = _words_len(cur, sep)
            elif length <= max_chars * 1.35:
                pass  # 附近没有标点，容许略微超长，等下一个标点再断，避免切碎词语
            else:
                emit(cur)
                cur, length = [], 0
        cur.append((st, en, bare))
        length += add
        if bare.endswith(tuple(SENT_END)) and length >= max_chars * 0.55:
            emit(cur)
            cur, length = [], 0
    emit(cur)
    return lines


def _allocate(start: float, end: float, pieces: list[str]) -> list[tuple[float, float]]:
    total = max(0.05, end - start)
    weights = [max(1, len(p)) for p in pieces]
    weight_sum = sum(weights)
    out: list[tuple[float, float]] = []
    cursor = start
    for i, w in enumerate(weights):
        dur = total * w / weight_sum
        seg_end = end if i == len(weights) - 1 else cursor + dur
        out.append((cursor, seg_end))
        cursor = seg_end
    return out


def _allocate_with_spans(
    start: float, end: float, pieces: list[str], spans: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """把文本按字数铺在真实语音区间上：行首自动落在开口处，静音不占时间。"""
    inter = [(max(s, start), min(e, end)) for s, e in spans if min(e, end) - max(s, start) > 0.05]
    if not inter:
        return _allocate(start, end, pieces)
    total_speech = sum(e - s for s, e in inter)
    if total_speech <= 0:
        return _allocate(start, end, pieces)
    total_chars = max(1, sum(len(p) for p in pieces))

    def t_at(frac: float) -> float:
        target = max(0.0, min(1.0, frac)) * total_speech
        acc = 0.0
        for s, e in inter:
            if acc + (e - s) >= target:
                return s + (target - acc)
            acc += e - s
        return inter[-1][1]

    out = []
    cursor = 0
    for p in pieces:
        s = t_at(cursor / total_chars)
        cursor += len(p)
        e = t_at(cursor / total_chars)
        out.append((s, max(s + 0.15, e)))
    return out


def _clean_words(words, lang: str):
    """词级时间戳也走同样的清洗，避免噪声字符从词路径回到正文。"""
    out = []
    for st, en, txt in words:
        t = _norm(txt, lang)
        if t:
            out.append((st, en, t))
    return out


def build_lines(
    segments: list[Segment],
    *,
    lang: str,
    max_chars: int = 28,
    max_line_sec: float = 8.0,
    merge_gap: float = 0.6,
    pre_roll: float = 0.15,
    offset: float = 0.0,
    blank_on_silence: bool = False,
    silence_gap: float = 5.0,
    speech_spans: list[tuple[float, float]] | None = None,
) -> list[Line]:
    # 1) 清洗 + 丢弃幻觉
    cleaned: list[Segment] = []
    for seg in segments:
        text = _norm(seg.text, lang)
        if _is_noise(text):
            continue
        if seg.no_speech_prob > 0.9 and seg.avg_logprob < -0.9:
            continue
        if len(text) <= 2 and (seg.end - seg.start) < 0.45:
            continue
        # 连续重复去重
        if len(cleaned) >= 2 and cleaned[-1].text == text and cleaned[-2].text == text:
            continue
        cleaned.append(Segment(seg.start, seg.end, text, seg.avg_logprob,
                               seg.no_speech_prob,
                               words=_clean_words(seg.words, lang) if seg.words else None))

    # 2) 合并相邻短句
    merged: list[Segment] = []
    for seg in cleaned:
        if merged:
            prev = merged[-1]
            gap = seg.start - prev.end
            sep = " " if lang.startswith("en") else ""
            combined = f"{prev.text}{sep}{seg.text}"
            if (
                not prev.words
                and not seg.words
                and gap <= merge_gap
                and len(combined) <= max_chars
                and (seg.end - prev.start) <= max_line_sec * 1.25
            ):
                prev.text = combined
                prev.end = seg.end
                continue
        merged.append(Segment(seg.start, seg.end, seg.text, seg.avg_logprob,
                              seg.no_speech_prob, words=seg.words))

    # 3) 断开过长片段 + 按字符占比分配时间
    lines: list[Line] = []
    word_segs = [s for s in merged if s.words]
    if word_segs:
        all_words = [w for s in word_segs for w in s.words]
        lines.extend(_group_words(all_words, max_chars, lang))
    for seg in (s for s in merged if not s.words):
        need_split = len(seg.text) > max_chars or (seg.end - seg.start) > max_line_sec
        pieces = split_text(seg.text, max_chars, lang) if need_split else [seg.text]
        if len(pieces) > 1:
            times = (
                _allocate_with_spans(seg.start, seg.end, pieces, speech_spans)
                if speech_spans
                else _allocate(seg.start, seg.end, pieces)
            )
        else:
            times = [(seg.start, seg.end)]
        for text, (s, e) in zip(pieces, times):
            lines.append(Line(s, e, text))

    # 4) 时间轴：偏移、预提前、单调递增
    prev_start = -999.0
    for ln in lines:
        ln.start = max(0.0, ln.start + offset - pre_roll)
        ln.end = max(ln.start + 0.2, ln.end + offset)
        if ln.start < prev_start + 0.25:
            delta = prev_start + 0.25 - ln.start
            ln.start += delta
            ln.end = max(ln.end, ln.start + 0.2)
        prev_start = ln.start
        ln.start = round(ln.start, 2)
        ln.end = round(ln.end, 2)

    # 5) 可选：长静音插空行
    if blank_on_silence and lines:
        out: list[Line] = []
        prev_end = 0.0
        for ln in lines:
            if ln.start - prev_end >= silence_gap:
                out.append(Line(round(prev_end + 0.05, 2), round(prev_end + 0.05, 2), ""))
            out.append(ln)
            prev_end = ln.end
        lines = out
    return lines


def stats(lines: list[Line]) -> dict[str, float]:
    if not lines:
        return {"lines": 0, "chars": 0, "avg_len": 0.0}
    chars = sum(len(ln.text) for ln in lines)
    return {"lines": len(lines), "chars": chars, "avg_len": chars / max(1, len(lines))}
