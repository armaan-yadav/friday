"""
__main__.py — Entry point. Run with `python -m friday` or `uv run friday`.
"""

import logging
import threading

import requests

from . import log_setup
log_setup.configure()

from . import transcribe        # noqa: E402
from . import tts               # noqa: E402
from . import pipeline          # noqa: E402
from . import server            # noqa: E402
from .config import (           # noqa: E402
    LLM_STUDIO_URL,
    SEARCH_SEARXNG_URL,
    STT_PROVIDER,
    STT_SARVAM_API_KEY,
    TTS_PROVIDER,
    TTS_SARVAM_API_KEY,
)

log = logging.getLogger(__name__)


def _probe(url: str, what: str, timeout: float = 2.0) -> None:
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code < 500:
            log.info("✓ %s reachable (%s)", what, resp.status_code)
        else:
            log.warning("⚠ %s HTTP %s — service may be down", what, resp.status_code)
    except requests.exceptions.RequestException as exc:
        log.warning("⚠ %s unreachable at %s: %s", what, url, exc)


def health_check() -> None:
    log.info("Running startup health checks...")
    # LM Studio: GET /v1/models is the canonical reachability probe
    if LLM_STUDIO_URL:
        models_url = LLM_STUDIO_URL.rsplit("/chat/completions", 1)[0] + "/models"
        _probe(models_url, "LM Studio")
    if SEARCH_SEARXNG_URL:
        # Just check the host is up; SearXNG accepts an empty GET on /search.
        _probe(SEARCH_SEARXNG_URL, "SearXNG")
    if STT_PROVIDER == "sarvam" and not STT_SARVAM_API_KEY:
        log.warning("⚠ STT_PROVIDER=sarvam but no API key configured")
    if TTS_PROVIDER == "sarvam" and not TTS_SARVAM_API_KEY:
        log.warning("⚠ TTS_PROVIDER=sarvam but no API key configured")


def main() -> None:
    print("=" * 60)
    print("  Friday Voice Assistant")
    print("  STT (Whisper / Sarvam)  →  LLM (LM Studio)  →  TTS (Kokoro / Sarvam)")
    print("=" * 60)

    transcribe.set_muted(False)
    pipeline.write_json()

    health_check()

    tts.load()
    transcribe.load_model()

    threading.Thread(target=server.serve_forever, daemon=True).start()

    transcribe.start(on_transcript=pipeline.on_transcript)
    log.info("Session ended")


if __name__ == "__main__":
    main()
