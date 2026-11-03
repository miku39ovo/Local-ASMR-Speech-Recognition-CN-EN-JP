"""命令行批量入口：python -m app.cli <文件或目录…> --lang ja --formats lrc,txt"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import AUDIO_EXTS, Settings, apply_env


def scan(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out += [f for f in sorted(p.rglob("*")) if f.suffix.lower() in AUDIO_EXTS]
        elif p.suffix.lower() in AUDIO_EXTS:
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ASMR2LRC 批量转写")
    ap.add_argument("inputs", nargs="+", help="音频文件或文件夹")
    ap.add_argument("--lang", default="ja", choices=["ja", "en", "zh", "auto"])
    ap.add_argument("--formats", default="lrc", help="逗号分隔：lrc,txt,srt")
    ap.add_argument("--out", default="", help="输出目录，留空则与音频同目录")
    ap.add_argument("--chars", type=int, default=0, help="每行最多字数，0 表示按语言默认")
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--compute", default="auto", choices=["auto", "float16", "int8_float16"])
    ap.add_argument("--model-ja", default="")
    ap.add_argument("--model-en", default="")
    ap.add_argument("--model-zh", default="")
    args = ap.parse_args(argv)

    s = Settings.load()
    apply_env(s)

    from .core.cuda_dlls import setup as setup_cuda

    setup_cuda()

    from .core.engine import AsrEngine
    from .core.pipeline import Job, process_file

    s.language = args.lang
    s.formats = [x.strip() for x in args.formats.split(",") if x.strip()]
    if args.chars > 0:
        s.max_chars = args.chars
    s.offset = args.offset
    s.compute_mode = args.compute
    if args.model_ja:
        s.ja_model = args.model_ja
    if args.model_en:
        s.en_model = args.model_en
    if args.model_zh:
        s.zh_model = args.model_zh
    if args.out:
        s.output_mode = "custom"
        s.output_dir = args.out

    files = scan(args.inputs)
    if not files:
        print("没有找到音视频文件")
        return 1

    engine = AsrEngine()
    ok = fail = 0
    try:
        for i, f in enumerate(files, 1):
            print(f"[{i}/{len(files)}] {f.name}", flush=True)
            job = Job(path=f)
            try:
                res = process_file(
                    job, s, engine,
                    progress=lambda p, m: print(f"    {p:3d}% {m}", flush=True),
                )
                print(f"    -> {res.status} {res.message}", flush=True)
                ok += res.status in ("done", "skipped")
                fail += res.status not in ("done", "skipped")
            except Exception as exc:  # noqa: BLE001
                fail += 1
                print(f"    !! {exc}", flush=True)
    finally:
        engine.release()
    print(f"完成：成功 {ok}，失败 {fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
