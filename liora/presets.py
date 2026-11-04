"""Editable preset pack. Same schema as the studio UI."""

from __future__ import annotations

import json
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent / "presets" / "presets.json"


def load_presets(path: Path | None = None) -> list[dict]:
    target = path or PACK
    if not target.exists():
        return []
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{target} must be a JSON array of presets")
    return data
