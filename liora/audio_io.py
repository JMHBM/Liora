"""WAV helpers. Stable Audio 3 emits 44.1 kHz stereo."""

from __future__ import annotations

from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100


def to_stereo(audio: object) -> np.ndarray:
    """Normalize library return values to float32 shaped (samples, 2)."""
    if isinstance(audio, (tuple, list)):
        audio = audio[0]
    if hasattr(audio, "detach"):
        audio = audio.detach().float().cpu().numpy()
    array = np.asarray(audio, dtype=np.float32)
    if array.ndim == 3:
        # (batch, channels, samples) — keep the first take
        array = array[0]
    if array.ndim == 1:
        array = np.stack([array, array], axis=0)
    if array.shape[0] in (1, 2) and array.shape[0] < array.shape[-1]:
        array = np.transpose(array, (1, 0))
    if array.shape[1] == 1:
        array = np.repeat(array, 2, axis=1)
    return np.clip(array[:, :2], -1.0, 1.0)


def write_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sample_rate, subtype="PCM_16")


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    audio, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
    return audio, int(sample_rate)
