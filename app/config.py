"""路径、环境变量与用户设置。

所有可变数据（模型 / 缓存 / 输出 / 日志）都固定在程序目录下的 D 盘路径，
不写 C 盘用户目录。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


def _app_root() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_ROOT = _app_root()
MODELS_DIR = APP_ROOT / "models"
CACHE_DIR = APP_ROOT / "cache"
OUTPUT_DIR = APP_ROOT / "output"
LOGS_DIR = APP_ROOT / "logs"
CONFIG_DIR = APP_ROOT / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
    ".mp4", ".mkv", ".mov", ".avi", ".webm",
}


def ensure_dirs() -> None:
    for p in (MODELS_DIR, CACHE_DIR, OUTPUT_DIR, LOGS_DIR, CONFIG_DIR):
        p.mkdir(parents=True, exist_ok=True)


def apply_env(settings: "Settings | None" = None) -> None:
    """把缓存与临时目录全部重定向到程序目录（必须在导入 hf / ctranslate2 之前调用）。"""
    ensure_dirs()
    hf_home = CACHE_DIR / "hf"
    for p in (hf_home, CACHE_DIR / "tmp", CACHE_DIR / "torch", CACHE_DIR / "pip"):
        p.mkdir(parents=True, exist_ok=True)

    endpoint = (settings.hf_endpoint if settings else "") or "https://hf-mirror.com"
    os.environ["HF_ENDPOINT"] = endpoint.rstrip("/")
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(hf_home / "hub")
    os.environ["MODELSCOPE_CACHE"] = str(CACHE_DIR / "modelscope")
    os.environ["TORCH_HOME"] = str(CACHE_DIR / "torch")
    os.environ["PIP_CACHE_DIR"] = str(CACHE_DIR / "pip")
    os.environ["TMP"] = str(CACHE_DIR / "tmp")
    os.environ["TEMP"] = str(CACHE_DIR / "tmp")
    # 国内镜像不支持 Xet 存储，禁用后走普通 HTTP 下载
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    # 让 CUDA 上下文按需加载，少占几十 MB 显存
    os.environ.setdefault("CUDA_MODULE_LOADING", "LAZY")
    os.environ.setdefault("OMP_NUM_THREADS", "4")


PRESETS: dict[str, dict[str, Any]] = {
    "ja_whisper": {
        "label": "日语耳语（推荐）",
        "language": "ja",
        "beam_size": 5,
        "vad": True,
        "vad_threshold": 0.25,
        "max_chars": 28,
        "max_line_sec": 8.0,
        "merge_gap": 0.6,
        "pre_roll": 0.15,
    },
    "en_soft": {
        "label": "英语轻声",
        "language": "en",
        "beam_size": 5,
        "vad": True,
        "vad_threshold": 0.30,
        "max_chars": 42,
        "max_line_sec": 8.0,
        "merge_gap": 0.6,
        "pre_roll": 0.15,
    },
    "zh_soft": {
        "label": "中文轻声（推荐）",
        "language": "zh",
        "beam_size": 5,
        "vad": True,
        "vad_threshold": 0.25,
        "max_chars": 18,
        "max_line_sec": 8.0,
        "merge_gap": 0.6,
        "pre_roll": 0.15,
    },
    "bgm_heavy": {
        "label": "BGM 较重（强过滤）",
        "language": "ja",
        "beam_size": 5,
        "vad": True,
        "vad_threshold": 0.35,
        "max_chars": 26,
        "max_line_sec": 7.0,
        "merge_gap": 0.5,
        "pre_roll": 0.18,
    },
    "custom": {"label": "自定义"},
}

ENCODINGS = ["utf-8", "utf-8-sig", "gbk", "shift_jis"]


@dataclass
class Settings:
    # 识别
    language: str = "ja"              # ja / en / zh / auto
    ja_model: str = "anime-whisper-ct2-fp16"
    en_model: str = "faster-whisper-large-v3-turbo-ct2"
    zh_model: str = "belle-whisper-large-v3-zh-punct-ct2"
    preset: str = "ja_whisper"
    beam_size: int = 5
    vad: bool = True
    vad_threshold: float = 0.25
    condition_on_previous: bool = False
    # 断句 / 时间轴
    max_chars: int = 28
    max_line_sec: float = 8.0
    merge_gap: float = 0.6
    pre_roll: float = 0.15
    offset: float = 0.0
    blank_on_silence: bool = False
    # 输出
    formats: list[str] = field(default_factory=lambda: ["lrc"])
    output_mode: str = "same"          # same / custom
    output_dir: str = ""
    keep_structure: bool = True
    encoding: str = "utf-8"
    overwrite: str = "skip"            # skip / overwrite / rename
    hour_timestamp: bool = False
    # 性能
    compute_mode: str = "auto"         # auto / float16 / int8_float16
    # 网络
    hf_endpoint: str = "https://hf-mirror.com"

    def save(self) -> None:
        ensure_dirs()
        SETTINGS_FILE.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_FILE.exists():
            try:
                raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
        else:
            raw = {}
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known}
        try:
            return cls(**data)
        except TypeError:
            return cls()

    def apply_preset(self, key: str) -> None:
        preset = PRESETS.get(key)
        if not preset or key == "custom":
            return
        self.preset = key
        for k, v in preset.items():
            if k != "label" and hasattr(self, k):
                setattr(self, k, v)
