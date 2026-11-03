"""ASMR2LRC 启动入口。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import APP_ROOT, CACHE_DIR, LOGS_DIR, Settings, apply_env  # noqa: E402


def _selftest() -> int:
    """打包后自检：依次跑日语/中文/英语样本，结果写到 logs/selftest.txt。"""
    import json
    import wave

    from app.config import LOGS_DIR, MODELS_DIR
    from app.core.engine import AsrEngine
    from app.core.gpu import query_vram
    from app.core.models import model_key_for
    from app.core.pipeline import Job, process_file

    def _make_tone() -> Path:
        p = CACHE_DIR / "selftest.wav"
        p.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000 * 3)
        return p

    # 语言 -> (样本文件名, 预设)
    cases = [
        ("ja", "test_ja.mp3", "ja_whisper"),
        ("zh", "test_zh.mp3", "zh_soft"),
        ("en", "test_en.mp3", "en_soft"),
    ]
    if not any((APP_ROOT / "samples" / n).exists() for _, n, _ in cases):
        cases = [("ja", "", "ja_whisper")]

    engine = AsrEngine()
    settings = Settings.load()
    info: dict = {
        "vram": query_vram().summary,
        "models_dir": str(MODELS_DIR),
        "results": [],
    }
    ok = True
    try:
        for lang, name, preset in cases:
            sample = APP_ROOT / "samples" / name if name else _make_tone()
            settings.apply_preset(preset)
            settings.language = lang
            settings.formats = ["lrc"]
            settings.output_mode = "custom"
            settings.output_dir = str(LOGS_DIR)
            settings.overwrite = "overwrite"
            job = Job(path=sample, language=lang)
            item: dict = {"lang": lang, "sample": str(sample),
                          "model": model_key_for(settings, lang)}
            try:
                res = process_file(job, settings, engine,
                                   on_log=lambda m, i=item: i.setdefault("log", []).append(m))
                item.update(status=res.status, message=res.message, lines=len(res.lines))
                if res.lines:
                    item["preview"] = [ln.text for ln in res.lines[:3]]
            except Exception as exc:  # noqa: BLE001
                item.update(status="error", message=str(exc))
            info["results"].append(item)
            if item.get("status") != "done":
                ok = False
        info.update(compute=engine.compute_type, device=engine.device)
    finally:
        engine.release()

    (LOGS_DIR / "selftest.txt").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if ok else 1


def main() -> int:
    settings = Settings.load()
    apply_env(settings)

    from app.core.cuda_dlls import setup as setup_cuda

    setup_cuda()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "app.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if "--selftest" in sys.argv:
        return _selftest()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from app import __version__
    from app.ui.main_window import MainWindow
    from app.ui.theme import QSS

    logging.getLogger(__name__).info("ASMR2LRC %s 启动，程序目录 %s", __version__, APP_ROOT)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("ASMR2LRC")
    app.setStyleSheet(QSS)

    win = MainWindow(settings)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
