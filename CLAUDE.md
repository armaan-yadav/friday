# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Friday** is a real-time voice assistant: microphone → faster-whisper STT (with wake word) → LM Studio LLM (streaming, optional web search) → Kokoro TTS (with barge-in) → React UI served from the same Python process.

The Python service is a single process running three threads: an STT loop (blocks on `sd.InputStream`), an HTTP server on port 5000, and short-lived TTS playback during responses. There is no WebSocket — the UI polls `transcripts.json` every 250ms.

## Commands

```bash
# Install Python deps (uv-managed, see pyproject.toml + uv.lock)
uv sync

# Run the assistant (STT loop + HTTP server). Opens http://localhost:5000
uv run main.py

# Print all loaded config from .env (debug)
uv run config.py

# UI development (proxies API calls to localhost:5000)
cd ui && npm install && npm run dev   # http://localhost:5173 with HMR
cd ui && npm run build                 # writes build artifacts to repo root (../)
cd ui && npm run lint                  # eslint
```

There is no Python test framework configured. The README references `test_llm_with_search.py`, `test_llm_streaming.py`, `test_endpoint.py` — **these files do not exist** in the repo. Don't trust that section.

`.env` must exist before first import of `config.py` or it raises `ValueError`. Copy `.env.example` to `.env`.

## Architecture

### Module pipeline

```
transcribe.py  (STT loop, owns the mic, calls back per utterance)
      │ on_transcript(user_text)
      ▼
main.py::_on_transcript  (orchestrator + HTTP server)
      │ for sentence, is_last in llm.ask_stream_sentences(...):
      ▼
llm.py  ── search.py (per-turn, only if needs_search() matches)
      │ yields sentences
      ▼
tts.py::speak(sentence)   (Kokoro synth + 2nd mic stream for barge-in)
```

`config.py` is the single source of truth for all settings, loaded from `.env` via `python-dotenv`. Every other module imports its constants from there. Each module also defines short backward-compat aliases (e.g. `MODEL_SIZE = STT_MODEL_SIZE`) — keep using the `STT_*` / `LLM_*` / `TTS_*` names from `config.py` in new code.

### Cross-cutting patterns (non-obvious)

- **Mute is a file**, not a variable. `muted.flag` (path from `SERVER_MUTE_FLAG_PATH`) existing = muted. `transcribe.is_muted()` does `os.path.exists()`. The `/toggle-mute` endpoint creates/removes it. `main.py` calls `transcribe.set_muted(False)` on startup to clear stale state.
- **STT is a state machine**, not always-on transcription. `_transcription_loop` flips between idle and `is_active`. Idle requires a wake word match (`STT_WAKE_WORDS`); active stays on until `STT_CONVERSATION_TIMEOUT` of inactivity. When a wake word is mid-utterance, the rest of the line is stripped and treated as the query (`_strip_wake_word`).
- **Streaming → sentence splitting is post-hoc**, not real-time. `llm.ask_stream_sentences` collects all chunks from `ask_stream` first, then splits on `(?<=[.!?])\s+`. So TTS latency is full-reply latency, not first-chunk. The split regex breaks on `Dr.` / `...`. Don't claim "first-sentence latency" — improve the splitter if you need it.
- **Search context is per-turn, never in `_chat_history`.** `llm.py` injects search results into the system prompt for the current call only, then appends only the user message + assistant reply to history. Don't move search results into the message list.
- **Barge-in opens a second `sd.InputStream`** (16 kHz, 512-sample blocks) inside `tts.speak()` while playback runs. RMS > `TTS_BARGE_IN_THRESHOLD` for `TTS_BARGE_IN_CONFIRM_BLOCKS` consecutive blocks → `_interrupted.set()` → `sd.stop()` → returns `False`. The STT mic stream keeps running independently and picks up the user's words from its own queue.
- **UI state is `transcripts.json` on disk.** `_write_json()` rewrites the whole file on every state change (thinking, partial_ai, new transcript, mute toggle). Frontend polls every 250ms (`ui/src/hooks/usePolling.ts`).
- **`/send-prompt`** spawns a thread to run `_on_transcript` so the HTTP handler returns immediately. STT is bypassed entirely for these.

### UI build output is at the repo root

`ui/vite.config.ts` sets `build.outDir: '..'`, so `npm run build` writes `index.html` and `assets/` **into the parent (repo root)**, where `main.py`'s HTTP handler serves them. The committed `index.html`, `assets/`, and `ui-dist/` are build artifacts. If you edit `ui/src/`, rebuild before testing against `main.py`. Vite dev server at :5173 proxies `/transcripts.json`, `/toggle-mute`, `/mute-status`, `/send-prompt` to :5000.

## HTTP API (served by `main.py`)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET  | `/`, `/index.html`   | — | HTML |
| GET  | `/transcripts.json`  | — | full UI state (transcripts, processing, thinking, partial_ai, muted, updated) |
| GET  | `/mute-status`       | — | `{muted: bool}` |
| POST | `/toggle-mute`       | — | `{muted: bool}` |
| POST | `/send-prompt`       | `{prompt: str}` | `{success: true}` — runs the pipeline on a thread |

## Gotchas

- LM Studio at `LLM_STUDIO_URL` must be reachable before `main.py` starts handling utterances or `requests.post` will hang for `LLM_REQUEST_TIMEOUT` seconds.
- `STT_LANGUAGE` must match the spoken language; `STT_TASK=translate` translates to English, `transcribe` keeps the source language.
- `STT_WHISPER_DEVICE=cuda` requires a CUDA GPU; fall back to `cpu` + `STT_COMPUTE_TYPE=int8` or `float32` if no GPU.
- The mute flag survives crashes. If STT seems dead, check whether `muted.flag` exists.
- `kokoro` and `faster-whisper` load models at import / `load_model()` time; cold start dominates first-run latency.
