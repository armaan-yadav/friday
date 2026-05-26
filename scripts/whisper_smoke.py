"""
whisper_smoke.py — Real-time Whisper STT smoke test.

Captures from the auto-detected mic continuously, detects speech with a simple
RMS gate, transcribes each utterance with faster-whisper, and prints the
result to the terminal. No dependency on the `friday` package — only reads
the same `.env` so model size / language / device match your assistant config.

Usage:
    uv run python scripts/whisper_smoke.py
    uv run python scripts/whisper_smoke.py --threshold 0.05
    uv run python scripts/whisper_smoke.py --device 4
    uv run python scripts/whisper_smoke.py --list
    uv run python scripts/whisper_smoke.py --once --seconds 5     # legacy fixed-window mode

Stop with Ctrl+C.
"""

import argparse
import os
import queue
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

SAMPLE_RATE = int(os.getenv("STT_SAMPLE_RATE", "16000"))
BLOCK_SIZE = int(os.getenv("STT_BLOCK_SIZE", "1600"))
MODEL_SIZE = os.getenv("STT_MODEL_SIZE", "base")
DEVICE = os.getenv("STT_WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "int8")
LANGUAGE = os.getenv("STT_LANGUAGE", "en")
TASK = os.getenv("STT_TASK", "transcribe")
SILENCE_THRESHOLD = float(os.getenv("STT_SILENCE_THRESHOLD", "0.04"))
SILENCE_DURATION = float(os.getenv("STT_SILENCE_DURATION", "0.8"))
MIN_SPEECH_DURATION = float(os.getenv("STT_MIN_SPEECH_DURATION", "0.5"))


# ---------------------------------------------------------------------------
# Mic auto-detect
# ---------------------------------------------------------------------------

def list_devices() -> None:
    print(f"{'idx':>3}  {'in':>3} {'out':>3}  name")
    for i, info in enumerate(sd.query_devices()):
        print(f"{i:>3}  {info['max_input_channels']:>3} {info['max_output_channels']:>3}  {info['name']}")


def probe(idx: int, listen_ms: int = 400) -> bool:
    captured: list[np.ndarray] = []

    def cb(indata, frames, time_info, status):
        captured.append(indata[:, 0].copy())

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=BLOCK_SIZE, device=idx, callback=cb):
            time.sleep(listen_ms / 1000.0)
    except Exception:
        return False
    if not captured:
        return False
    sample = np.concatenate(captured)
    return sample.size > 0 and float(np.max(np.abs(sample))) > 0.0


def auto_pick_device() -> int | None:
    preferred = ("pipewire", "pulse", "default")

    def priority(name: str) -> int:
        n = name.lower()
        for p, key in enumerate(preferred):
            if key in n:
                return p
        return len(preferred)

    candidates = [
        (priority(info["name"]), i, info["name"])
        for i, info in enumerate(sd.query_devices())
        if info.get("max_input_channels", 0) > 0
    ]
    candidates.sort()
    for _, idx, name in candidates:
        if probe(idx):
            print(f"[mic] selected [{idx}] {name}")
            return idx
        print(f"[mic] skipped  [{idx}] {name} (silent or refused to open)")
    return None


# ---------------------------------------------------------------------------
# Whisper
# ---------------------------------------------------------------------------

_MODEL = None


def load_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    from faster_whisper import WhisperModel
    print(f"[stt] loading whisper '{MODEL_SIZE}' on {DEVICE} ({COMPUTE_TYPE})...")
    t0 = time.time()
    _MODEL = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    print(f"[stt] loaded in {time.time()-t0:.1f}s")
    return _MODEL


def transcribe(audio: np.ndarray, beam_size: int = 5) -> tuple[str, float]:
    model = load_model()
    t0 = time.time()
    segments, _info = model.transcribe(
        audio,
        language=LANGUAGE,
        task=TASK,
        beam_size=beam_size,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, time.time() - t0


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def fixed_window(device: int | None, seconds: float) -> int:
    """Legacy mode: record N seconds, transcribe, exit."""
    chunks: list[np.ndarray] = []

    def cb(indata, frames, time_info, status):
        chunks.append(indata[:, 0].copy())

    print(f"[rec] recording {seconds:.1f}s — speak now...")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=BLOCK_SIZE, device=device, callback=cb):
        time.sleep(seconds)
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    print(f"[rec] done — {len(audio)/SAMPLE_RATE:.2f}s, peak={peak:.4f}")
    if peak == 0.0:
        print("[rec] captured silence — check your mic", file=sys.stderr)
        return 1
    text, dt = transcribe(audio)
    print(f"[stt] {dt:.2f}s")
    print(f"  → {text!r}" if text else "  → (empty)")
    return 0


def realtime(device: int | None, threshold: float) -> int:
    """Continuous capture: print each utterance as it ends."""
    load_model()  # warm before opening the stream

    audio_q: queue.Queue[np.ndarray] = queue.Queue()
    heartbeat = {"count": 0, "peak": 0.0}

    def cb(indata, frames, time_info, status):
        block = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(block ** 2)))
        if rms > heartbeat["peak"]:
            heartbeat["peak"] = rms
        heartbeat["count"] += 1
        if heartbeat["count"] >= 50:  # ~5s at 100ms blocks
            print(f"[mic] {heartbeat['count']} blocks, peak rms={heartbeat['peak']:.4f}")
            heartbeat["count"] = 0
            heartbeat["peak"] = 0.0
        audio_q.put(block)

    silence_limit = int(SILENCE_DURATION * SAMPLE_RATE)
    max_samples = int(15.0 * SAMPLE_RATE)

    print(f"[run] real-time mode — threshold={threshold:.3f}, "
          f"silence_duration={SILENCE_DURATION:.1f}s, "
          f"min_speech={MIN_SPEECH_DURATION:.1f}s")
    print("[run] speak now (Ctrl+C to quit)\n")

    chunks: list[np.ndarray] = []
    silent_samples = 0

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=BLOCK_SIZE, device=device, callback=cb):
        try:
            while True:
                try:
                    block = audio_q.get(timeout=0.5)
                except queue.Empty:
                    continue

                rms = float(np.sqrt(np.mean(block ** 2)))

                if rms > threshold:
                    if not chunks:
                        ts = time.strftime("%H:%M:%S")
                        print(f"[{ts}] speech started (rms={rms:.4f})")
                    chunks.append(block)
                    silent_samples = 0
                    if sum(len(c) for c in chunks) < max_samples:
                        continue
                    print(f"[{time.strftime('%H:%M:%S')}] hit max length, forcing close")
                else:
                    if not chunks:
                        continue
                    chunks.append(block)
                    silent_samples += len(block)
                    if silent_samples < silence_limit:
                        continue

                # utterance complete
                utterance = np.concatenate(chunks)
                chunks.clear()
                silent_samples = 0
                duration = len(utterance) / SAMPLE_RATE
                peak = float(np.max(np.abs(utterance)))

                if duration < MIN_SPEECH_DURATION:
                    print(f"[{time.strftime('%H:%M:%S')}] too short ({duration:.2f}s), discarded")
                    continue

                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] transcribing {duration:.2f}s (peak={peak:.4f})...")
                text, dt = transcribe(utterance)
                if text:
                    print(f"[{ts}] → {text}  ({dt:.2f}s)\n")
                else:
                    print(f"[{ts}] → (empty)  ({dt:.2f}s)\n")

        except KeyboardInterrupt:
            print("\n[run] stopped")
            return 0


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list audio devices and exit")
    ap.add_argument("--device", type=int, default=None, help="explicit input device index")
    ap.add_argument("--threshold", type=float, default=SILENCE_THRESHOLD,
                    help="RMS gate (default from .env or 0.04)")
    ap.add_argument("--once", action="store_true", help="legacy fixed-window mode")
    ap.add_argument("--seconds", type=float, default=5.0, help="length for --once")
    args = ap.parse_args()

    if args.list:
        list_devices()
        return 0

    device = args.device if args.device is not None else auto_pick_device()
    if device is None and args.device is None:
        print("[mic] no working capture device found", file=sys.stderr)
        return 1

    if args.once:
        return fixed_window(device, args.seconds)
    return realtime(device, args.threshold)


if __name__ == "__main__":
    sys.exit(main())
