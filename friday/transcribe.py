"""
transcribe.py — Plain Whisper STT loop.

Owns the microphone, gates audio with simple RMS, hands utterances to
faster-whisper (via stt.py), and matches the wake word as a text substring.
No silero-vad, no openWakeWord, no extras.

Public API:
    is_muted() / set_muted(bool)
    pause_capture() / resume_capture()
    load_model()
    start(on_transcript)
"""

import logging
import os
import queue
import re
import threading
import time
from typing import Callable, List

import numpy as np
import sounddevice as sd

from . import stt
from . import tts
from .config import (
    STT_SAMPLE_RATE,
    STT_CONVERSATION_TIMEOUT,
    STT_SILENCE_THRESHOLD,
    STT_SILENCE_DURATION,
    STT_MIN_SPEECH_DURATION,
    STT_MIN_SPEECH_DURATION_IDLE,
    STT_BLOCK_SIZE,
    STT_WAKE_WORDS,
    STT_WAKE_FUZZY_THRESHOLD,
    SERVER_MUTE_FLAG_PATH,
)

try:
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # graceful fallback — exact substring match only
    _rf_fuzz = None

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_audio_queue: "queue.Queue[np.ndarray]" = queue.Queue()
_capture_paused = threading.Event()

# Timestamp of the most recent "the conversation is alive" event.
# Updated when the user speaks, when the ack finishes, and (crucially) when
# Friday's TTS reply finishes — so the post-reply silence window measures
# from Friday's last word, not the user's. Read by `_loop` to decide when
# to drop back to idle.
_last_activity: float = 0.0

_HEARTBEAT_EVERY = 50  # ~5 s at 100 ms blocks
_heartbeat_counter = 0
_heartbeat_max_rms = 0.0


def mark_activity() -> None:
    """Reset the conversation-timeout clock. Call from pipeline after TTS ends."""
    global _last_activity
    _last_activity = time.time()


# ---------------------------------------------------------------------------
# Mute flag (file on disk so it survives restarts)
# ---------------------------------------------------------------------------

def is_muted() -> bool:
    return os.path.exists(SERVER_MUTE_FLAG_PATH)


def set_muted(muted: bool) -> None:
    if muted:
        os.makedirs(os.path.dirname(SERVER_MUTE_FLAG_PATH) or ".", exist_ok=True)
        open(SERVER_MUTE_FLAG_PATH, "w").close()
    else:
        try:
            os.remove(SERVER_MUTE_FLAG_PATH)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Capture pause/resume — called by tts.py to prevent self-echo
# ---------------------------------------------------------------------------

def pause_capture() -> None:
    _capture_paused.set()


def resume_capture() -> None:
    _capture_paused.clear()
    drained = 0
    while True:
        try:
            _audio_queue.get_nowait()
            drained += 1
        except queue.Empty:
            break
    if drained:
        log.debug("Drained %d stale blocks on resume", drained)


# ---------------------------------------------------------------------------
# Mic auto-detect
# ---------------------------------------------------------------------------

def _probe_device(idx: int, listen_ms: int = 400) -> bool:
    captured: List[np.ndarray] = []

    def cb(indata, frames, time_info, status):
        captured.append(indata[:, 0].copy())

    try:
        with sd.InputStream(
            samplerate=STT_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=STT_BLOCK_SIZE,
            device=idx,
            callback=cb,
        ):
            time.sleep(listen_ms / 1000.0)
    except Exception:
        return False
    if not captured:
        return False
    sample = np.concatenate(captured)
    return sample.size > 0 and float(np.max(np.abs(sample))) > 0.0


def _resolve_input_device():
    try:
        devices = list(sd.query_devices())
    except Exception as exc:
        log.warning("Could not query audio devices: %s", exc)
        return None

    preferred = ("pipewire", "pulse", "default")

    def priority(name: str) -> int:
        n = name.lower()
        for p, key in enumerate(preferred):
            if key in n:
                return p
        return len(preferred)

    candidates = [
        (priority(info["name"]), i, info["name"])
        for i, info in enumerate(devices)
        if info.get("max_input_channels", 0) > 0
    ]
    candidates.sort()

    for _, idx, name in candidates:
        if _probe_device(idx):
            log.info("Auto-selected input device: [%d] %s", idx, name)
            return idx
        log.info("Skipping unusable device [%d] %s", idx, name)

    log.warning("No working capture device found; using system default")
    return None


# ---------------------------------------------------------------------------
# Wake word — plain text substring (punctuation-tolerant)
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    cleaned = _PUNCT_RE.sub(" ", (text or "").lower())
    return _WS_RE.sub(" ", cleaned).strip()


def _wake_match(text: str) -> tuple[bool, str, int]:
    """
    Return (matched, matched_phrase, score).

    Matching is two-pass:
      1) Exact normalised substring (fast path, score=100).
      2) rapidfuzz partial_ratio over each variant (handles "fryday", "friady",
         "friday's" by tolerating insert/delete/substitute up to threshold).

    `matched_phrase` is the normalised wake variant that hit, used by the
    stripper to find and remove it from the original transcript.
    """
    norm = _normalise(text)
    if not norm:
        return False, "", 0

    # Pass 1 — exact substring (cheap, handles most clean cases).
    for w in STT_WAKE_WORDS:
        wn = _normalise(w)
        if wn and wn in norm:
            return True, wn, 100

    # Pass 2 — fuzzy. Only useful if rapidfuzz is available.
    if _rf_fuzz is None:
        return False, "", 0

    best_score = 0
    best_phrase = ""
    for w in STT_WAKE_WORDS:
        wn = _normalise(w)
        if not wn:
            continue
        score = _rf_fuzz.partial_ratio(wn, norm)
        if score > best_score:
            best_score, best_phrase = int(score), wn
    return (best_score >= STT_WAKE_FUZZY_THRESHOLD, best_phrase, best_score)


def _has_wake_word(text: str) -> bool:
    matched, _, _ = _wake_match(text)
    return matched


def _strip_wake_word(text: str) -> str:
    """
    Remove the matched wake portion from `text`. Tries exact substring on the
    normalised string first; if the match was fuzzy (i.e. exact substring
    doesn't exist), falls back to dropping the leading word(s) of the
    transcript — the wake word is almost always at the start of an utterance.
    """
    matched, phrase, score = _wake_match(text)
    norm = _normalise(text)
    if not matched:
        return text
    idx = norm.find(phrase)
    if idx != -1:
        return norm[idx + len(phrase):].strip()
    # Fuzzy hit, no exact substring. Strip the first N tokens of the
    # transcript where N == the number of words in the wake phrase.
    n_wake_tokens = max(1, len(phrase.split()))
    tokens = norm.split()
    return " ".join(tokens[n_wake_tokens:]).strip()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def load_model() -> None:
    stt.load()


def start(on_transcript: Callable[[str], None]) -> None:
    device = _resolve_input_device()
    threading.Thread(
        target=_loop,
        args=(on_transcript,),
        daemon=True,
    ).start()

    with sd.InputStream(
        samplerate=STT_SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=STT_BLOCK_SIZE,
        callback=_audio_callback,
        device=device,
    ):
        log.info("Listening (say a wake word to begin)")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("Stopped by user")


# ---------------------------------------------------------------------------
# PortAudio callback
# ---------------------------------------------------------------------------

def _audio_callback(indata, frames, time_info, status) -> None:
    global _heartbeat_counter, _heartbeat_max_rms
    if status:
        log.warning("sounddevice status: %s", status)
    if _capture_paused.is_set():
        return

    block_rms = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
    if block_rms > _heartbeat_max_rms:
        _heartbeat_max_rms = block_rms
    _heartbeat_counter += 1
    if _heartbeat_counter >= _HEARTBEAT_EVERY:
        log.info("[mic] %d blocks, peak rms=%.4f",
                 _heartbeat_counter, _heartbeat_max_rms)
        _heartbeat_counter = 0
        _heartbeat_max_rms = 0.0

    _audio_queue.put(indata.copy())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio ** 2)))


def _samples_in(chunks: List[np.ndarray]) -> int:
    return sum(len(c) for c in chunks)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _loop(on_transcript: Callable[[str], None]) -> None:
    log.info("Idle. Waiting for wake word.")

    chunks: List[np.ndarray] = []
    silent_samples = 0
    silence_limit = int(STT_SILENCE_DURATION * STT_SAMPLE_RATE)
    max_utterance_samples = int(15.0 * STT_SAMPLE_RATE)  # safety cap
    is_active = False

    while True:
        if is_active and time.time() - _last_activity > STT_CONVERSATION_TIMEOUT:
            log.info("Sleeping (timeout). Waiting for wake word.")
            is_active = False

        try:
            block = _audio_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if is_muted():
            chunks.clear()
            silent_samples = 0
            continue

        mono = block[:, 0] if block.ndim > 1 else block
        block_rms = _rms(mono)

        if block_rms > STT_SILENCE_THRESHOLD:
            if not chunks:
                log.info("Speech started (rms=%.4f)", block_rms)
            chunks.append(mono)
            silent_samples = 0
            if _samples_in(chunks) < max_utterance_samples:
                continue
            log.info("Utterance hit max length, forcing close")
        else:
            if not chunks:
                continue
            chunks.append(mono)
            silent_samples += len(mono)
            if silent_samples < silence_limit:
                continue

        utterance = np.concatenate(chunks)
        chunks.clear()
        silent_samples = 0
        duration = len(utterance) / STT_SAMPLE_RATE

        # While idle (waiting for wake), accept much shorter clips so a quick
        # "Friday!" by itself isn't thrown away.
        min_duration = (
            STT_MIN_SPEECH_DURATION if is_active else STT_MIN_SPEECH_DURATION_IDLE
        )
        if duration < min_duration:
            log.info("Utterance too short (%.2fs), discarded", duration)
            continue

        log.info("Transcribing %.2fs...", duration)
        text = stt.transcribe(utterance, STT_SAMPLE_RATE, beam_size=5)
        if not text:
            log.warning("Whisper empty for %.2fs of audio", duration)
            continue
        log.info("Heard: %s", text)
        now = time.time()

        if is_active:
            log.info("You: %s", text)
            mark_activity()
            on_transcript(text)
            continue

        matched, phrase, score = _wake_match(text)
        if matched:
            log.info("Wake fired (matched %r, score=%d)", phrase, score)
            is_active = True
            mark_activity()
            query = _strip_wake_word(text).strip()
            if len(query) > 2:
                log.info("You: %s", query)
                on_transcript(query)
            else:
                # Bare wake word — give a short audible ack so the user knows
                # we're listening. Pause mic during playback so the ack doesn't
                # get re-transcribed as a self-echo.
                pause_capture()
                try:
                    tts.speak_ack()
                finally:
                    resume_capture()
                # Restart the 25s window from when the user *heard* the ack.
                mark_activity()
        else:
            # Visible miss log: shows what Whisper actually heard and how
            # close the best wake variant came. Feed real misses back into
            # STT_WAKE_WORDS to widen coverage.
            log.info("Heard but no wake match (best score=%d): %r", score, text)
