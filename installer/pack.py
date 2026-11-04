"""Append the Liora payload zip to LioraSetup.exe."""

import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
SKIP = {"__pycache__", ".venv", "dist"}


def main() -> None:
    payload = OUT.with_suffix(".payload.zip")
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP for part in path.parts):
                continue
            if path.suffix in {".pyc", ".exe"}:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("installer/setup") or rel.startswith("dist/"):
                continue
            archive.write(path, rel)
        archive.write(ROOT / "installer" / "Install-Liora.ps1", "Install-Liora.ps1")
    blob = payload.read_bytes()
    packed = EXE.read_bytes() + blob + struct.pack("<Q", len(blob)) + b"LIOROVLY"
    OUT.write_bytes(packed)
    payload.unlink()
    print(f"wrote {OUT} ({len(packed)} bytes, payload {len(blob)})")


if __name__ == "__main__":
    main()
