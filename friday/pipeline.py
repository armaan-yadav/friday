"""
pipeline.py — Orchestrates STT → LLM → TTS for a single utterance.

`on_transcript()` is called by transcribe.py (or the HTTP /send-prompt endpoint)
once per recognised utterance. To prevent the STT loop from blocking during a
long reply, the heavy work is dispatched to a single worker thread; if a new
utterance arrives while the worker is mid-flight, the old one is cancelled.
"""

import json
import logging
import re
import threading
import time
from pathlib import Path

from .config import (
    SERVER_OUTPUT_JSON,
    STT_DANGLER_WORDS,
    STT_DANGLER_GRACE_PERIOD,
    STT_MERGE_WINDOW,
)
from . import transcribe
from . import llm
from . import tts

log = logging.getLogger(__name__)

_OUTPUT_PATH = Path(SERVER_OUTPUT_JSON)
_transcripts: list[dict] = []
_state_lock = threading.Lock()

# Single in-flight worker; new dispatches preempt the previous one.
_dispatch_lock = threading.Lock()
_current_thread: threading.Thread | None = None
_current_cancel: threading.Event | None = None

# Endpointing state — protected by _dispatch_lock.
# `_pending_text`: an utterance held back because it ended in a dangler word.
# `_pending_timer`: fires after STT_DANGLER_GRACE_PERIOD if no continuation comes.
# `_last_dispatch_text` / `_last_dispatch_time`: previous turn, used for merge.
_pending_text: str | None = None
_pending_timer: threading.Timer | None = None
_last_dispatch_text: str = ""
_last_dispatch_time: float = 0.0

_DANGLER_SET = {w.strip().lower() for w in STT_DANGLER_WORDS if w.strip()}
_LAST_WORD_RE = re.compile(r"([A-Za-z']+)[^A-Za-z']*$")

# Listeners notified after every state-file write (used by SSE).
_state_listeners: list = []


def add_state_listener(callback) -> None:
    """Register a no-arg callback fired after each `write_json()` call."""
    _state_listeners.append(callback)


def _fire_state_listeners() -> None:
    for cb in _state_listeners:
        try:
            cb()
        except Exception:
            log.exception("state listener failed")


def write_json(*, is_processing: bool = False, is_thinking: bool = False,
               partial_ai: str = "") -> None:
    payload = {
        "transcripts": _transcripts,
        "processing": is_processing,
        "thinking": is_thinking,
        "partial_ai": partial_ai,
        "muted": transcribe.is_muted(),
        "updated": time.time(),
    }
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    _fire_state_listeners()


def _run_pipeline(user_text: str, cancel: threading.Event) -> None:
    """Body of one pipeline turn. Runs on a worker thread."""
    write_json(is_thinking=True)
    log.info("→ LLM: %s", user_text)

    full_reply_parts: list[str] = []

    def sentence_iter():
        """Yields LLM-produced sentences and updates the UI as they arrive."""
        try:
            for sentence, is_last in llm.ask_stream_sentences(user_text, cancel=cancel):
                if cancel.is_set():
                    return
                if not sentence:
                    continue
                full_reply_parts.append(sentence)
                partial = " ".join(full_reply_parts)
                write_json(is_thinking=not is_last, partial_ai=partial)
                log.debug("← chunk: %s", sentence)
                yield sentence
        except Exception:
            log.exception("LLM stream failed")

    try:
        # Pause mic capture so TTS audio doesn't get re-transcribed (echo).
        # The barge-in monitor inside tts.speak_stream still listens via its
        # own short-lived InputStream and will set `cancel` if the user speaks.
        transcribe.pause_capture()
        tts.speak_stream(sentence_iter(), cancel=cancel)
    finally:
        transcribe.resume_capture()
        # Reset the conversation-timeout clock so the post-reply window
        # measures from Friday's last word, not the user's. Without this,
        # long replies eat into the follow-up window and force a re-wake.
        transcribe.mark_activity()

    full_reply = " ".join(full_reply_parts).strip()
    log.info("← LLM full (%d chars)", len(full_reply))

    if cancel.is_set() and not full_reply:
        # Nothing useful to record.
        write_json()
        return

    with _state_lock:
        _transcripts.append({
            "user": user_text,
            "ai": full_reply,
            "time": time.strftime("%H:%M:%S"),
            "timestamp": time.time(),
        })
    write_json()


def _ends_with_dangler(text: str) -> bool:
    """True if the last word looks like an incomplete-sentence dangler."""
    if not text:
        return False
    # Trailing comma/dash also means "more coming".
    stripped = text.rstrip()
    if stripped.endswith((",", "-", "—", "–")):
        return True
    m = _LAST_WORD_RE.search(stripped)
    if not m:
        return False
    return m.group(1).lower() in _DANGLER_SET


def _start_worker_locked(user_text: str) -> None:
    """Spin up a fresh pipeline worker. Caller must hold _dispatch_lock."""
    global _current_thread, _current_cancel, _last_dispatch_text, _last_dispatch_time
    if _current_thread and _current_thread.is_alive():
        log.info("Cancelling previous turn for new utterance")
        assert _current_cancel is not None
        _current_cancel.set()
        _current_thread.join(timeout=2.0)

    _current_cancel = threading.Event()
    _current_thread = threading.Thread(
        target=_run_pipeline,
        args=(user_text, _current_cancel),
        daemon=True,
    )
    _last_dispatch_text = user_text
    _last_dispatch_time = time.time()
    _current_thread.start()


def _flush_pending() -> None:
    """Timer callback: grace period elapsed with no continuation, fire as-is."""
    global _pending_text, _pending_timer
    with _dispatch_lock:
        if _pending_text is None:
            return
        text = _pending_text
        _pending_text = None
        _pending_timer = None
        log.info("Dangler grace expired, dispatching: %s", text)
        _start_worker_locked(text)


def on_transcript(user_text: str) -> None:
    """
    Dispatch an utterance through the pipeline with semantic endpointing:
      1. If a previous utterance was held back as "incomplete", combine.
      2. If the (combined) text still ends in a dangler, hold it briefly to
         allow a continuation to merge before firing the LLM.
      3. If the previous turn dispatched <STT_MERGE_WINDOW ago, cancel it and
         resubmit as one combined utterance.
    """
    global _pending_text, _pending_timer, _last_dispatch_text, _last_dispatch_time

    with _dispatch_lock:
        # (1) A continuation is arriving for a held-back dangler.
        if _pending_text is not None:
            if _pending_timer is not None:
                _pending_timer.cancel()
                _pending_timer = None
            combined = f"{_pending_text} {user_text}".strip()
            log.info("Merging continuation: %r + %r", _pending_text, user_text)
            _pending_text = None
            user_text = combined

        # (3) Quick follow-up to an already-dispatched turn → cancel + merge.
        elif (
            _last_dispatch_text
            and (time.time() - _last_dispatch_time) < STT_MERGE_WINDOW
            and _current_thread
            and _current_thread.is_alive()
        ):
            log.info(
                "Quick follow-up (%.2fs), merging: %r + %r",
                time.time() - _last_dispatch_time, _last_dispatch_text, user_text,
            )
            user_text = f"{_last_dispatch_text} {user_text}".strip()

        # (2) Still incomplete? Hold and wait for a continuation.
        if _ends_with_dangler(user_text):
            log.info(
                "Held back (dangler, grace %.1fs): %s",
                STT_DANGLER_GRACE_PERIOD, user_text,
            )
            _pending_text = user_text
            _pending_timer = threading.Timer(STT_DANGLER_GRACE_PERIOD, _flush_pending)
            _pending_timer.daemon = True
            _pending_timer.start()
            return

        _start_worker_locked(user_text)
