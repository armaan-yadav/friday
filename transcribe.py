"""
transcribe.py — Real-time Speech-to-Text via faster-whisper

UPDATED FEATURES:
  - Wake-word required only once per session ("Hey Friday")
  - Conversation mode stays active until silence timeout
  - Auto-sleep after inactivity
  - Mute flag support
  - Voice activity detection (RMS-based)
"""

import os
import queue
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_SIZE: str = "large-v3"
LANGUAGE: str = "hi"
TASK: str = "translate"
SAMPLE_RATE: int = 16_000
WHISPER_DEVICE: str = "cuda"
COMPUTE_TYPE: str = "float16"

# ---------------------------------------------------------------------------
# Wake-word configuration
# ---------------------------------------------------------------------------

WAKE_WORDS: list[str] = ["hey friday"]
WAKE_WORD_TIMEOUT: float = 8.0

# ---------------------------------------------------------------------------
# Conversation mode
# ---------------------------------------------------------------------------

CONVERSATION_TIMEOUT: float = 12.0  # seconds before going back to sleep

# ---------------------------------------------------------------------------
# Mute flag
# ---------------------------------------------------------------------------

MUTE_FLAG_PATH: str = "muted.flag"

# ---------------------------------------------------------------------------
# Voice Activity Detection
# ---------------------------------------------------------------------------

SILENCE_THRESHOLD: float = 0.01
SILENCE_DURATION: float = 1.5
MIN_SPEECH_DURATION: float = 0.5
BLOCK_SIZE: int = int(0.1 * SAMPLE_RATE)

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_audio_queue: queue.Queue = queue.Queue()
_model: WhisperModel | None = None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_muted() -> bool:
    return os.path.exists(MUTE_FLAG_PATH)


def set_muted(muted: bool) -> None:
    if muted:
        open(MUTE_FLAG_PATH, "w").close()
    else:
        try:
            os.remove(MUTE_FLAG_PATH)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_model() -> None:
    global _model
    if _model is not None:
        print("[STT] Model already loaded.")
        return

    print(f"[STT] Loading Whisper '{MODEL_SIZE}' on {WHISPER_DEVICE} ({COMPUTE_TYPE})…")
    _model = WhisperModel(MODEL_SIZE, device=WHISPER_DEVICE, compute_type=COMPUTE_TYPE)
    print("[STT] Whisper ready.")


def start(on_transcript: Callable[[str], None]) -> None:
    if _model is None:
        raise RuntimeError("Call load_model() before start().")

    worker = threading.Thread(
        target=_transcription_loop,
        args=(on_transcript,),
        daemon=True,
    )
    worker.start()

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=BLOCK_SIZE,
        callback=_audio_callback,
    ):
        print("[STT] 🎤 Listening... Say 'Hey Friday' to wake.\n")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n[STT] Stopped.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _audio_callback(indata, frames, time_info, status):
    if status:
        print(f"[STT] sounddevice status: {status}")
    _audio_queue.put(indata.copy())


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio ** 2)))


def _contains_wake_word(text: str) -> bool:
    text_lower = text.lower()
    return any(w in text_lower for w in WAKE_WORDS)


def _strip_wake_word(text: str) -> str:
    text_lower = text.lower()
    for w in WAKE_WORDS:
        idx = text_lower.find(w)
        if idx != -1:
            remainder = text[idx + len(w):].strip().lstrip(",. ")
            return remainder
    return text


def _collect_utterance(max_duration: float = 15.0) -> np.ndarray:
    speech_buffer = np.array([], dtype=np.float32)
    silence_sample_count = 0
    silence_sample_limit = int(SILENCE_DURATION * SAMPLE_RATE)
    max_samples = int(max_duration * SAMPLE_RATE)

    while len(speech_buffer) < max_samples:
        try:
            block = _audio_queue.get(timeout=0.5)
        except queue.Empty:
            break

        mono = block[:, 0]

        if _rms(mono) > SILENCE_THRESHOLD:
            speech_buffer = np.append(speech_buffer, mono)
            silence_sample_count = 0
        elif len(speech_buffer) > 0:
            silence_sample_count += len(mono)
            speech_buffer = np.append(speech_buffer, mono)

            if silence_sample_count >= silence_sample_limit:
                break

    return speech_buffer


# ---------------------------------------------------------------------------
# MAIN LOOP (UPDATED)
# ---------------------------------------------------------------------------

def _transcription_loop(on_transcript: Callable[[str], None]) -> None:
    print("[STT] Idle mode. Waiting for wake word...")

    speech_buffer = np.array([], dtype=np.float32)
    silence_sample_count = 0
    silence_sample_limit = int(SILENCE_DURATION * SAMPLE_RATE)

    # 🔥 NEW STATE
    is_active = False
    last_activity_time = 0.0

    while True:
        # Auto sleep
        if is_active and (time.time() - last_activity_time > CONVERSATION_TIMEOUT):
            print("[STT] 🔴 Sleeping... Say 'Hey Friday' to wake.")
            is_active = False

        try:
            block = _audio_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if is_muted():
            while not _audio_queue.empty():
                try:
                    _audio_queue.get_nowait()
                except queue.Empty:
                    break
            speech_buffer = np.array([], dtype=np.float32)
            silence_sample_count = 0
            continue

        mono = block[:, 0]

        if _rms(mono) > SILENCE_THRESHOLD:
            speech_buffer = np.append(speech_buffer, mono)
            silence_sample_count = 0

        elif len(speech_buffer) > 0:
            silence_sample_count += len(mono)
            speech_buffer = np.append(speech_buffer, mono)

            if silence_sample_count >= silence_sample_limit:
                duration_sec = len(speech_buffer) / SAMPLE_RATE

                if duration_sec >= MIN_SPEECH_DURATION:
                    print("[STT] Processing speech...")

                    segments, _ = _model.transcribe(
                        speech_buffer,
                        language=LANGUAGE,
                        task=TASK,
                        beam_size=2,
                        vad_filter=True,
                    )

                    text = " ".join(seg.text.strip() for seg in segments).strip()
                    print(f"[STT] Heard: {text}")

                    current_time = time.time()

                    # 🔥 ACTIVE MODE
                    if is_active:
                        if text:
                            print(f"[STT] 🎙 You: {text}")
                            on_transcript(text)
                            last_activity_time = current_time

                    # 🔥 WAKE WORD
                    elif _contains_wake_word(text):
                        print("[STT] 🟢 Wake word detected!")
                        is_active = True
                        last_activity_time = current_time

                        query = _strip_wake_word(text).strip()

                        if len(query) > 2:
                            print(f"[STT] 🎙 You: {query}")
                            on_transcript(query)
                        else:
                            print("[STT] Waiting for query...")
                            query_audio = _collect_utterance(WAKE_WORD_TIMEOUT)

                            if len(query_audio) / SAMPLE_RATE >= MIN_SPEECH_DURATION:
                                _transcribe_and_callback(query_audio, on_transcript)

                    else:
                        print("[STT] Ignored (no wake word).")

                speech_buffer = np.array([], dtype=np.float32)
                silence_sample_count = 0


def _transcribe_and_callback(audio: np.ndarray, on_transcript: Callable[[str], None]) -> None:
    print("[STT] Transcribing query...")

    segments, _ = _model.transcribe(
        audio,
        language=LANGUAGE,
        task=TASK,
        beam_size=5,
        vad_filter=True,
    )

    text = " ".join(seg.text.strip() for seg in segments).strip()

    if text:
        print(f"[STT] 🎙 You: {text}")
        on_transcript(text)
    else:
        print("[STT] Empty transcription.")

