"""Tiny local studio. Binds to localhost only — the models never leave the machine."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from liora.audio_io import SAMPLE_RATE, write_wav
from liora.devices import detect
from liora.engine import EngineNotReady, GenerateRequest, StableAudioEngine
from liora.presets import load_presets

WEB = Path(__file__).resolve().parent / "web" / "studio.html"
OUT = Path.home() / ".liora" / "takes"

_engine = StableAudioEngine()
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Liora studio  http://{host}:{port}")
    print("Offline after the weights are cached. Ctrl+C stops the server.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: object) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._send(200, WEB.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self._json(200, detect().to_dict())
            return
        if path == "/api/presets":
            self._json(200, load_presets())
            return
        if path.startswith("/api/jobs/"):
            rest = path[len("/api/jobs/") :]
            audio = rest.endswith("/audio")
            job_id = rest[: -len("/audio")] if audio else rest
            with _jobs_lock:
                job = _jobs.get(job_id)
            if job is None:
                self._json(404, {"error": "unknown job"})
                return
            if audio:
                if job.get("status") != "done":
                    self._json(409, {"error": "not ready"})
                    return
                data = Path(job["path"]).read_bytes()
                self._send(200, data, "audio/wav")
                return
            public = {key: job[key] for key in ("id", "status", "stage", "error", "warnings", "model") if key in job}
            self._json(200, public)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/generate":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "bad json"})
            return
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "status": "queued", "stage": "Queued", "warnings": [], "model": payload.get("model", "auto")}
        with _jobs_lock:
            _jobs[job_id] = job
        threading.Thread(target=_run_job, args=(job, payload), daemon=True).start()
        self._json(202, {"id": job_id})


def _run_job(job: dict, payload: dict) -> None:
    report = detect()
    model = payload.get("model") or "auto"
    if model == "auto":
        model = report.recommended_model
    job["status"] = "running"
    job["stage"] = "Loading Stable Audio 3"
    request = GenerateRequest(
        prompt=str(payload.get("prompt") or ""),
        negative_prompt=str(payload.get("negative") or ""),
        duration=float(payload.get("duration") or 30),
        steps=int(payload.get("steps") or 8),
        cfg_scale=float(payload.get("cfg") or 1),
        seed=int(payload.get("seed") if payload.get("seed") is not None else -1),
        model=str(model),
        chunked_decode=bool(payload.get("chunked", True)),
        lora_path=Path(payload["lora"]) if payload.get("lora") else None,
        lora_strength=float(payload.get("loraStrength") or 1),
    )
    if not request.prompt.strip():
        job["status"] = "error"
        job["error"] = "Prompt is empty."
        return
    try:
        job["stage"] = "Sampling"
        result = _engine.generate(request)
        path = OUT / f"{job['id']}.wav"
        write_wav(path, result.audio, result.sample_rate or SAMPLE_RATE)
        job["path"] = str(path)
        job["model"] = result.model
        job["warnings"] = result.warnings
        job["stage"] = "Done"
        job["status"] = "done"
    except EngineNotReady as exc:
        job["status"] = "error"
        job["error"] = str(exc)
    except Exception as exc:  # surface the runtime error in the studio, don't die
        job["status"] = "error"
        job["error"] = f"{exc.__class__.__name__}: {exc}"
