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

# Repo root = parent of the `friday/` package directory.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Load .env file from repo root
ENV_PATH = REPO_ROOT / ".env"
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
# TRANSCRIPTION (STT) — Provider selection
# ============================================================================

# "whisper" (local, faster-whisper) or "sarvam" (cloud)
STT_PROVIDER: str = _get_env("STT_PROVIDER", "whisper")

STT_SAMPLE_RATE: int = _get_env("STT_SAMPLE_RATE", 16000, int)
STT_LANGUAGE: str = _get_env("STT_LANGUAGE", "en")

# ── Whisper (local) ─────────────────────────────────────────────────────────
STT_MODEL_SIZE: str = _get_env("STT_MODEL_SIZE", "large-v3")
STT_WHISPER_DEVICE: str = _get_env("STT_WHISPER_DEVICE", "cuda")
STT_COMPUTE_TYPE: str = _get_env("STT_COMPUTE_TYPE", "float16")

# ── Sarvam (cloud) — shared API key for STT + TTS ──────────────────────────
SARVAM_API_KEY: str = _get_env("SARVAM_API_KEY", "")

# Per-service overrides fall back to the shared key when unset
STT_SARVAM_API_KEY: str = _get_env("STT_SARVAM_API_KEY", SARVAM_API_KEY)
STT_SARVAM_URL: str = _get_env("STT_SARVAM_URL", "https://api.sarvam.ai/speech-to-text")
STT_SARVAM_MODEL: str = _get_env("STT_SARVAM_MODEL", "saarika:v2.5")
STT_SARVAM_LANGUAGE: str = _get_env("STT_SARVAM_LANGUAGE", "en-IN")
STT_SARVAM_TIMEOUT: int = _get_env("STT_SARVAM_TIMEOUT", 30, int)

# ============================================================================
# VOICE ACTIVITY DETECTION (VAD)
# ============================================================================

# Wake-word variants. Include common Whisper misrecognitions so a single
# real-world utterance ("Hi Friday", "Fryday", "Friday?") still triggers.
_DEFAULT_WAKE_WORDS = [
    "friday", "hey friday", "hi friday", "hello friday", "okay friday",
    "ok friday", "yo friday", "fryday", "fridey", "fride", "free day",
    "frida", "freeday", "friyay", "freitag",
]
STT_WAKE_WORDS: list[str] = _get_env("STT_WAKE_WORDS", _DEFAULT_WAKE_WORDS, list)
# Fuzzy-match similarity threshold (0–100, rapidfuzz partial_ratio). Lower =
# more permissive (more false wakes), higher = stricter (more misses).
STT_WAKE_FUZZY_THRESHOLD: int = _get_env("STT_WAKE_FUZZY_THRESHOLD", 85, int)
STT_CONVERSATION_TIMEOUT: float = _get_env("STT_CONVERSATION_TIMEOUT", 25.0, float)
STT_SILENCE_THRESHOLD: float = _get_env("STT_SILENCE_THRESHOLD", 0.04, float)
STT_SILENCE_DURATION: float = _get_env("STT_SILENCE_DURATION", 0.8, float)
STT_MIN_SPEECH_DURATION: float = _get_env("STT_MIN_SPEECH_DURATION", 0.5, float)
# Shorter minimum while idle so a quick "Friday!" by itself isn't discarded.
STT_MIN_SPEECH_DURATION_IDLE: float = _get_env(
    "STT_MIN_SPEECH_DURATION_IDLE", 0.25, float
)
STT_BLOCK_SIZE: int = _get_env("STT_BLOCK_SIZE", 1600, int)

# Semantic endpointing — hold the turn when the transcript ends in a "dangler"
# (preposition, conjunction, article, etc.) that signals the user isn't done.
_DEFAULT_DANGLER_WORDS = [
    "and", "or", "but", "so", "because", "if", "when", "while", "after",
    "before", "with", "without", "about", "between", "among", "for", "from",
    "to", "of", "in", "on", "at", "by", "as", "than", "then", "the", "a",
    "an", "my", "your", "his", "her", "its", "our", "their", "is", "am",
    "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "have", "has", "had", "will", "would", "can", "could", "should",
    "might", "may", "that", "this", "these", "those", "which", "who",
    "whom", "whose", "what", "where", "why", "how",
]
STT_DANGLER_WORDS: list[str] = _get_env(
    "STT_DANGLER_WORDS", _DEFAULT_DANGLER_WORDS, list
)
# Seconds to wait for a continuation when the transcript ends in a dangler.
STT_DANGLER_GRACE_PERIOD: float = _get_env("STT_DANGLER_GRACE_PERIOD", 2.0, float)
# A new utterance arriving within this many seconds of the previous dispatch
# is merged with it (cancelling the in-flight reply).
STT_MERGE_WINDOW: float = _get_env("STT_MERGE_WINDOW", 1.5, float)

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
LLM_HISTORY_MAX_TURNS: int = _get_env("LLM_HISTORY_MAX_TURNS", 10, int)
LLM_TOOLS_ENABLED: bool = _get_env("LLM_TOOLS_ENABLED", False, bool)

# ============================================================================
# TEXT-TO-SPEECH (TTS) — Provider selection
# ============================================================================

# "kokoro" (local) or "sarvam" (cloud)
TTS_PROVIDER: str = _get_env("TTS_PROVIDER", "kokoro")

# ── Kokoro (local) ─────────────────────────────────────────────────────────
TTS_KOKORO_LANG: str = _get_env("TTS_KOKORO_LANG", "a")
TTS_KOKORO_VOICE: str = _get_env("TTS_KOKORO_VOICE", "af_heart")
TTS_KOKORO_SAMPLE_RATE: int = _get_env("TTS_KOKORO_SAMPLE_RATE", 24000, int)

# ── Sarvam (cloud) ─────────────────────────────────────────────────────────
TTS_SARVAM_API_KEY: str = _get_env("TTS_SARVAM_API_KEY", SARVAM_API_KEY)
TTS_SARVAM_URL: str = _get_env("TTS_SARVAM_URL", "https://api.sarvam.ai/text-to-speech")
TTS_SARVAM_MODEL: str = _get_env("TTS_SARVAM_MODEL", "bulbul:v2")
TTS_SARVAM_SPEAKER: str = _get_env("TTS_SARVAM_SPEAKER", "anushka")
TTS_SARVAM_LANGUAGE: str = _get_env("TTS_SARVAM_LANGUAGE", "en-IN")
TTS_SARVAM_SAMPLE_RATE: int = _get_env("TTS_SARVAM_SAMPLE_RATE", 22050, int)
TTS_SARVAM_PITCH: float = _get_env("TTS_SARVAM_PITCH", 0.0, float)
TTS_SARVAM_PACE: float = _get_env("TTS_SARVAM_PACE", 1.0, float)
TTS_SARVAM_LOUDNESS: float = _get_env("TTS_SARVAM_LOUDNESS", 1.0, float)
TTS_SARVAM_TIMEOUT: int = _get_env("TTS_SARVAM_TIMEOUT", 30, int)

# ============================================================================
# WAKE ACKNOWLEDGEMENT — short reply when the wake word fires alone
# ============================================================================

TTS_ACK_ENABLED: bool = _get_env("TTS_ACK_ENABLED", True, bool)
_DEFAULT_ACK_PHRASES = [ "yes boss"]
TTS_ACK_PHRASES: list[str] = _get_env(
    "TTS_ACK_PHRASES", _DEFAULT_ACK_PHRASES, list
)

# ============================================================================
# BARGE-IN (Interrupt Detection)
# ============================================================================

TTS_BARGE_IN_THRESHOLD: float = _get_env("TTS_BARGE_IN_THRESHOLD", 0.02, float)
TTS_BARGE_IN_CONFIRM_BLOCKS: int = _get_env("TTS_BARGE_IN_CONFIRM_BLOCKS", 3, int)

# ============================================================================
# WEB UI & SERVER
# ============================================================================

SERVER_PORT: int = _get_env("SERVER_PORT", 5000, int)
SERVER_OUTPUT_JSON: str = _get_env(
    "SERVER_OUTPUT_JSON", str(REPO_ROOT / "data" / "transcripts.json")
)
SERVER_MUTE_FLAG_PATH: str = _get_env(
    "SERVER_MUTE_FLAG_PATH", str(REPO_ROOT / "data" / "muted.flag")
)

# ============================================================================
# WEB SEARCH — SearXNG + Jina Reader
# ============================================================================

SEARCH_ENABLED: bool = _get_env("SEARCH_ENABLED", True, bool)
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
        "STT_PROVIDER": STT_PROVIDER,
        "STT_SAMPLE_RATE": STT_SAMPLE_RATE,
        "STT_LANGUAGE": STT_LANGUAGE,
        # Whisper
        "STT_MODEL_SIZE": STT_MODEL_SIZE,
        "STT_WHISPER_DEVICE": STT_WHISPER_DEVICE,
        "STT_COMPUTE_TYPE": STT_COMPUTE_TYPE,
        # Sarvam
        "STT_SARVAM_API_KEY": "***" if STT_SARVAM_API_KEY else "",
        "STT_SARVAM_URL": STT_SARVAM_URL,
        "STT_SARVAM_MODEL": STT_SARVAM_MODEL,
        "STT_SARVAM_LANGUAGE": STT_SARVAM_LANGUAGE,
        "STT_SARVAM_TIMEOUT": STT_SARVAM_TIMEOUT,
        # Wake / VAD
        "STT_WAKE_WORDS": STT_WAKE_WORDS,
        "STT_WAKE_FUZZY_THRESHOLD": STT_WAKE_FUZZY_THRESHOLD,
        "STT_CONVERSATION_TIMEOUT": STT_CONVERSATION_TIMEOUT,
        "STT_SILENCE_THRESHOLD": STT_SILENCE_THRESHOLD,
        "STT_SILENCE_DURATION": STT_SILENCE_DURATION,
        "STT_MIN_SPEECH_DURATION": STT_MIN_SPEECH_DURATION,
        "STT_MIN_SPEECH_DURATION_IDLE": STT_MIN_SPEECH_DURATION_IDLE,
        "STT_BLOCK_SIZE": STT_BLOCK_SIZE,
        "STT_DANGLER_WORDS": STT_DANGLER_WORDS,
        "STT_DANGLER_GRACE_PERIOD": STT_DANGLER_GRACE_PERIOD,
        "STT_MERGE_WINDOW": STT_MERGE_WINDOW,
        # LLM
        "LLM_STUDIO_URL": LLM_STUDIO_URL,
        "LLM_MODEL": LLM_MODEL,
        "LLM_SYSTEM_PROMPT": LLM_SYSTEM_PROMPT,
        "LLM_TEMPERATURE": LLM_TEMPERATURE,
        "LLM_MAX_OUTPUT_TOKENS": LLM_MAX_OUTPUT_TOKENS,
        "LLM_REQUEST_TIMEOUT": LLM_REQUEST_TIMEOUT,
        # TTS
        "TTS_PROVIDER": TTS_PROVIDER,
        # Kokoro
        "TTS_KOKORO_LANG": TTS_KOKORO_LANG,
        "TTS_KOKORO_VOICE": TTS_KOKORO_VOICE,
        "TTS_KOKORO_SAMPLE_RATE": TTS_KOKORO_SAMPLE_RATE,
        # Sarvam TTS
        "TTS_SARVAM_API_KEY": "***" if TTS_SARVAM_API_KEY else "",
        "TTS_SARVAM_URL": TTS_SARVAM_URL,
        "TTS_SARVAM_MODEL": TTS_SARVAM_MODEL,
        "TTS_SARVAM_SPEAKER": TTS_SARVAM_SPEAKER,
        "TTS_SARVAM_LANGUAGE": TTS_SARVAM_LANGUAGE,
        "TTS_SARVAM_SAMPLE_RATE": TTS_SARVAM_SAMPLE_RATE,
        "TTS_SARVAM_PITCH": TTS_SARVAM_PITCH,
        "TTS_SARVAM_PACE": TTS_SARVAM_PACE,
        "TTS_SARVAM_LOUDNESS": TTS_SARVAM_LOUDNESS,
        "TTS_SARVAM_TIMEOUT": TTS_SARVAM_TIMEOUT,
        # Wake ack
        "TTS_ACK_ENABLED": TTS_ACK_ENABLED,
        "TTS_ACK_PHRASES": TTS_ACK_PHRASES,
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
