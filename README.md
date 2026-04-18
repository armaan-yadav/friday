"# Friday Voice Assistant

A real-time voice assistant that streams speech-to-text, passes queries to a local LLM, and synthesizes responses with natural barge-in interruption. Runs as a Python service with an HTTP-served web UI for mute control.

**Core Architecture**: `transcribe.py` (STT) → `main.py` (orchestrator) → `llm.py` (streaming chat) → `tts.py` (speech synthesis with interrupt detection) → `index.html` (web UI)

## Tech Stack

- **Speech-to-Text**: `faster-whisper` (local, CUDA-accelerated)
- **LLM**: `requests` to LM Studio (OpenAI-compatible streaming endpoint)
- **Text-to-Speech**: `kokoro` (fast local synthesis, 24 kHz)
- **Audio I/O**: `sounddevice` + `soundfile`
- **UI**: React/TypeScript with Vite + Tailwind CSS
- **Configuration**: `python-dotenv` for environment-based settings via `.env`

## Quick Start

### Prerequisites
- Python 3.11+
- NVIDIA GPU with CUDA (or CPU fallback)
- Node.js 18+ (for UI development)
- LM Studio running locally at `http://192.168.1.5:1234`

### Setup

1. **Copy environment template**:
   ```bash
   cp .env.example .env
   ```

2. **Customize `.env`** for your environment (see Configuration section below)

3. **Install Python dependencies**:
   ```bash
   uv sync
   ```

4. **Build/Run the UI**:
   ```bash
   cd ui
   npm install
   npm run build  # Production build
   # OR
   npm run dev    # Development with live reload
   ```

5. **Start the main server**:
   ```bash
   uv run main.py
   ```

6. **Open in browser**:
   ```
   http://localhost:5000
   ```

## Configuration

All settings are in **`.env`** file. See `.env.example` for full list.

### Key Settings

**STT (Whisper)**:
```env
STT_MODEL_SIZE=large-v3          # Model size: tiny, base, small, medium, large, large-v3
STT_LANGUAGE=hi                  # Language code: en, hi, es, fr, etc.
STT_TASK=translate               # transcribe or translate
STT_WHISPER_DEVICE=cuda          # cuda or cpu
STT_COMPUTE_TYPE=float16         # float16 (GPU), float32 (CPU), or int8
```

**LLM (LM Studio)**:
```env
LLM_STUDIO_URL=http://192.168.1.5:1234/v1/chat/completions
LLM_MODEL=google/gemma-4-e4b
LLM_MAX_OUTPUT_TOKENS=1000       # Increased for extended thinking models
LLM_TEMPERATURE=0.7
```

**TTS (Kokoro)**:
```env
TTS_KOKORO_LANG=a                # a (American) or b (British)
TTS_KOKORO_VOICE=af_heart        # Voice variant
```

**Wake Word & VAD**:
```env
STT_WAKE_WORDS=friday            # Comma-separated: friday,okay friday
STT_SILENCE_THRESHOLD=0.01       # RMS cutoff for speech detection
STT_CONVERSATION_TIMEOUT=12.0    # Seconds before auto-sleep
```

## Backend API Endpoints

### GET Endpoints

| Endpoint | Description | Response |
|----------|-------------|----------|
| `GET /` | Serves the main UI page | HTML (index.html) |
| `GET /index.html` | Same as `/` | HTML (index.html) |
| `GET /transcripts.json` | Get all chat transcripts and current state | JSON |
| `GET /mute-status` | Check if microphone is currently muted | `{"muted": boolean}` |

### POST Endpoints

| Endpoint | Description | Request Body | Response |
|----------|-------------|--------------|----------|
| `POST /toggle-mute` | Toggle microphone mute on/off | (none) | `{"muted": boolean}` |
| `POST /send-prompt` | Send a text prompt to be processed by LLM | `{"prompt": "text here"}` | `{"success": true}` or error |

### Response Examples

#### `GET /transcripts.json`
```json
{
  "transcripts": [
    {
      "user": "Tell me a joke",
      "ai": "Why don't scientists trust atoms? Because they make up everything!",
      "time": "14:30:45",
      "timestamp": 1776504633.123
    }
  ],
  "processing": false,
  "thinking": false,
  "partial_ai": "",
  "muted": false,
  "updated": 1776504633.456
}
```

#### `GET /mute-status`
```json
{
  "muted": false
}
```

#### `POST /toggle-mute`
```json
{
  "muted": true
}
```

#### `POST /send-prompt` (Success)
```json
{
  "success": true
}
```

#### `POST /send-prompt` (Error)
```json
{
  "error": "empty prompt"
}
```

### Example Usage

```bash
# Get all transcripts
curl http://localhost:5000/transcripts.json

# Check mute status
curl http://localhost:5000/mute-status

# Toggle mute
curl -X POST http://localhost:5000/toggle-mute

# Send a text prompt to LLM
curl -X POST http://localhost:5000/send-prompt \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the weather?"}'
```

## Architecture

### Pipeline Flow

```
User Audio
    ↓
Whisper STT (transcribe.py)
    ↓ [Wake word detected: "Hey Friday"]
    ↓
Speech Activity Detection (VAD)
    ↓
User Query Transcription
    ↓
LLM Processing (llm.py)
    ├→ Web Search (SearXNG + Jina Reader) [optional]
    ├→ Streaming from LM Studio
    └→ Sentence-by-sentence output
    ↓
Text-to-Speech (tts.py)
    ├→ Kokoro synthesis
    ├→ Microphone monitoring (barge-in detection)
    └→ Audio playback
    ↓
UI Update (transcripts.json)
    ↓
Web Browser (React UI)
```

### Key Components

- **`transcribe.py`**: Handles speech-to-text with wake word detection and VAD
- **`llm.py`**: Manages LLM communication with streaming support and web search
- **`tts.py`**: Synthesizes audio responses with barge-in interrupt detection
- **`main.py`**: Orchestrates the pipeline and serves the HTTP API
- **`search.py`**: Integrates SearXNG and Jina Reader for web context
- **`ui/`**: React frontend for mute control and chat visualization

## Features

✅ **Real-time Streaming**: Speech recognition and LLM responses stream in real-time  
✅ **Barge-in**: Interrupt playback by speaking (customizable threshold)  
✅ **Web Search**: Automatic search for news/current events queries  
✅ **Conversation History**: Maintains context across multiple turns  
✅ **Mute Control**: Toggle microphone from web UI  
✅ **Predefined Prompts**: Click buttons to send test queries without speaking  
✅ **Configurable Everything**: Language, model, voice, thresholds all in `.env`  
✅ **Local-First**: No cloud dependencies (except optional web search)  

## Troubleshooting

### "ModuleNotFoundError"
Make sure you're running with `uv run` (uses the venv) not just `python`.

### "LM Studio not reachable"
Check `LLM_STUDIO_URL` in `.env` matches your LM Studio server address.

### "Empty LLM responses"
- Increase `LLM_MAX_OUTPUT_TOKENS` (models with reasoning need more tokens)
- Check that LM Studio has a model loaded
- Verify the model name in `LLM_MODEL` matches the loaded model

### "Audio issues"
- Check `STT_WHISPER_DEVICE` is set correctly (cuda/cpu)
- Verify microphone is not muted system-wide
- Adjust `STT_SILENCE_THRESHOLD` if speech isn't detected

## Development

### UI Development

```bash
cd ui
npm run dev
# Opens http://localhost:5173 with hot reload
```

### Testing Endpoints

```bash
# Test LLM streaming with search
uv run test_llm_with_search.py

# Test LLM streaming without search
uv run test_llm_streaming.py

# Test /send-prompt endpoint
uv run test_endpoint.py
```

### Debugging

View logs while running:
```bash
uv run main.py 2>&1 | grep -E "\[LLM\]|\[STT\]|\[TTS\]|\[Main\]"
```

## Performance Tips

- **Faster STT**: Use `STT_MODEL_SIZE=base` or `small` instead of `large-v3`
- **CPU Mode**: Set `STT_WHISPER_DEVICE=cpu` (slower but uses no VRAM)
- **Disable Search**: Set prompts that don't trigger search detection
- **Shorter Responses**: Lower `LLM_MAX_OUTPUT_TOKENS` for faster synthesis

## License

MIT

## Contributing

See `.github/copilot-instructions.md` for development guidelines.
" 
