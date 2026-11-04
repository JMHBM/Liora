"""`python -m liora` — doctor, download, generate, serve."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from liora import __version__
from liora.audio_io import write_wav
from liora.devices import detect, format_report
from liora.engine import EngineNotReady, GenerateRequest, StableAudioEngine
from liora.presets import load_presets

REPOS = {
    "small-music": "stabilityai/stable-audio-3-small-music",
    "medium": "stabilityai/stable-audio-3-medium",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="liora", description="Offline instrumental generator on Stable Audio 3")
    parser.add_argument("--version", action="version", version=f"liora {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Show GPU, VRAM, and the model you should load")

    download = sub.add_parser("download", help="Fetch gated weights after you accept the license")
    download.add_argument("--model", default="small-music", choices=sorted(REPOS))

    presets = sub.add_parser("presets", help="List the starter preset pack")
    presets.add_argument("--category", default="")

    generate = sub.add_parser("generate", help="Write a WAV")
    generate.add_argument("-p", "--prompt", required=True)
    generate.add_argument("-o", "--output", type=Path, default=Path("liora-take.wav"))
    generate.add_argument("--negative", default="vocals, singing, speech, lyrics, words, low quality")
    generate.add_argument("--duration", type=float, default=30)
    generate.add_argument("--model", default="auto", choices=["auto", "small-music", "medium"])
    generate.add_argument("--steps", type=int, default=8)
    generate.add_argument("--cfg", type=float, default=1.0)
    generate.add_argument("--seed", type=int, default=-1)
    generate.add_argument("--no-chunked", action="store_true")
    generate.add_argument("--init-audio", type=Path)
    generate.add_argument("--init-noise", type=float, default=0.7)
    generate.add_argument("--inpaint-audio", type=Path)
    generate.add_argument("--inpaint-start", type=float)
    generate.add_argument("--inpaint-end", type=float)
    generate.add_argument("--lora", type=Path)
    generate.add_argument("--lora-strength", type=float, default=1.0)
    generate.add_argument("--device", default=None)
    generate.add_argument("--preset", default="", help="Preset id; fills any flag you did not change")

    serve = sub.add_parser("serve", help="Local studio at http://127.0.0.1:8765")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)
    if args.cmd == "doctor":
        print(format_report(detect()))
        return 0
    if args.cmd == "presets":
        rows = load_presets()
        if args.category:
            rows = [row for row in rows if str(row.get("category", "")).lower() == args.category.lower()]
        print(json.dumps(rows, indent=2))
        return 0
    if args.cmd == "download":
        return _download(args.model)
    if args.cmd == "generate":
        return _generate(args)
    if args.cmd == "serve":
        from liora.server import serve as serve_app

        serve_app(args.host, args.port)
        return 0
    parser.error(f"unknown command {args.cmd}")
    return 2


def _download(model: str) -> int:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Install huggingface-hub first. See README.")
        return 1
    repo = REPOS[model]
    print(f"Downloading {repo}")
    print("The repo is gated. Accept the Community License (and Gemma terms for T5Gemma) and `huggingface-cli login`.")
    path = snapshot_download(repo)
    print(path)
    return 0


def _generate(args: argparse.Namespace) -> int:
    report = detect()
    model = report.recommended_model if args.model == "auto" else args.model
    prompt = args.prompt
    duration = args.duration
    negative = args.negative
    cfg = args.cfg
    steps = args.steps
    if args.preset:
        match = next((row for row in load_presets() if row.get("id") == args.preset), None)
        if match is None:
            print(f"No preset {args.preset}")
            return 2
        prompt = match.get("prompt", prompt)
        duration = float(match.get("duration", duration))
        negative = match.get("negative", negative)
        cfg = float(match.get("cfg", cfg))
        steps = int(match.get("steps", steps))
        if args.model == "auto":
            model = str(match.get("model", model))
    if model == "medium" and not args.no_chunked:
        chunked = True
    else:
        chunked = not args.no_chunked
    request = GenerateRequest(
        prompt=prompt,
        negative_prompt=negative,
        duration=duration,
        steps=steps,
        cfg_scale=cfg,
        seed=args.seed,
        model=model,
        chunked_decode=chunked,
        init_audio=args.init_audio,
        init_noise_level=args.init_noise,
        inpaint_audio=args.inpaint_audio,
        inpaint_start=args.inpaint_start,
        inpaint_end=args.inpaint_end,
        lora_path=args.lora,
        lora_strength=args.lora_strength,
        device=args.device,
    )
    engine = StableAudioEngine()
    try:
        result = engine.generate(request)
    except EngineNotReady as exc:
        print(exc)
        return 1
    write_wav(args.output, result.audio, result.sample_rate)
    for note in result.warnings:
        print(f"note: {note}")
    print(f"wrote {args.output} ({result.model}, {result.sample_rate} Hz)")
    return 0
