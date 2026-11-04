"""Stable Audio 3 inference wrapper.

Pipeline (official `stable_audio_3.StableAudioModel.generate`):

1. Text prompt and negative prompt go through the frozen T5Gemma encoder.
2. Duration picks a variable-length latent. SAME downsamples 44.1 kHz stereo
   by 4096× into 256-d latents, so a 10 s clip is about 108 frames, not a
   fixed window.
3. The diffusion transformer samples that latent. Post-trained checkpoints
   are the adversarial 8-step models — extra steps past 8 rarely help.
   Base checkpoints (LoRA training) want something closer to 50.
4. The SAME decoder reconstructs stereo audio. `chunked_decode=True`
   (the library default) overlaps decoder chunks so Medium at 120 s drops
   from ~6.5 GB toward ~5.1 GB. Leave it on for an 8 GB card.
5. Optional init audio / inpaint masks edit or continue an existing take.
   LoRA weights, if any, were already fused via `load_lora`.

This module does not reimplement the DiT. It only guards VRAM, devices,
and the kwargs the installed library actually accepts.
"""

from __future__ import annotations

import inspect
import threading
from dataclasses import dataclass, field
from pathlib import Path

from liora.audio_io import SAMPLE_RATE, read_wav, to_stereo
from liora.devices import detect


@dataclass
class GenerateRequest:
    prompt: str
    negative_prompt: str = "vocals, singing, speech, lyrics, words, voiceover, low quality"
    duration: float = 30
    steps: int = 8
    cfg_scale: float = 1.0
    seed: int = -1
    model: str = "small-music"
    chunked_decode: bool = True
    batch_size: int = 1
    init_audio: Path | None = None
    init_noise_level: float = 0.7
    inpaint_audio: Path | None = None
    inpaint_start: float | None = None
    inpaint_end: float | None = None
    lora_path: Path | None = None
    lora_strength: float = 1.0
    device: str | None = None
    dtype: str = "float16"


@dataclass
class GenerateResult:
    audio: object
    sample_rate: int = SAMPLE_RATE
    model: str = "small-music"
    warnings: list[str] = field(default_factory=list)


class EngineNotReady(RuntimeError):
    pass


class StableAudioEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None
        self._model_id: str | None = None
        self._lora: str | None = None

    def _import_model_cls(self):
        try:
            from stable_audio_3 import StableAudioModel
        except ImportError as exc:
            raise EngineNotReady(
                "stable-audio-3 is not installed. Follow README: install the matching "
                "PyTorch build first, then `pip install git+https://github.com/Stability-AI/stable-audio-3.git`. "
                "Run `python -m liora doctor` to see this machine."
            ) from exc
        return StableAudioModel

    def _device_arg(self, requested: str | None) -> str | None:
        if requested:
            return requested
        report = detect()
        if report.backend in {"cuda", "rocm", "zluda"}:
            return "cuda"
        if report.backend == "mps":
            return "mps"
        return "cpu"

    def load(self, model_id: str, device: str | None = None, dtype: str = "float16"):
        StableAudioModel = self._import_model_cls()
        device_arg = self._device_arg(device)
        kwargs = {}
        signature = inspect.signature(StableAudioModel.from_pretrained)
        if "device" in signature.parameters and device_arg:
            kwargs["device"] = device_arg
        if "dtype" in signature.parameters and dtype:
            kwargs["dtype"] = dtype
        model = StableAudioModel.from_pretrained(model_id, **kwargs)
        self._model = model
        self._model_id = model_id
        self._lora = None
        return model

    def _apply_lora(self, path: Path | None, strength: float) -> None:
        if path is None or self._model is None:
            return
        key = f"{path}:{strength}"
        if key == self._lora:
            return
        if not path.exists():
            raise EngineNotReady(f"LoRA file not found: {path}")
        self._model.load_lora([str(path)])
        if hasattr(self._model, "set_lora_strength"):
            self._model.set_lora_strength(strength)
        self._lora = key

    def _call(self, request: GenerateRequest):
        assert self._model is not None
        signature = inspect.signature(self._model.generate)
        kwargs: dict = {
            "prompt": request.prompt,
            "duration": request.duration,
        }
        optional = {
            "negative_prompt": request.negative_prompt,
            "steps": request.steps,
            "cfg_scale": request.cfg_scale,
            "seed": request.seed,
            "batch_size": max(1, request.batch_size),
            "chunked_decode": request.chunked_decode,
            "init_noise_level": request.init_noise_level,
        }
        if request.init_audio is not None:
            optional["init_audio"] = _load_audio_arg(request.init_audio)
        if request.inpaint_audio is not None and request.inpaint_start is not None and request.inpaint_end is not None:
            optional["inpaint_audio"] = _load_audio_arg(request.inpaint_audio)
            optional["inpaint_mask_start_seconds"] = request.inpaint_start
            optional["inpaint_mask_end_seconds"] = request.inpaint_end
        for name, value in optional.items():
            if name in signature.parameters and value is not None:
                kwargs[name] = value
        return self._model.generate(**kwargs)

    def generate(self, request: GenerateRequest) -> GenerateResult:
        """Generate one stereo take. Medium OOM falls back to Small-Music."""
        warnings: list[str] = []
        report = detect()
        model_id = request.model
        if model_id == "medium" and not report.allow_medium:
            warnings.append(report.warnings[0] if report.warnings else "Medium is not available here.")
            model_id = "small-music"
        if model_id == "small-music":
            request.duration = min(float(request.duration), 120.0)
        else:
            request.duration = min(float(request.duration), 380.0)
        if model_id == "medium":
            request.chunked_decode = True
            request.batch_size = 1
            warnings.append("Chunked decode forced on for Medium.")

        with self._lock:
            if self._model is None or self._model_id != model_id:
                self.load(model_id, device=request.device, dtype=request.dtype)
            self._apply_lora(request.lora_path, request.lora_strength)
            try:
                raw = self._call(request)
            except RuntimeError as exc:
                if model_id != "medium" or not _is_oom(exc):
                    raise
                _empty_cache()
                warnings.append("Medium ran out of VRAM. Reloading Small-Music and rendering up to 120 s.")
                self._model = None
                request.duration = min(request.duration, 120.0)
                request.model = "small-music"
                self.load("small-music", device=request.device, dtype="float32")
                raw = self._call(request)
                model_id = "small-music"
        return GenerateResult(audio=to_stereo(raw), sample_rate=SAMPLE_RATE, model=model_id, warnings=warnings)


def _load_audio_arg(path: Path):
    """Return (sample_rate, tensor) the way the official examples do."""
    import torch
    import torchaudio

    try:
        waveform, sample_rate = torchaudio.load(str(path))
        return sample_rate, waveform
    except Exception:
        samples, sample_rate = read_wav(path)
        tensor = torch.from_numpy(samples.T.copy())
        return sample_rate, tensor


def _is_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda" in text and "memory" in text


def _empty_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return
