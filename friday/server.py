"""
server.py — HTTP server: serves the built UI and exposes the JSON API.

Routes
------
GET  /                   → static/index.html
GET  /index.html         → static/index.html
GET  /assets/<file>      → static/assets/<file>          (Vite-bundled JS/CSS)
GET  /transcripts.json   → SERVER_OUTPUT_JSON (compat polling endpoint)
GET  /events             → Server-Sent Events stream of state updates
GET  /mute-status        → {"muted": bool}
POST /toggle-mute        → flips muted.flag
POST /send-prompt        → runs the pipeline on a worker thread
"""

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import SERVER_PORT, SERVER_OUTPUT_JSON
from . import transcribe
from . import pipeline

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

_CONTENT_TYPES = {
    ".html": "text/html",
    ".js":   "application/javascript",
    ".css":  "text/css",
    ".svg":  "image/svg+xml",
    ".json": "application/json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


# ---------------------------------------------------------------------------
# SSE broadcast: when state file changes, push to all connected clients
# ---------------------------------------------------------------------------

_sse_subscribers: list["queue.SimpleQueue"] = []
_sse_lock = threading.Lock()

import queue  # noqa: E402  (needed by SSE)


def broadcast_state() -> None:
    """Read the current state file and push it to every SSE subscriber."""
    try:
        data = Path(SERVER_OUTPUT_JSON).read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    with _sse_lock:
        dead: list = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


def _sse_subscribe() -> "queue.SimpleQueue":
    q: queue.SimpleQueue = queue.SimpleQueue()
    with _sse_lock:
        _sse_subscribers.append(q)
    return q


def _sse_unsubscribe(q: "queue.SimpleQueue") -> None:
    with _sse_lock:
        if q in _sse_subscribers:
            _sse_subscribers.remove(q)


# Register pipeline state-change hook so writes propagate to SSE clients.
pipeline.add_state_listener(broadcast_state)  # type: ignore[attr-defined]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        return  # silence default access log

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._serve_path(STATIC_DIR / "index.html", "text/html")

        elif path.startswith("/assets/"):
            asset = (STATIC_DIR / "assets" / Path(path).name).resolve()
            if STATIC_DIR / "assets" not in asset.parents:
                self._respond(404, "text/plain", b"Not found")
                return
            self._serve_path(asset, _CONTENT_TYPES.get(asset.suffix, "application/octet-stream"))

        elif path == "/transcripts.json":
            self._serve_path(Path(SERVER_OUTPUT_JSON), "application/json")

        elif path == "/events":
            self._serve_sse()

        elif path == "/mute-status":
            body = json.dumps({"muted": transcribe.is_muted()}).encode()
            self._respond(200, "application/json", body)

        else:
            self._respond(404, "text/plain", b"Not found")

    def do_POST(self):
        if self.path == "/toggle-mute":
            transcribe.set_muted(not transcribe.is_muted())
            pipeline.write_json()
            body = json.dumps({"muted": transcribe.is_muted()}).encode()
            self._respond(200, "application/json", body)

        elif self.path == "/send-prompt":
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._respond(400, "application/json", b'{"error": "invalid json"}')
                return

            prompt_text = (data.get("prompt") or "").strip()
            if not prompt_text:
                self._respond(400, "application/json", b'{"error": "empty prompt"}')
                return

            log.info("Prompt from UI: %s", prompt_text)
            pipeline.on_transcript(prompt_text)
            self._respond(200, "application/json", b'{"success": true}')

        else:
            self._respond(404, "text/plain", b"Not found")

    # ── SSE handler ────────────────────────────────────────────────────────

    def _serve_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")  # nginx hint
        self.end_headers()

        q = _sse_subscribe()
        try:
            # Send current state immediately so the client doesn't wait
            try:
                initial = Path(SERVER_OUTPUT_JSON).read_text(encoding="utf-8")
                self._sse_send(initial)
            except FileNotFoundError:
                pass

            last_keepalive = time.time()
            while True:
                try:
                    payload = q.get(timeout=1.0)
                    self._sse_send(payload)
                except queue.Empty:
                    if time.time() - last_keepalive > 15:
                        try:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            return
                        last_keepalive = time.time()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            _sse_unsubscribe(q)

    def _sse_send(self, payload: str) -> None:
        # Multi-line payloads need each line prefixed; transcripts.json is pretty-printed.
        try:
            for line in payload.splitlines():
                self.wfile.write(b"data: " + line.encode("utf-8") + b"\n")
            self.wfile.write(b"\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise

    # ── helpers ─────────────────────────────────────────────────────────────

    def _serve_path(self, path: Path, content_type: str):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self._respond(404, "text/plain", b"File not found")
            return
        self._respond(200, content_type, data)

    def _respond(self, code: int, content_type: str, body: bytes):
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected mid-response; not actionable.
            pass


def serve_forever(port: int = SERVER_PORT) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info("UI available at http://localhost:%d", port)
    server.serve_forever()
