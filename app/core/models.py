"""本地模型清单与下载。"""
from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import MODELS_DIR


@dataclass(frozen=True)
class ModelSpec:
    key: str
    repo: str
    label: str
    lang: str
    size_gb: float
    note: str = ""
    broken_timestamps: bool = False
    word_timestamps: bool = False

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.key


MODEL_SPECS: dict[str, ModelSpec] = {
    "anime-whisper-ct2-fp16": ModelSpec(
        key="anime-whisper-ct2-fp16",
        repo="quantumcookie/anime-whisper-ct2-fp16",
        label="Anime-Whisper（日语 ASMR 推荐）",
        lang="ja",
        size_gb=1.5,
        note="动漫/游戏语音微调，断句自然、带标点；VAD 分段补偿时间轴",
        broken_timestamps=True,
    ),
    "kotoba-whisper-v2.0-faster": ModelSpec(
        key="kotoba-whisper-v2.0-faster",
        repo="kotoba-tech/kotoba-whisper-v2.0-faster",
        label="Kotoba-Whisper v2.0（日语快速）",
        lang="ja",
        size_gb=1.5,
        note="官方 CT2，速度最快（约 3 倍于 anime-whisper），但输出无标点、断句偏长",
    ),
    "faster-whisper-large-v3-turbo-ct2": ModelSpec(
        key="faster-whisper-large-v3-turbo-ct2",
        repo="deepdml/faster-whisper-large-v3-turbo-ct2",
        label="Whisper large-v3-turbo（英语推荐）",
        lang="en",
        size_gb=1.6,
        note="英语轻声/耳语表现稳定，速度快；支持词级时间戳",
        word_timestamps=True,
    ),
    "belle-whisper-large-v3-zh-punct-ct2": ModelSpec(
        key="belle-whisper-large-v3-zh-punct-ct2",
        repo="k1nto/Belle-whisper-large-v3-zh-punct-ct2",
        label="Belle-Whisper v3 中文标点（中文推荐）",
        lang="zh",
        size_gb=2.9,
        note="中文语料微调，自带标点、默认简体；显存占用较高",
        word_timestamps=True,
    ),
    "belle-whisper-large-v3-turbo-zh-ct2-int8": ModelSpec(
        key="belle-whisper-large-v3-turbo-zh-ct2-int8",
        repo="wolfofbackstreet/faster-whisper-belle-whisper-large-v3-turbo-zh-ct2-int8",
        label="Belle-Whisper turbo 中文（快速/低显存）",
        lang="zh",
        size_gb=0.8,
        note="turbo 蒸馏版，速度快约 3 倍、显存减半；标点不如标点版稳",
        word_timestamps=True,
    ),
}

REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.json")

DEFAULT_KEYS = {
    "ja": "anime-whisper-ct2-fp16",
    "en": "faster-whisper-large-v3-turbo-ct2",
    "zh": "belle-whisper-large-v3-zh-punct-ct2",
}


def model_key_for(settings, language: str | None) -> str:
    """语言 → 模型 key。auto 走多语种 turbo（英语槽位）。"""
    lang = "ja" if not language or language == "auto" else language
    attr = {"ja": "ja_model", "en": "en_model", "zh": "zh_model"}.get(lang, "en_model")
    return getattr(settings, attr, "") or DEFAULT_KEYS.get(lang, DEFAULT_KEYS["en"])


def installed(spec: ModelSpec) -> bool:
    return all((spec.path / f).exists() for f in REQUIRED_FILES)


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f}{unit}" if unit != "B" else f"{int(num)}B"
        num /= 1024
    return f"{num:.1f}GB"


def download(
    spec: ModelSpec,
    progress: Callable[[int, str], None] | None = None,
    stop_flag: threading.Event | None = None,
) -> Path:
    """下载模型到 models/<key>，返回目录。"""
    from huggingface_hub import snapshot_download

    target = spec.path
    target.mkdir(parents=True, exist_ok=True)
    expected = spec.size_gb * (1024 ** 3)

    stop_monitor = threading.Event()

    def monitor() -> None:
        while not stop_monitor.wait(1.0):
            done = dir_size(target)
            pct = min(99, int(done / expected * 100)) if expected else 0
            if progress:
                progress(pct, f"下载中 {human_size(done)} / 约 {spec.size_gb:.1f}GB")

    th = threading.Thread(target=monitor, daemon=True)
    th.start()
    try:
        snapshot_download(
            repo_id=spec.repo,
            local_dir=str(target),
            allow_patterns=[
                "*.json", "*.bin", "*.txt", "*.model", "*.safetensors",
            ],
            max_workers=4,
        )
    finally:
        stop_monitor.set()
    if progress:
        progress(100, f"完成 {human_size(dir_size(target))}")
    if not installed(spec):
        raise RuntimeError(f"模型文件不完整：{target}")
    return target


def import_local(spec: ModelSpec, src: Path, progress: Callable[[int, str], None] | None = None) -> Path:
    """把已有的 CT2 模型目录复制进 models/。"""
    src = Path(src)
    if not src.is_dir():
        raise ValueError("请选择模型文件夹")
    for f in REQUIRED_FILES:
        if not (src / f).exists():
            raise ValueError(f"文件夹缺少 {f}")
    dst = spec.path
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    if progress:
        progress(100, "导入完成")
    return dst
