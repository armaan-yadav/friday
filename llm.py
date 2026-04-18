"""
llm.py — LM Studio / Gemma chat client with streaming support

Exposes:
  ask(user_text)            → full reply string (non-streaming, kept for compat)
  ask_stream(user_text)     → generator that yields text chunks as they arrive
  clear_history()           → wipe conversation history

Configuration from .env file via config.py
Web search via search.py (SearXNG + Jina Reader) — auto-triggered per query
"""

import json
import re
import requests

# Load configuration from .env
from config import (
    LLM_STUDIO_URL,
    LLM_MODEL,
    LLM_SYSTEM_PROMPT,
    LLM_TEMPERATURE,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_REQUEST_TIMEOUT,
)

import search  # search.py — SearXNG + Jina Reader

# Appended to system prompt only on turns where search results are injected
_SEARCH_ADDENDUM = (
    "\n\nYou have access to real-time web search results provided above. "
    "Use them to answer accurately. "
    "Mention sources naturally (e.g. 'according to BBC News...') but keep it conversational. "
    "Do not read out URLs."
)

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

    If the query appears to need web search, SearXNG + Jina results are
    fetched first and injected into the system prompt for this turn only.
    Conversation history is never polluted with search context.

    Each yielded chunk is a raw string fragment (may be partial words).

    Usage:
        for chunk in ask_stream("Hello"):
            print(chunk, end="", flush=True)
    """
    # ── Web search (optional, per-turn) ───────────────────────────────────
    system_prompt = LLM_SYSTEM_PROMPT

    if search.needs_search(user_text):
        print(f"[LLM] 🔍 Search triggered for: {user_text}")
        search_context = search.get_search_context(user_text)
        if search_context:
            system_prompt = search_context + "\n\n" + LLM_SYSTEM_PROMPT + _SEARCH_ADDENDUM
            print("[LLM] ✅ Search context injected.")
        else:
            print("[LLM] ⚠ Search returned no results, continuing without.")
    else:
        print("[LLM] 💬 No search needed.")

    # ── Build message list ────────────────────────────────────────────────
    _chat_history.append({"role": "user", "content": user_text})

    messages = [{"role": "system", "content": system_prompt}] + _chat_history

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_OUTPUT_TOKENS,
        "stream": True,
    }

    full_reply = ""

    try:
        print(f"[LLM] → Streaming POST to {LLM_STUDIO_URL}")
        print(f"[LLM] System prompt length: {len(system_prompt)} chars")
        print(f"[LLM] Payload: model={LLM_MODEL}, temp={LLM_TEMPERATURE}, max_tokens={LLM_MAX_OUTPUT_TOKENS}")
        
        with requests.post(
            LLM_STUDIO_URL,
            json=payload,
            timeout=LLM_REQUEST_TIMEOUT,
            stream=True,
        ) as response:
            if response.status_code != 200:
                err = f"[LLM error: HTTP {response.status_code}]"
                print(f"[LLM] {err}")
                # Try to read error body
                try:
                    error_body = response.text[:500]
                    print(f"[LLM] Response body: {error_body}")
                except:
                    pass
                yield err
                return

            line_count = 0
            chunk_count = 0
            for line in response.iter_lines():
                if not line:
                    continue
                line_count += 1
                try:
                    line = line.decode("utf-8")
                except UnicodeDecodeError as e:
                    print(f"[LLM] Decode error on line {line_count}: {e}")
                    continue
                    
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        print(f"[LLM] Stream complete: {chunk_count} chunks, {len(full_reply)} chars")
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0].get("delta", {})
                        
                        # Handle both regular "content" and extended thinking "reasoning_content"
                        # Only collect actual response content, skip reasoning/thinking
                        content_chunk = delta.get("content", "")
                        if content_chunk:
                            chunk_count += 1
                            full_reply += content_chunk
                            yield content_chunk
                    except (json.JSONDecodeError, KeyError, IndexError) as e:
                        print(f"[LLM] Parse error on line {line_count}: {type(e).__name__} | {line[:100]}")
                        continue
            
            if line_count == 0:
                print("[LLM] ⚠ No lines received from LM Studio!")
                yield "[LLM error: no response from LM Studio]"
                return

    except requests.exceptions.Timeout:
        err = f"[LLM error: timed out after {LLM_REQUEST_TIMEOUT}s]"
        yield err
        return
    except Exception as exc:
        err = f"[LLM error: {exc}]"
        yield err
        return

    # Append assistant turn after stream completes
    if full_reply:
        print(f"[LLM] ✅ Got {len(full_reply)} chars: {full_reply[:100]}...")
        _chat_history.append({"role": "assistant", "content": full_reply})
    else:
        print("[LLM] ⚠ Empty reply collected from stream")


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

    # Check if response is an error message
    if full.startswith("[LLM error"):
        print(f"[LLM] Sentence splitter got error: {full}")
        yield full, True
        return

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', full.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        print(f"[LLM] No sentences extracted from {len(full)} chars: {full[:100]}")
        if full:
            yield full, True
        return

    for i, sentence in enumerate(sentences):
        yield sentence, i == len(sentences) - 1


def clear_history() -> None:
    _chat_history.clear()
    print("[LLM] Chat history cleared.")