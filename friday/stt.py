"""
stt.py — Pluggable Speech-to-Text providers.

Selects between local faster-whisper and cloud providers (Sarvam) based on
STT_PROVIDER. Audio capture and the wake-word state machine live in
transcribe.py — this module owns model loading and per-utterance inference.

Provider contract:
    load() -> None
    transcribe(audio: np.ndarray, sample_rate: int = 16000, beam_size: int = 5) -> str
"""

import io
import logging

import numpy as np
import requests
import soundfile as sf

log = logging.getLogger(__name__)

from .config import (
    STT_PROVIDER,
    STT_LANGUAGE,
    STT_MODEL_SIZE,
    STT_WHISPER_DEVICE,
    STT_COMPUTE_TYPE,
    STT_SARVAM_API_KEY,
    STT_SARVAM_URL,
    STT_SARVAM_MODEL,
    STT_SARVAM_LANGUAGE,
    STT_SARVAM_TIMEOUT,
)

_whisper_model = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load() -> None:
    """Warm up the active provider."""
    if STT_PROVIDER == "whisper":
        _load_whisper()
    elif STT_PROVIDER == "sarvam":
        _load_sarvam()
    else:
        raise ValueError(
            f"Unknown STT_PROVIDER: {STT_PROVIDER!r}. Use 'whisper' or 'sarvam'."
        )


def transcribe(audio: np.ndarray, sample_rate: int = 16000, beam_size: int = 5) -> str:
    """Run the active provider on a mono float32 audio buffer; return the text."""
    if STT_PROVIDER == "whisper":
        return _transcribe_whisper(audio, beam_size=beam_size)
    if STT_PROVIDER == "sarvam":
        return _transcribe_sarvam(audio, sample_rate)
    raise ValueError(f"Unknown STT_PROVIDER: {STT_PROVIDER!r}")


# ---------------------------------------------------------------------------
# Whisper (local, faster-whisper)
# ---------------------------------------------------------------------------

def _load_whisper() -> None:
    global _whisper_model
    if _whisper_model is not None:
        log.debug("Whisper already loaded")
        return
    from faster_whisper import WhisperModel
    log.info("Loading Whisper '%s' on %s (%s)", STT_MODEL_SIZE, STT_WHISPER_DEVICE, STT_COMPUTE_TYPE)
    _whisper_model = WhisperModel(
        STT_MODEL_SIZE,
        device=STT_WHISPER_DEVICE,
        compute_type=STT_COMPUTE_TYPE,
    )
    log.info("Whisper ready")


def _transcribe_whisper(audio: np.ndarray, beam_size: int) -> str:
    if _whisper_model is None:
        raise RuntimeError("Call stt.load() before transcribe().")
    # vad_filter=False: we already gated upstream with silero/RMS, and Whisper's
    # internal VAD often drops short utterances after our external filter.
    #
    # condition_on_previous_text=False: critical for short streaming utterances.
    # When True (the default) Whisper carries the previous segment's text as a
    # prompt and "continues" it on the next call — this is the textbook cause
    # of repeated-phrase hallucinations ("Bye. Bye. Bye.", "Thank you. Thank
    # you.") on near-silent audio.
    #
    # no_speech_threshold + log_prob_threshold + compression_ratio_threshold
    # are faster-whisper's built-in hallucination filters; spelling them out
    # here so we can tune if the room/mic profile changes.
    segments, info = _whisper_model.transcribe(
        audio,
        language=STT_LANGUAGE,
        task="transcribe",
        beam_size=beam_size,
        vad_filter=False,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        initial_prompt=None,
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    log.debug("Whisper duration=%.2fs lang=%s text=%r", info.duration, info.language, text)
    return text


# ---------------------------------------------------------------------------
# Sarvam (cloud)
# ---------------------------------------------------------------------------

def _load_sarvam() -> None:
    if not STT_SARVAM_API_KEY:
        raise RuntimeError(
            "STT_PROVIDER=sarvam but STT_SARVAM_API_KEY is empty. Set it in .env."
        )
    log.info("Sarvam STT ready (model=%s, lang=%s)", STT_SARVAM_MODEL, STT_SARVAM_LANGUAGE)


def _transcribe_sarvam(audio: np.ndarray, sample_rate: int) -> str:
    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)

    try:
        resp = requests.post(
            STT_SARVAM_URL,
            headers={"api-subscription-key": STT_SARVAM_API_KEY},
            files={"file": ("utterance.wav", buf, "audio/wav")},
            data={
                "model": STT_SARVAM_MODEL,
                "language_code": STT_SARVAM_LANGUAGE,
            },
            timeout=STT_SARVAM_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        log.error("Sarvam request failed: %s", exc)
        return ""

    if resp.status_code != 200:
        log.error("Sarvam HTTP %s: %s", resp.status_code, resp.text[:200])
        return ""

    try:
        data = resp.json()
    except ValueError:
        log.error("Sarvam non-JSON response: %s", resp.text[:200])
        return ""

    return (data.get("transcript") or "").strip()
