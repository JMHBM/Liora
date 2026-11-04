"""Environment detection for the RX 6600M and everyone else.

Backend preference, matching what actually runs Stable Audio 3 today:
  1. ROCm (Linux, torch.version.hip)
  2. CUDA, including ZLUDA's CUDA translation on Windows RDNA2
  3. CPU — Small-Music is designed for it

DirectML / ONNX are not wired up. The official loader speaks CUDA, MPS, and CPU.
Pretending DirectML can host SAME-L would fail at the first attention kernel.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class DeviceReport:
    backend: str
    device_name: str
    vram_gb: float | None
    flash_attn: bool
    torch_version: str | None
    hip_version: str | None
    recommended_model: str
    allow_medium: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def recommend(vram_gb: float | None, backend: str, flash_attn: bool) -> tuple[str, bool, list[str]]:
    """Return (model id, allow_medium, warnings).

    Official peaks (H200, not this GPU): Small 120s ≈ 2.4 GB, Medium 120s
    unchunked ≈ 6.49 GB, chunked ≈ 5.14 GB. An 8 GB card has headroom for
    Medium only when chunked decode stays on and nothing else is using VRAM.
    """
    notes: list[str] = []
    if backend == "cpu" or vram_gb is None:
        notes.append("No GPU runtime is visible. Small-Music is the supported CPU model.")
        return "small-music", False, notes
    if vram_gb < 6.5:
        notes.append(f"{vram_gb:.1f} GB is below the Medium budget. Stay on Small-Music.")
        return "small-music", False, notes
    if not flash_attn:
        notes.append(
            "flash-attn is not importable. Medium's SAME-L decoder expects that style of "
            "attention, and ZLUDA / gfx1032 often cannot run those kernels. "
            "You can still pass --model medium; Liora unloads and retries Small-Music on OOM."
        )
        return "small-music", True, notes
    if vram_gb <= 9:
        notes.append(
            "8 GB class GPU: force chunked decode, batch size 1, and fp16. "
            "Close browsers before a long Medium render."
        )
        return "medium", True, notes
    return "medium", True, notes


def detect() -> DeviceReport:
    backend = "cpu"
    name = "CPU"
    vram = None
    torch_version = None
    hip = None
    flash = False
    try:
        import torch

        torch_version = getattr(torch, "__version__", None)
        hip = getattr(getattr(torch, "version", None), "hip", None)
        if torch.cuda.is_available():
            index = torch.cuda.current_device()
            name = torch.cuda.get_device_name(index)
            props = torch.cuda.get_device_properties(index)
            vram = getattr(props, "total_memory", 0) / (1024**3)
            backend = "rocm" if hip else "cuda"
            # ZLUDA reports a CUDA device whose name is the AMD GPU.
            if hip is None and any(token in name.lower() for token in ("radeon", "amd", "gfx")):
                backend = "zluda"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            backend = "mps"
            name = "Apple MPS"
    except Exception as exc:  # torch missing or a broken ROCm build
        name = f"CPU (torch not usable: {exc.__class__.__name__})"

    try:
        import flash_attn  # type: ignore  # noqa: F401

        flash = True
    except Exception:
        flash = False

    model, allow, notes = recommend(vram, backend, flash)
    if backend == "zluda":
        notes.append(
            "ZLUDA is intercepting CUDA. Launch Python through `zluda` so nvcuda.dll is the translation layer, not NVIDIA's."
        )
    if backend == "rocm":
        notes.append("For gfx1032 set HSA_OVERRIDE_GFX_VERSION=10.3.0 before importing torch.")
    return DeviceReport(
        backend=backend,
        device_name=name,
        vram_gb=None if vram is None else round(vram, 2),
        flash_attn=flash,
        torch_version=torch_version,
        hip_version=str(hip) if hip else None,
        recommended_model=model,
        allow_medium=allow,
        warnings=notes,
    )


def format_report(report: DeviceReport) -> str:
    lines = [
        "Liora device report",
        f"  backend:     {report.backend}",
        f"  device:      {report.device_name}",
        f"  VRAM:        {report.vram_gb if report.vram_gb is not None else 'n/a'} GB",
        f"  torch:       {report.torch_version or 'not importable'}",
        f"  hip:         {report.hip_version or 'n/a'}",
        f"  flash-attn:  {'yes' if report.flash_attn else 'no'}",
        f"  recommend:   {report.recommended_model}",
        f"  medium ok:   {'attempt with chunking' if report.allow_medium else 'no'}",
    ]
    for note in report.warnings:
        lines.append(f"  - {note}")
    return "\n".join(lines)
