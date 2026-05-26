"""
tts.py — Text-to-Speech with provider abstraction (Kokoro local | Sarvam cloud)
and pipelined synth ↔ playback for low-gap multi-sentence delivery.

Public API:
    load()                                 — warm the active provider
    speak(text, cancel=None)               — single sentence; returns False on barge-in
    speak_stream(text_iter, cancel=None)   — pipeline-aware: synth-ahead while playing
    interrupted                            — Event set by barge-in monitor

Barge-in: a single InputStream watches mic energy during playback. When the user
starts speaking, `interrupted` is set, the current playback is stopped, AND any
shared `cancel` event passed in is set so upstream LLM calls bail out too.
"""

import base64
import io
import logging
import queue
import random
import threading
from typing import Iterable, Iterator, List, Optional, Tuple

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf

from .config import (
    TTS_PROVIDER,
    TTS_KOKORO_LANG,
    TTS_KOKORO_VOICE,
    TTS_KOKORO_SAMPLE_RATE,
    TTS_SARVAM_API_KEY,
    TTS_SARVAM_URL,
    TTS_SARVAM_MODEL,
    TTS_SARVAM_SPEAKER,
    TTS_SARVAM_LANGUAGE,
    TTS_SARVAM_SAMPLE_RATE,
    TTS_SARVAM_PITCH,
    TTS_SARVAM_PACE,
    TTS_SARVAM_LOUDNESS,
    TTS_SARVAM_TIMEOUT,
    TTS_ACK_ENABLED,
    TTS_ACK_PHRASES,
    TTS_BARGE_IN_THRESHOLD,
    TTS_BARGE_IN_CONFIRM_BLOCKS,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kokoro (local) — lazy init
# ---------------------------------------------------------------------------

_kokoro_pipeline = None


def _ensure_kokoro_loaded() -> None:
    global _kokoro_pipeline
    if _kokoro_pipeline is not None:
        return
    from kokoro import KPipeline
    log.info("Loading Kokoro pipeline...")
    _kokoro_pipeline = KPipeline(lang_code=TTS_KOKORO_LANG)
    log.info("Kokoro ready")


def _synthesize_kokoro(text: str) -> Iterator[Tuple[np.ndarray, int]]:
    _ensure_kokoro_loaded()
    for _g, _p, audio_chunk in _kokoro_pipeline(text, voice=TTS_KOKORO_VOICE):
        if audio_chunk is None or len(audio_chunk) == 0:
            continue
        yield audio_chunk, TTS_KOKORO_SAMPLE_RATE


# ---------------------------------------------------------------------------
# Sarvam (cloud)
# ---------------------------------------------------------------------------

def _synthesize_sarvam(text: str) -> Iterator[Tuple[np.ndarray, int]]:
    if not TTS_SARVAM_API_KEY:
        log.error("TTS_PROVIDER=sarvam but no API key set")
        return

    payload = {
        "inputs": [text],
        "target_language_code": TTS_SARVAM_LANGUAGE,
        "model": TTS_SARVAM_MODEL,
        "speaker": TTS_SARVAM_SPEAKER,
        "pitch": TTS_SARVAM_PITCH,
        "pace": TTS_SARVAM_PACE,
        "loudness": TTS_SARVAM_LOUDNESS,
        "speech_sample_rate": TTS_SARVAM_SAMPLE_RATE,
        "enable_preprocessing": True,
    }

    try:
        resp = requests.post(
            TTS_SARVAM_URL,
            json=payload,
            headers={"api-subscription-key": TTS_SARVAM_API_KEY},
            timeout=TTS_SARVAM_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        log.error("Sarvam request failed: %s", exc)
        return

    if resp.status_code != 200:
        log.error("Sarvam HTTP %s: %s", resp.status_code, resp.text[:200])
        return

    try:
        data = resp.json()
    except ValueError:
        log.error("Sarvam non-JSON response: %s", resp.text[:200])
        return

    for b64_audio in data.get("audios", []):
        try:
            wav_bytes = base64.b64decode(b64_audio)
            audio, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        except Exception as exc:
            log.error("Failed to decode Sarvam audio: %s", exc)
            continue
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        yield audio, int(sr)


def _synthesize(text: str) -> Iterator[Tuple[np.ndarray, int]]:
    if TTS_PROVIDER == "kokoro":
        yield from _synthesize_kokoro(text)
    elif TTS_PROVIDER == "sarvam":
        yield from _synthesize_sarvam(text)
    else:
        raise ValueError(f"Unknown TTS_PROVIDER: {TTS_PROVIDER!r}")


# ---------------------------------------------------------------------------
# Barge-in monitoring (provider-agnostic, single shared event)
# ---------------------------------------------------------------------------

interrupted = threading.Event()


class _BargeInMonitor:
    """Counts consecutive loud blocks; sets `interrupted` when over threshold."""

    def __init__(self) -> None:
        self._counter = 0

    def reset(self) -> None:
        self._counter = 0

    def __call__(self, indata, frames, time_info, status) -> None:
        rms = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
        if rms > TTS_BARGE_IN_THRESHOLD:
            self._counter += 1
            if self._counter >= TTS_BARGE_IN_CONFIRM_BLOCKS:
                interrupted.set()
        else:
            self._counter = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load() -> None:
    if TTS_PROVIDER == "kokoro":
        _ensure_kokoro_loaded()
    elif TTS_PROVIDER == "sarvam":
        if not TTS_SARVAM_API_KEY:
            raise RuntimeError("TTS_PROVIDER=sarvam but no API key set")
        log.info(
            "Sarvam TTS ready (model=%s, speaker=%s, lang=%s)",
            TTS_SARVAM_MODEL, TTS_SARVAM_SPEAKER, TTS_SARVAM_LANGUAGE,
        )
    else:
        raise ValueError(f"Unknown TTS_PROVIDER: {TTS_PROVIDER!r}")

    _prerender_acks()


# ---------------------------------------------------------------------------
# Wake-word acknowledgement — pre-rendered short replies for zero-latency reply
# ---------------------------------------------------------------------------

# Cached as (audio_array, sample_rate, phrase_text) tuples.
_ack_cache: List[Tuple[np.ndarray, int, str]] = []


def _prerender_acks() -> None:
    """Synthesize each ack phrase once and cache the audio for instant playback."""
    _ack_cache.clear()
    if not TTS_ACK_ENABLED:
        return
    for phrase in TTS_ACK_PHRASES:
        phrase = phrase.strip()
        if not phrase:
            continue
        try:
            parts: list[np.ndarray] = []
            sr = 0
            for audio_chunk, sample_rate in _synthesize(phrase):
                parts.append(audio_chunk)
                sr = sample_rate
            if not parts:
                log.warning("Ack phrase %r produced no audio", phrase)
                continue
            audio = np.concatenate(parts) if len(parts) > 1 else parts[0]
            _ack_cache.append((audio, sr, phrase))
        except Exception:
            log.exception("Failed to pre-render ack phrase: %s", phrase)
    log.info("Pre-rendered %d wake-ack phrase(s)", len(_ack_cache))


def speak_ack() -> bool:
    """
    Play a random pre-rendered acknowledgement. Returns True if something
    played, False if acks are disabled / nothing cached.

    This is fire-and-forget from the caller's point of view: it blocks until
    the short clip finishes (typically <500ms) so the next utterance can be
    captured cleanly. No barge-in monitor — the clips are short enough that
    interruption isn't worth the complexity.
    """
    if not _ack_cache:
        return False
    audio, sample_rate, phrase = random.choice(_ack_cache)
    log.info("Ack: %s", phrase)
    try:
        sd.play(audio, samplerate=sample_rate)
        sd.wait()
        return True
    except Exception:
        log.exception("Ack playback failed")
        return False


def speak(text: str, cancel: Optional[threading.Event] = None) -> bool:
    """Synthesize+play a single sentence. Returns False on barge-in."""
    return speak_stream([text], cancel=cancel)


def speak_stream(
    text_iter: Iterable[str],
    cancel: Optional[threading.Event] = None,
) -> bool:
    """
    Pipeline-aware playback over a sequence of text fragments.

    A producer thread synthesizes the next fragment while the current one plays,
    eliminating the inter-sentence audio gap. On barge-in, sets `interrupted`
    AND the caller-supplied `cancel` so upstream LLM streams stop too.

    Returns:
        True  — all fragments played to completion.
        False — interrupted (by user speech or external cancel).
    """
    interrupted.clear()
    monitor = _BargeInMonitor()

    # Bounded queue: producer at most 2 sentences ahead of the player.
    chunk_queue: "queue.Queue[Optional[Tuple[np.ndarray, int]]]" = queue.Queue(maxsize=8)
    producer_done = threading.Event()

    def _is_cancelled() -> bool:
        return interrupted.is_set() or (cancel is not None and cancel.is_set())

    def _producer() -> None:
        try:
            for text in text_iter:
                if _is_cancelled():
                    return
                if not text or not text.strip():
                    continue
                log.info("Speaking: %s%s", text[:80], "..." if len(text) > 80 else "")
                for audio_chunk, sample_rate in _synthesize(text):
                    if _is_cancelled():
                        return
                    chunk_queue.put((audio_chunk, sample_rate))
        except Exception as exc:
            log.exception("TTS producer failed: %s", exc)
        finally:
            producer_done.set()
            chunk_queue.put(None)  # sentinel

    producer_thread = threading.Thread(target=_producer, daemon=True)
    producer_thread.start()

    try:
        with sd.InputStream(
            samplerate=16_000,
            channels=1,
            dtype="float32",
            blocksize=512,
            callback=monitor,
            device=None,
        ):
            while True:
                if _is_cancelled():
                    sd.stop()
                    if cancel is not None and interrupted.is_set():
                        cancel.set()
                    log.info("TTS cancelled (barge-in or external)")
                    return False

                try:
                    item = chunk_queue.get(timeout=0.05)
                except queue.Empty:
                    if producer_done.is_set() and chunk_queue.empty():
                        break
                    continue

                if item is None:
                    break

                audio_chunk, sample_rate = item
                sd.play(audio_chunk, samplerate=sample_rate)
                while sd.get_stream().active:
                    if _is_cancelled():
                        sd.stop()
                        if cancel is not None and interrupted.is_set():
                            cancel.set()
                        log.info("TTS cancelled mid-chunk")
                        return False
                    interrupted.wait(timeout=0.01)

        log.info("TTS done")
        return True
    finally:
        # Drain any leftover chunks so the producer thread can exit.
        while not chunk_queue.empty():
            try:
                chunk_queue.get_nowait()
            except queue.Empty:
                break
