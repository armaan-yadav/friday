# Friday Voice Assistant — Copilot Instructions

## Project Overview

**Friday** is a real-time voice assistant that streams speech-to-text, passes queries to a local LLM, and synthesizes responses with natural barge-in interruption. It runs as a Python service with an HTTP-served web UI for mute control.

**Core Architecture**: `transcribe.py` (STT) → `main.py` (orchestrator) → `llm.py` (streaming chat) → `tts.py` (speech synthesis with interrupt detection) → `index.html` (web UI)

### Tech Stack

- **Speech-to-Text**: `faster-whisper` (local, CUDA-accelerated)
- **LLM**: `requests` to LM Studio (OpenAI-compatible streaming endpoint)
- **Text-to-Speech**: `kokoro` (fast local synthesis, 24 kHz)
- **Audio I/O**: `sounddevice` + `soundfile`
- **UI**: HTML5/CSS3 served via Python's `HTTPServer`
- **Configuration**: `python-dotenv` for environment-based settings via `.env`

## Configuration Management

All configuration is centralized in **`.env`** file and loaded by **`config.py`**. Never hardcode settings—always use the config module.

### Setup
1. Copy `.env.example` to `.env` and customize for your environment
2. Import from `config.py`: `from config import STT_MODEL_SIZE, LLM_STUDIO_URL, ...`
3. `.env` is git-ignored (see `.gitignore`)—each developer has their own settings

### Environment Variables by Category

**STT (Whisper)**:
- `STT_MODEL_SIZE` (default: `large-v3`) — "tiny", "base", "small", "medium", "large", or "large-v3"
- `STT_LANGUAGE` (default: `hi`) — Language code; "en", "hi", "es", "fr", etc.
- `STT_TASK` (default: `translate`) — "transcribe" or "translate"
- `STT_WHISPER_DEVICE` (default: `cuda`) — "cuda" (GPU) or "cpu"
- `STT_COMPUTE_TYPE` (default: `float16`) — "float16" (GPU), "float32" (CPU), or "int8"

**Wake-Word & VAD**:
- `STT_WAKE_WORDS` (default: `hey friday`) — Comma-separated phrases
- `STT_SILENCE_THRESHOLD` (default: `0.01`) — RMS cutoff for speech detection
- `STT_CONVERSATION_TIMEOUT` (default: `12.0`) — Seconds before auto-sleep

**LLM (LM Studio)**:
- `LLM_STUDIO_URL` (default: `http://192.168.1.5:1234/v1/chat/completions`) — API endpoint
- `LLM_MODEL` (default: `google/gemma-4-e4b`) — Model name (must match server's loaded model)
- `LLM_SYSTEM_PROMPT` — System behavior definition
- `LLM_MAX_OUTPUT_TOKENS` (default: `300`) — Response length (~4 chars/token)
- `LLM_TEMPERATURE` (default: `0.7`) — Creativity (0.0–1.0+)

**TTS (Kokoro)**:
- `TTS_KOKORO_LANG` (default: `a`) — "a" (American) or "b" (British)
- `TTS_KOKORO_VOICE` (default: `af_heart`) — Voice variant ("af_heart", "am_michael", etc.)

**Barge-In**:
- `TTS_BARGE_IN_THRESHOLD` (default: `0.02`) — RMS to interrupt playback
- `TTS_BARGE_IN_CONFIRM_BLOCKS` (default: `3`) — Consecutive blocks needed

**Server**:
- `SERVER_PORT` (default: `5000`) — HTTP port for web UI
- `SERVER_OUTPUT_JSON` (default: `transcripts.json`) — Transcript file
- `SERVER_MUTE_FLAG_PATH` (default: `muted.flag`) — Mute marker file

### 1. Wake Word → Transcription → Pipeline

```
User audio → transcribe.py detects "Hey Friday" 
  → _contains_wake_word() checks utterance
  → _transcription_loop() enters active mode (12s timeout auto-sleep)
  → on_transcript() callback triggers main.py pipeline
```

**Key Pattern**: `transcribe.py` uses a **state machine** (`is_active` flag) with RMS-based silence detection. The **mute flag** (`muted.flag` file) disables transcription entirely—always check `is_muted()` before processing.

### 2. Streaming LLM to Sentence-by-Sentence TTS

```
main.py → llm.ask_stream_sentences(user_text)
  ↓
  Yields complete sentences via regex split on [.!?] boundaries
  ↓
  Each sentence → tts.speak() immediately (low latency)
  ↓
  User hears first response words ~200ms after question ends
```

**Key Pattern**: `llm.ask_stream_sentences()` buffers all chunks then does **post-processing sentence splitting** (not real-time). This avoids streaming incomplete sentences to TTS. The LLM's streaming endpoint is at `http://192.168.1.5:1234/v1/chat/completions` (configurable in `llm.py`).

### 3. Barge-In: Microphone Monitoring During Playback

```
tts.speak() opens a second InputStream (16 kHz, low-latency)
  ↓
  While sd.play() outputs audio:
    _mic_monitor_callback() measures RMS energy
    ↓
    If 3+ consecutive loud blocks exceed BARGE_IN_THRESHOLD (0.02):
      _interrupted.set() → sd.stop() → return False
  ↓
  STT picks up audio already in its queue (seamless handoff)
```

**Key Pattern**: Barge-in uses a **background thread callback** on a separate audio stream. The threshold and confirmation blocks are tunable (see `BARGE_IN_THRESHOLD`, `BARGE_IN_CONFIRM_BLOCKS` in `tts.py`).

### 4. UI State Updates via `transcripts.json`

```
_write_json() writes to transcripts.json:
  {
    "transcripts": [{"user": "...", "ai": "...", "time": "HH:MM:SS", "timestamp": Unix}],
    "processing": bool,
    "thinking": bool,
    "partial_ai": str (streaming response preview),
    "muted": bool,
    "updated": Unix timestamp
  }
```

**Key Pattern**: The web UI polls `transcripts.json` (no WebSocket). Mute toggle sends POST to `/toggle-mute` → updates `muted.flag` → next frame of `_write_json()` reflects change.

## Configuration & Tuning Points

| File | Variable | Purpose |
|------|----------|---------|
| `transcribe.py` | `MODEL_SIZE`, `WHISPER_DEVICE`, `COMPUTE_TYPE` | Whisper model; switch to `"small"` for faster/lower-RAM |
| `transcribe.py` | `LANGUAGE`, `TASK` | Language code (`"hi"` for Hindi), `"translate"` vs `"transcribe"` |
| `transcribe.py` | `SILENCE_THRESHOLD`, `SILENCE_DURATION` | RMS cutoff for speech detection; tune for noise floors |
| `transcribe.py` | `CONVERSATION_TIMEOUT` | Seconds before auto-sleep (currently 12s) |
| `llm.py` | `LM_STUDIO_URL`, `LM_MODEL` | LM Studio connection; model name must match server's loaded model |
| `llm.py` | `SYSTEM_PROMPT` | Global system behavior ("You are Friday...") |
| `llm.py` | `MAX_OUTPUT_TOKENS` | Hard cap on response length (300 tokens = ~80 words) |
| `tts.py` | `KOKORO_VOICE`, `KOKORO_LANG` | Voice variant (`"af_heart"` = warm female); `"a"` = American English |
| `tts.py` | `BARGE_IN_THRESHOLD` | RMS energy to trigger interrupt (raise for less interrupts) |
| `main.py` | HTTP port (default 5000) | Change in `_start_server(port=5000)` |

## Common Modifications

### Adjusting Configuration via .env

Instead of editing Python files, modify `.env`:

```bash
# Speed up by using smaller model
STT_MODEL_SIZE=small

# Use CPU if VRAM limited
STT_WHISPER_DEVICE=cpu

# Reduce response length for faster speech
LLM_MAX_OUTPUT_TOKENS=150

# Disable barge-in by setting impossibly high threshold
TTS_BARGE_IN_THRESHOLD=999.0

# Add multiple wake words
STT_WAKE_WORDS=hey friday,okay friday
```

### Adding a New Voice Command Handler
1. Extend `STT_WAKE_WORDS` in `.env` (e.g., `STT_WAKE_WORDS=hey friday,hello friday`)
2. If command-specific behavior: add branching in `main._on_transcript()` before calling `llm.ask_stream_sentences()`

### Running with Custom Configuration
Each developer can have their own `.env`:
```bash
# Copy example template
cp .env.example .env

# Edit for your machine
nano .env

# Run normally — config.py loads from .env
python main.py
```

## Testing & Debugging

- **Manual transcript**: Run `transcribe.py` standalone with `load_model()` + `start()` to isolate STT.
- **LLM streaming**: Test `llm.ask_stream(user_text)` in a REPL to verify sentence splitting.
- **Audio levels**: Monitor mic RMS in `_audio_callback()` or `_mic_monitor_callback()` logs to tune thresholds.
- **HTTP server**: `curl http://localhost:5000/transcripts.json` to check state JSON.
- **View loaded config**: `python config.py` to print all environment variables.

## Gotchas

- **CUDA required**: If `STT_WHISPER_DEVICE=cuda` but no GPU: set to `cpu` (much slower, ~10s/utterance).
- **LM Studio must be running** at the configured `LLM_STUDIO_URL` before starting Friday (else `requests.post()` hangs with timeout).
- **Language mismatch**: `STT_LANGUAGE=hi` + English speech = mistranslations. Match language to audio.
- **Mute flag persists**: Setting mute flag file (path from `SERVER_MUTE_FLAG_PATH`) disables STT permanently until removed. The `/toggle-mute` API deletes it.
- **Sentence splitting**: The regex `(?<=[.!?])\s+` won't split on ellipses (`...`) or abbreviations (`Dr. Smith`). Improve in `llm.ask_stream_sentences()` if needed.
- **Missing `.env`**: If `.env` doesn't exist, `config.py` will raise `ValueError` on first import. Copy `.env.example` to `.env`.

## Entry Point

```bash
python main.py
# Opens http://localhost:5000
# Logs all pipeline stages: [STT], [LLM], [TTS], [Main], [Server]
```

Press Ctrl+C to stop; `transcribe.set_muted(False)` is called on startup to clear any prior mute state.
