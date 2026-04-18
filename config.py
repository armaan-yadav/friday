"""
config.py — Environment variable loader and configuration management

This module loads all configuration from .env file and provides
a single source of truth for all settings across the application.

Usage:
    from config import STT_MODEL_SIZE, LLM_STUDIO_URL, ...
    
    or
    
    from config import get_config
    cfg = get_config()
    print(cfg.STT_MODEL_SIZE)
"""

import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

# Load .env file from project root
ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)


def _get_env(key: str, default: Any = None, var_type: type = str) -> Any:
    """
    Safely retrieve and type-convert environment variables.
    
    Args:
        key: Environment variable name
        default: Default value if not set
        var_type: Type to convert to (str, int, float, bool, list)
    
    Returns:
        Value from .env or default
    """
    value = os.getenv(key)
    
    if value is None:
        if default is None:
            raise ValueError(f"Missing required env var: {key}")
        return default
    
    if var_type == bool:
        return value.lower() in ("true", "1", "yes")
    elif var_type == int:
        return int(value)
    elif var_type == float:
        return float(value)
    elif var_type == list:
        # Parse comma-separated values
        return [item.strip() for item in value.split(",")]
    
    return value


# ============================================================================
# TRANSCRIPTION (STT) — faster-whisper
# ============================================================================

STT_MODEL_SIZE: str = _get_env("STT_MODEL_SIZE", "large-v3")
STT_LANGUAGE: str = _get_env("STT_LANGUAGE", "hi")
STT_TASK: str = _get_env("STT_TASK", "translate")
STT_SAMPLE_RATE: int = _get_env("STT_SAMPLE_RATE", 16000, int)
STT_WHISPER_DEVICE: str = _get_env("STT_WHISPER_DEVICE", "cuda")
STT_COMPUTE_TYPE: str = _get_env("STT_COMPUTE_TYPE", "float16")

# ============================================================================
# VOICE ACTIVITY DETECTION (VAD)
# ============================================================================

STT_WAKE_WORDS: list[str] = _get_env("STT_WAKE_WORDS", "hey friday", list)
STT_WAKE_WORD_TIMEOUT: float = _get_env("STT_WAKE_WORD_TIMEOUT", 8.0, float)
STT_CONVERSATION_TIMEOUT: float = _get_env("STT_CONVERSATION_TIMEOUT", 12.0, float)
STT_SILENCE_THRESHOLD: float = _get_env("STT_SILENCE_THRESHOLD", 0.01, float)
STT_SILENCE_DURATION: float = _get_env("STT_SILENCE_DURATION", 1.5, float)
STT_MIN_SPEECH_DURATION: float = _get_env("STT_MIN_SPEECH_DURATION", 0.5, float)
STT_BLOCK_SIZE: int = _get_env("STT_BLOCK_SIZE", 1600, int)

# ============================================================================
# LLM (LANGUAGE MODEL) — LM Studio
# ============================================================================

LLM_STUDIO_URL: str = _get_env(
    "LLM_STUDIO_URL", "http://192.168.1.5:1234/v1/chat/completions"
)
LLM_MODEL: str = _get_env("LLM_MODEL", "google/gemma-4-e4b")
LLM_SYSTEM_PROMPT: str = _get_env(
    "LLM_SYSTEM_PROMPT",
    (
        "You are a voice assistant named Friday.\n\n"
        "Keep responses short, natural, and conversational.\n"
        "No markdown, no bullet points, no headers.\n"
        "Respond as you would speak out loud."
    ),
)
LLM_TEMPERATURE: float = _get_env("LLM_TEMPERATURE", 0.7, float)
LLM_MAX_OUTPUT_TOKENS: int = _get_env("LLM_MAX_OUTPUT_TOKENS", 300, int)
LLM_REQUEST_TIMEOUT: int = _get_env("LLM_REQUEST_TIMEOUT", 30, int)

# ============================================================================
# TEXT-TO-SPEECH (TTS) — Kokoro
# ============================================================================

TTS_KOKORO_LANG: str = _get_env("TTS_KOKORO_LANG", "a")
TTS_KOKORO_VOICE: str = _get_env("TTS_KOKORO_VOICE", "af_heart")
TTS_KOKORO_SAMPLE_RATE: int = _get_env("TTS_KOKORO_SAMPLE_RATE", 24000, int)

# ============================================================================
# BARGE-IN (Interrupt Detection)
# ============================================================================

TTS_BARGE_IN_THRESHOLD: float = _get_env("TTS_BARGE_IN_THRESHOLD", 0.02, float)
TTS_BARGE_IN_CONFIRM_BLOCKS: int = _get_env("TTS_BARGE_IN_CONFIRM_BLOCKS", 3, int)

# ============================================================================
# WEB UI & SERVER
# ============================================================================

SERVER_PORT: int = _get_env("SERVER_PORT", 5000, int)
SERVER_OUTPUT_JSON: str = _get_env("SERVER_OUTPUT_JSON", "transcripts.json")
SERVER_MUTE_FLAG_PATH: str = _get_env("SERVER_MUTE_FLAG_PATH", "muted.flag")

# ============================================================================
# WEB SEARCH — SearXNG + Jina Reader
# ============================================================================

SEARCH_SEARXNG_URL: str = _get_env("SEARCH_SEARXNG_URL", "http://localhost:8888/search")
SEARCH_JINA_URL: str = _get_env("SEARCH_JINA_URL", "https://r.jina.ai/")
SEARCH_NUM_RESULTS: int = _get_env("SEARCH_NUM_RESULTS", 4, int)
SEARCH_FETCH_FULL_PAGES: int = _get_env("SEARCH_FETCH_FULL_PAGES", 2, int)
SEARCH_MAX_PAGE_CHARS: int = _get_env("SEARCH_MAX_PAGE_CHARS", 1500, int)
SEARCH_TIMEOUT: int = _get_env("SEARCH_TIMEOUT", 8, int)
SEARCH_JINA_TIMEOUT: int = _get_env("SEARCH_JINA_TIMEOUT", 12, int)

# ============================================================================
# LOGGING & DEBUG
# ============================================================================

LOG_LEVEL: str = _get_env("LOG_LEVEL", "INFO")


def get_config() -> Dict[str, Any]:
    """
    Return all configuration as a dictionary.
    Useful for debugging or passing to functions.
    
    Returns:
        Dictionary of all environment-based config
    """
    return {
        # STT
        "STT_MODEL_SIZE": STT_MODEL_SIZE,
        "STT_LANGUAGE": STT_LANGUAGE,
        "STT_TASK": STT_TASK,
        "STT_SAMPLE_RATE": STT_SAMPLE_RATE,
        "STT_WHISPER_DEVICE": STT_WHISPER_DEVICE,
        "STT_COMPUTE_TYPE": STT_COMPUTE_TYPE,
        # VAD
        "STT_WAKE_WORDS": STT_WAKE_WORDS,
        "STT_WAKE_WORD_TIMEOUT": STT_WAKE_WORD_TIMEOUT,
        "STT_CONVERSATION_TIMEOUT": STT_CONVERSATION_TIMEOUT,
        "STT_SILENCE_THRESHOLD": STT_SILENCE_THRESHOLD,
        "STT_SILENCE_DURATION": STT_SILENCE_DURATION,
        "STT_MIN_SPEECH_DURATION": STT_MIN_SPEECH_DURATION,
        "STT_BLOCK_SIZE": STT_BLOCK_SIZE,
        # LLM
        "LLM_STUDIO_URL": LLM_STUDIO_URL,
        "LLM_MODEL": LLM_MODEL,
        "LLM_SYSTEM_PROMPT": LLM_SYSTEM_PROMPT,
        "LLM_TEMPERATURE": LLM_TEMPERATURE,
        "LLM_MAX_OUTPUT_TOKENS": LLM_MAX_OUTPUT_TOKENS,
        "LLM_REQUEST_TIMEOUT": LLM_REQUEST_TIMEOUT,
        # TTS
        "TTS_KOKORO_LANG": TTS_KOKORO_LANG,
        "TTS_KOKORO_VOICE": TTS_KOKORO_VOICE,
        "TTS_KOKORO_SAMPLE_RATE": TTS_KOKORO_SAMPLE_RATE,
        # Barge-in
        "TTS_BARGE_IN_THRESHOLD": TTS_BARGE_IN_THRESHOLD,
        "TTS_BARGE_IN_CONFIRM_BLOCKS": TTS_BARGE_IN_CONFIRM_BLOCKS,
        # Server
        "SERVER_PORT": SERVER_PORT,
        "SERVER_OUTPUT_JSON": SERVER_OUTPUT_JSON,
        "SERVER_MUTE_FLAG_PATH": SERVER_MUTE_FLAG_PATH,
        # Search
        "SEARCH_SEARXNG_URL": SEARCH_SEARXNG_URL,
        "SEARCH_JINA_URL": SEARCH_JINA_URL,
        "SEARCH_NUM_RESULTS": SEARCH_NUM_RESULTS,
        "SEARCH_FETCH_FULL_PAGES": SEARCH_FETCH_FULL_PAGES,
        "SEARCH_MAX_PAGE_CHARS": SEARCH_MAX_PAGE_CHARS,
        "SEARCH_TIMEOUT": SEARCH_TIMEOUT,
        "SEARCH_JINA_TIMEOUT": SEARCH_JINA_TIMEOUT,
        # Logging
        "LOG_LEVEL": LOG_LEVEL,
    }


if __name__ == "__main__":
    # Print all loaded configuration for debugging
    import json
    print(json.dumps(get_config(), indent=2))
