"""
main.py — Orchestrator: STT → LLM (streaming) → TTS pipeline

Changes from v1:
  - Wake-word gating ("Hey Friday") in transcribe.py
  - Streaming LLM: sentences are spoken as they're generated (low latency)
  - HTTP server (port 5000) for the UI to control mic mute + serve files
  - index.html served via this process so mic control works

Run:
    python main.py
Then open http://localhost:5000 in your browser.
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# Local modules
import transcribe
import llm
import tts

# ---------------------------------------------------------------------------
# Transcript persistence
# ---------------------------------------------------------------------------

OUTPUT_JSON: str = "transcripts.json"
_transcripts: list[dict] = []
_lock = threading.Lock()


def _write_json(*, is_processing: bool = False, is_thinking: bool = False,
                partial_ai: str = "") -> None:
    payload = {
        "transcripts": _transcripts,
        "processing": is_processing,
        "thinking": is_thinking,
        "partial_ai": partial_ai,
        "muted": transcribe.is_muted(),
        "updated": time.time(),
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Core pipeline callback
# ---------------------------------------------------------------------------

def _on_transcript(user_text: str) -> None:
    """
    Called by transcribe.py on a background thread when a complete
    utterance is ready.  Streams LLM reply sentence-by-sentence into TTS.
    """
    _write_json(is_thinking=True)
    print(f"[Main] → LLM: {user_text}")

    full_reply_parts = []
    partial = ""

    try:
        for sentence, is_last in llm.ask_stream_sentences(user_text):
            if not sentence:
                continue

            full_reply_parts.append(sentence)
            partial = " ".join(full_reply_parts)

            # Update UI with the partial reply as it builds up
            _write_json(is_thinking=not is_last, partial_ai=partial)

            print(f"[Main] ← LLM chunk: {sentence}")

            # Speak this sentence immediately — don't wait for the full reply
            tts.speak(sentence)

    except Exception as exc:
        print(f"[Main] Pipeline error: {exc}")

    full_reply = " ".join(full_reply_parts)
    print(f"[Main] ← LLM full: {full_reply}")

    with _lock:
        _transcripts.append({
            "user": user_text,
            "ai": full_reply,
            "time": time.strftime("%H:%M:%S"),
            "timestamp": time.time(),
        })
    _write_json()


# ---------------------------------------------------------------------------
# HTTP server — serves index.html, transcripts.json, and /toggle-mute
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass   # silence request logs

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._serve_file("index.html", "text/html")

        elif path == "/transcripts.json":
            self._serve_file("transcripts.json", "application/json")

        elif path == "/mute-status":
            body = json.dumps({"muted": transcribe.is_muted()}).encode()
            self._respond(200, "application/json", body)

        else:
            self._respond(404, "text/plain", b"Not found")

    def do_POST(self):
        if self.path == "/toggle-mute":
            currently_muted = transcribe.is_muted()
            transcribe.set_muted(not currently_muted)
            _write_json()
            body = json.dumps({"muted": transcribe.is_muted()}).encode()
            self._respond(200, "application/json", body)
        else:
            self._respond(404, "text/plain", b"Not found")

    def _serve_file(self, filename: str, content_type: str):
        try:
            with open(filename, "rb") as f:
                data = f.read()
            self._respond(200, content_type, data)
        except FileNotFoundError:
            self._respond(404, "text/plain", b"File not found")

    def _respond(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def _start_server(port: int = 5000):
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"[Server] UI available at http://localhost:{port}")
    server.serve_forever()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  Friday Voice Assistant")
    print("  STT (Whisper)  →  LLM (Gemma / LM Studio)  →  TTS (Kokoro)")
    print("=" * 60)

    # Clear mute flag on fresh start
    transcribe.set_muted(False)

    _write_json()

    transcribe.load_model()

    # Start the HTTP server on a background thread
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    # Start the STT loop (blocks until Ctrl-C)
    transcribe.start(on_transcript=_on_transcript)

    print("[Main] Session ended.")


if __name__ == "__main__":
    main()