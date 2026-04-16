"""
llm.py — LM Studio / Gemma chat client with streaming support

Exposes:
  ask(user_text)            → full reply string (non-streaming, kept for compat)
  ask_stream(user_text)     → generator that yields text chunks as they arrive
  clear_history()           → wipe conversation history
"""

import json
import re
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LM_STUDIO_URL: str = "http://192.168.1.5:1234/v1/chat/completions"  # OpenAI-compat endpoint for streaming

LM_MODEL: str = "google/gemma-4-e4b"

SYSTEM_PROMPT: str = (
    "You are a voice assistant named Friday.\n\n"
    "Keep responses short, natural, and conversational.\n"
    "No markdown, no bullet points, no headers.\n"
    "Respond as you would speak out loud."
)

TEMPERATURE: float = 0.7
MAX_OUTPUT_TOKENS: int = 300
REQUEST_TIMEOUT: int = 30

# ---------------------------------------------------------------------------
# In-memory conversation history
# ---------------------------------------------------------------------------

_chat_history: list[dict] = []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ask(user_text: str) -> str:
    """Non-streaming: send user_text and return the full reply."""
    reply = "".join(ask_stream(user_text))
    return reply


def ask_stream(user_text: str):
    """
    Streaming generator: yields text chunks as the LLM produces them.

    The conversation history is updated once the stream completes.
    Each yielded chunk is a raw string fragment (may be partial words).

    Usage:
        for chunk in ask_stream("Hello"):
            print(chunk, end="", flush=True)
    """
    _chat_history.append({"role": "user", "content": user_text})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _chat_history

    payload = {
        "model": LM_MODEL,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": True,
    }

    full_reply = ""

    try:
        print(f"[LLM] → Streaming POST to {LM_STUDIO_URL}")
        with requests.post(
            LM_STUDIO_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
            stream=True,
        ) as response:
            if response.status_code != 200:
                err = f"[LLM error: HTTP {response.status_code}]"
                yield err
                return

            for line in response.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0]["delta"].get("content", "")
                        if delta:
                            full_reply += delta
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    except requests.exceptions.Timeout:
        err = f"[LLM error: timed out after {REQUEST_TIMEOUT}s]"
        yield err
        return
    except Exception as exc:
        err = f"[LLM error: {exc}]"
        yield err
        return

    # Append assistant turn after stream completes
    if full_reply:
        _chat_history.append({"role": "assistant", "content": full_reply})


def ask_stream_sentences(user_text: str):
    """
    Higher-level streaming generator that yields complete sentences.

    Each yielded string is a natural sentence boundary — ideal for piping
    directly into TTS so speech starts after the first sentence without
    waiting for the full reply.

    Yields: (sentence_text, is_last)
    """
    buffer = ""
    # Sentence-ending punctuation followed by space or end-of-string
    sentence_end = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')

    chunks = list(ask_stream(user_text))   # collect all for sentence splitting
    full = "".join(chunks)

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', full.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    for i, sentence in enumerate(sentences):
        yield sentence, i == len(sentences) - 1


def clear_history() -> None:
    _chat_history.clear()
    print("[LLM] Chat history cleared.")