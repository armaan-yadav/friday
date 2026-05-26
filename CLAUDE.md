# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Friday** is a real-time voice assistant: microphone → STT (faster-whisper or Sarvam) with wake word → LM Studio LLM (streaming, optional web search) → TTS (Kokoro or Sarvam) with barge-in → React UI served from the same Python process.

The Python service is a single process that runs:

- an STT capture loop (PortAudio thread) feeding a queue,
- a transcription state machine on its own thread,
- a `ThreadingHTTPServer` on `SERVER_PORT` (default 5000),
- a single in-flight pipeline worker per turn (preempted on the next utterance).

The UI gets state via Server-Sent Events at `/events` (with `/transcripts.json` as a polling fallback) — there is no WebSocket.

## Commands

```bash
# Install Python deps (uv-managed, see pyproject.toml + uv.lock)
uv sync

# Run the assistant. Opens http://localhost:5000
uv run friday
# Equivalent: uv run python -m friday

# Print all loaded config from .env (debug)
uv run python -m friday.config

# UI development (proxies API + SSE to localhost:5000)
cd frontend && npm install && npm run dev   # http://localhost:5173 with HMR
cd frontend && npm run build                 # writes to ../static/
cd frontend && npm run lint                  # eslint
```

There is no Python test framework configured; no test files exist in the repo.

`.env` must exist before first import of `friday.config` or it raises `ValueError`. Copy `.env.example` to `.env`.

## Architecture

### Module pipeline

```
friday/transcribe.py  (mic → audio queue → wake-word + VAD state machine)
        │ stt.transcribe(audio)        ← provider abstraction (whisper | sarvam)
        │ on_transcript(user_text)
        ▼
friday/pipeline.py::on_transcript  (orchestrator on a worker thread)
        │ for sentence, is_last in llm.ask_stream_sentences(...):
        ▼
friday/llm.py  ── friday/search.py (per-turn, via tool-call OR heuristic)
        │ yields sentences
        ▼
friday/tts.py::speak_stream(sentences, cancel)   (synth-ahead + barge-in)
```

`friday/__main__.py` is the entry point: warms TTS + STT, starts `server.serve_forever` on a daemon thread, then calls `transcribe.start(on_transcript=pipeline.on_transcript)` on the main thread.

### Provider abstractions

- **`friday/stt.py`** is a thin provider layer (`load()`, `transcribe(audio, sample_rate, beam_size)`). `STT_PROVIDER` selects `"whisper"` (local faster-whisper) or `"sarvam"` (cloud). `transcribe.py` owns capture and never imports `faster_whisper` directly. To add a provider, branch in `stt.load()` and `stt.transcribe()` — don't touch `transcribe.py`.
- **`friday/tts.py`** likewise: `TTS_PROVIDER` selects `"kokoro"` (local) or `"sarvam"` (cloud). `speak_stream()` is provider-agnostic; the barge-in monitor is shared.
- **`friday/vad.py`** wraps silero-vad with an RMS fallback (`STT_VAD_PROVIDER`).
- **`friday/wake_word.py`** has two providers (`STT_WAKE_WORD_PROVIDER=text|openwakeword`). Text mode matches against `STT_WAKE_WORDS` after Whisper output; openWakeWord runs an ONNX model on every audio block while idle (cheap and faster).

### Cross-cutting patterns (non-obvious)

- **`friday.config` is the single source of truth.** All other modules import constants from there. Every config name is `STT_*`, `LLM_*`, `TTS_*`, `SERVER_*`, or `SEARCH_*` — use those exact names in new code. Values come from `.env` via `python-dotenv`. `_get_env(key, default, var_type)` raises `ValueError` if a required var has no default.
- **Mute is a file**, not a variable. `data/muted.flag` (path from `SERVER_MUTE_FLAG_PATH`) existing = muted. `transcribe.is_muted()` does `os.path.exists()`. `__main__.main()` calls `transcribe.set_muted(False)` on startup to clear stale state. `/toggle-mute` flips the file.
- **STT is a state machine**, not always-on transcription. `_transcription_loop` flips between idle and active. Idle requires a wake-word match; active stays on until `STT_CONVERSATION_TIMEOUT` of inactivity. With openWakeWord, idle-mode never accumulates audio — the wake fires on a single block, then `_collect_after_oww` collects the next utterance. With text-mode, Whisper transcribes every utterance and `_strip_wake_word` removes the trigger phrase.
- **Capture pause prevents self-echo.** `pipeline._run_pipeline` calls `transcribe.pause_capture()` before TTS and `resume_capture()` (which drains the queue) after. The barge-in monitor runs its _own_ short `sd.InputStream` during playback, so the user can still interrupt while the main mic is paused.
- **One in-flight turn at a time.** `pipeline.on_transcript` cancels the previous worker (sets `_current_cancel`, joins for ≤2s) before starting a new one. Cancellation propagates through `cancel: threading.Event` into `llm.ask_stream` (closes the `requests` connection) and `tts.speak_stream` (calls `sd.stop()`).
- **Streaming → sentence splitting is real-time-ish.** `llm.ask_stream_sentences` emits each sentence the instant a `[.!?]\s+` boundary is seen in the buffer (not after the full reply). The split regex still breaks on `Dr.` mid-sentence is fine (no whitespace), but `...` and abbreviations followed by space will mis-split — improve the splitter if it matters.
- **Search has two paths.** `LLM_TOOLS_ENABLED=true` exposes a `search_web` OpenAI-style tool that the model can invoke (up to 3 rounds); the result goes back as a `role: "tool"` message. With tools off, `search.needs_search(user_text)` heuristically prepends search context to the system prompt for that turn only. Search results are **never** added to `_chat_history`.
- **TTS is pipelined.** `speak_stream` runs a producer thread that synthesizes the next fragment while the current one plays (bounded queue, `maxsize=8`). Barge-in sets a module-level `interrupted` event AND the caller's `cancel`, so the LLM stream stops too.
- **UI state is `data/transcripts.json` on disk.** `pipeline.write_json()` rewrites the whole file on every state change (thinking, partial_ai, new transcript, mute toggle) and fires registered listeners. `server.broadcast_state` is one such listener — it pushes the file to every SSE subscriber on `/events`.
- **`/send-prompt`** calls `pipeline.on_transcript` directly (no thread spawn at the handler level — `pipeline` already dispatches to a worker). STT is bypassed entirely.

### Build output layout

`frontend/vite.config.ts` sets `build.outDir: '../static'`, so `npm run build` writes `index.html` and `assets/` into the repo's `static/` directory. `friday/server.py` serves `static/index.html` on `/` and `static/assets/*` on `/assets/*`. If you edit `frontend/src/`, rebuild before testing against `uv run friday`. The Vite dev server at :5173 proxies `/transcripts.json`, `/toggle-mute`, `/mute-status`, `/send-prompt`, and `/events` to :5000.

`data/` holds runtime state (`transcripts.json`, `muted.flag`) and is gitignored apart from `.gitkeep`. `static/` is also gitignored — it's a build artifact.

## HTTP API (served by `friday/server.py`)

| Method | Path                | Body            | Returns                                                                                  |
| ------ | ------------------- | --------------- | ---------------------------------------------------------------------------------------- |
| GET    | `/`, `/index.html`  | —               | `static/index.html`                                                                      |
| GET    | `/assets/<file>`    | —               | bundled JS/CSS from `static/assets/`                                                     |
| GET    | `/transcripts.json` | —               | full UI state (transcripts, processing, thinking, partial_ai, muted, updated)            |
| GET    | `/events`           | —               | SSE stream of UI state (sends current state on connect, then push on every `write_json`) |
| GET    | `/mute-status`      | —               | `{muted: bool}`                                                                          |
| POST   | `/toggle-mute`      | —               | `{muted: bool}`                                                                          |
| POST   | `/send-prompt`      | `{prompt: str}` | `{success: true}` — runs the pipeline on a thread                                        |

## Gotchas

- LM Studio at `LLM_STUDIO_URL` must be reachable before utterances flow, or `requests.post` hangs for `LLM_REQUEST_TIMEOUT` seconds. `__main__.health_check()` probes `/v1/models` at startup and logs a warning, but doesn't abort.
- `STT_LANGUAGE` is currently fixed to English (`en`). Whisper always runs in `transcribe` mode; the old `STT_TASK=translate` path was removed. Multi-language support will be re-added later.
- `STT_WHISPER_DEVICE=cuda` requires a CUDA GPU; fall back to `cpu` + `STT_COMPUTE_TYPE=int8` or `float32` if no GPU.
- The mute flag survives crashes. If STT seems dead, check `data/muted.flag`.
- `kokoro`, `faster-whisper`, `silero-vad`, and `openwakeword` all load models lazily on first use; cold-start dominates first-run latency.
- `STT_PROVIDER=sarvam` or `TTS_PROVIDER=sarvam` requires `SARVAM_API_KEY` (or the per-service `STT_SARVAM_API_KEY` / `TTS_SARVAM_API_KEY`). The startup health check warns if missing.
