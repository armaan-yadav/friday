"""
tts.py — Text-to-Speech via Kokoro with barge-in support

Responsibilities:
  - Initialise the Kokoro TTS pipeline once at import time
  - speak(text) synthesises audio chunk-by-chunk and plays each chunk
    immediately so the user hears the first words without delay
  - While playing, a background mic monitor watches for user speech;
    if the user starts talking the playback is interrupted (barge-in)

Barge-in works by opening a second, low-latency InputStream just for
monitoring (not recording) during playback.  The moment RMS energy on
that stream exceeds BARGE_IN_THRESHOLD for enough consecutive blocks,
sd.play() is stopped and speak() returns False, letting the STT pipeline
pick up from the audio already sitting in its queue.

Dependencies: kokoro, sounddevice, numpy
"""

import threading
import numpy as np
import sounddevice as sd
from kokoro import KPipeline

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KOKORO_LANG        = "a"          # 'a' = American English
KOKORO_VOICE       = "af_heart"   # warm female voice
KOKORO_SAMPLE_RATE = 24_000       # Kokoro always outputs 24 kHz

# RMS energy on the mic that counts as "user is speaking".
# Raise this if speaker bleed-through triggers false interrupts;
# lower it if you have to shout to be heard.
BARGE_IN_THRESHOLD = 0.02

# How many consecutive loud blocks are required before we interrupt.
# 1 = hair-trigger; 3 ~= 30 ms of speech needed (fewer false positives).
BARGE_IN_CONFIRM_BLOCKS = 3

# ---------------------------------------------------------------------------
# One-time pipeline initialisation
# ---------------------------------------------------------------------------

print("[TTS] Loading Kokoro pipeline...")
_pipeline = KPipeline(lang_code=KOKORO_LANG)
print("[TTS] Kokoro ready.")

# ---------------------------------------------------------------------------
# Internal barge-in state
# ---------------------------------------------------------------------------

# Set by the mic monitor when user speech is detected mid-playback.
_interrupted = threading.Event()


def _mic_monitor_callback(indata, frames, time_info, status):
    """
    sounddevice InputStream callback that runs while TTS audio is playing.

    Counts consecutive loud blocks; once BARGE_IN_CONFIRM_BLOCKS are
    reached it sets _interrupted, which causes speak() to halt playback.
    """
    counter = _mic_monitor_callback._counter
    rms = float(np.sqrt(np.mean(indata[:, 0] ** 2)))

    if rms > BARGE_IN_THRESHOLD:
        counter[0] += 1
        if counter[0] >= BARGE_IN_CONFIRM_BLOCKS:
            _interrupted.set()
    else:
        counter[0] = 0

_mic_monitor_callback._counter = [0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def speak(text: str) -> bool:
    """
    Convert *text* to speech and play it back chunk by chunk.

    While playing, the microphone is monitored for barge-in: if the user
    starts speaking, playback stops immediately and this function returns
    False so the caller knows the response was cut short.

    Args:
        text: The string to be spoken aloud.

    Returns:
        True  -- playback completed in full.
        False -- playback was interrupted by user speech (barge-in).
    """
    if not text or not text.strip():
        return True

    print(f"[TTS] Speaking: {text[:80]}{'...' if len(text) > 80 else ''}")

    # Reset interrupt flag and loud-block counter before each utterance.
    _interrupted.clear()
    _mic_monitor_callback._counter[0] = 0

    # Open a lightweight mic stream just for barge-in detection.
    with sd.InputStream(
        samplerate=16_000,
        channels=1,
        dtype="float32",
        blocksize=512,          # ~32 ms per callback block
        callback=_mic_monitor_callback,
        device=None,
    ):
        for _graphemes, _phonemes, audio_chunk in _pipeline(text, voice=KOKORO_VOICE):
            if audio_chunk is None or len(audio_chunk) == 0:
                continue

            # Check barge-in before starting each new chunk.
            if _interrupted.is_set():
                sd.stop()
                print("[TTS] Interrupted before chunk -- user speaking.")
                return False

            # Start playing this chunk (non-blocking internally).
            sd.play(audio_chunk, samplerate=KOKORO_SAMPLE_RATE)

            # Poll every 10 ms so we can interrupt mid-chunk.
            while sd.get_stream().active:
                if _interrupted.is_set():
                    sd.stop()
                    print("[TTS] Interrupted mid-chunk -- user speaking.")
                    return False
                _interrupted.wait(timeout=0.01)

    print("[TTS] Done speaking.")
    return True