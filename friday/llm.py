"""
llm.py — LM Studio chat client with true sentence streaming.

Public API:
    ask(text, cancel=None)                  → full reply string
    ask_stream(text, cancel=None)           → yields raw chunks
    ask_stream_sentences(text, cancel=None) → yields (sentence, is_last)
    clear_history()
"""

import json
import logging
import re
import threading
from typing import Iterator, Optional, Tuple

import requests

from .config import (
    LLM_STUDIO_URL,
    LLM_MODEL,
    LLM_SYSTEM_PROMPT,
    LLM_TEMPERATURE,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_REQUEST_TIMEOUT,
    LLM_HISTORY_MAX_TURNS,
    LLM_TOOLS_ENABLED,
    SEARCH_ENABLED,
)
from . import search


# OpenAI-style tool definition for the LLM to invoke when it wants a search.
_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Search the web for up-to-date information. Use this when the user "
            "asks about news, current events, recent prices, or anything that "
            "requires fresh facts the model wouldn't know."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Concise search query, 3-8 words."
                }
            },
            "required": ["query"],
        },
    },
}

log = logging.getLogger(__name__)

_SEARCH_ADDENDUM = (
    "\n\nYou have access to real-time web search results provided above. "
    "Use them to answer accurately. "
    "Mention sources naturally (e.g. 'according to BBC News...') but keep it conversational. "
    "Do not read out URLs."
)

_chat_history: list[dict] = []
_history_lock = threading.Lock()


def _trimmed_history() -> list[dict]:
    """Return a copy of history truncated to the last LLM_HISTORY_MAX_TURNS turns."""
    with _history_lock:
        # 2 messages per turn (user + assistant); drop oldest if over budget
        max_messages = LLM_HISTORY_MAX_TURNS * 2
        if len(_chat_history) > max_messages:
            del _chat_history[: len(_chat_history) - max_messages]
        return list(_chat_history)


def _append_history(*messages: dict) -> None:
    with _history_lock:
        _chat_history.extend(messages)


def clear_history() -> None:
    with _history_lock:
        _chat_history.clear()
    log.info("Chat history cleared")


def ask(user_text: str, cancel: Optional[threading.Event] = None) -> str:
    return "".join(ask_stream(user_text, cancel=cancel))


def _stream_one_request(
    messages: list,
    tools: Optional[list],
    cancel: Optional[threading.Event],
) -> Tuple[Iterator[str], dict]:
    """
    Open one streaming request to LM Studio. Returns (chunk_iterator, accumulator).

    The accumulator is mutated as the iterator runs and on completion contains:
        accumulator["content"]    — full text concatenated
        accumulator["tool_calls"] — list of {id, name, arguments} dicts
        accumulator["error"]      — error string or None
    """
    payload: dict = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_OUTPUT_TOKENS,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools

    accumulator: dict = {"content": "", "tool_calls": [], "error": None}
    tc_partial: dict[int, dict] = {}  # index → {id, name, arguments}

    def _generate() -> Iterator[str]:
        try:
            with requests.post(
                LLM_STUDIO_URL,
                json=payload,
                timeout=LLM_REQUEST_TIMEOUT,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    msg = f"HTTP {response.status_code}: {response.text[:300]}"
                    log.error("LLM %s", msg)
                    accumulator["error"] = f"[LLM error: HTTP {response.status_code}]"
                    yield accumulator["error"]
                    return

                for line in response.iter_lines():
                    if cancel and cancel.is_set():
                        log.info("LLM stream cancelled by caller")
                        response.close()
                        return
                    if not line:
                        continue
                    try:
                        decoded = line.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    if not decoded.startswith("data: "):
                        continue
                    data = decoded[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0].get("delta", {})
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

                    # Tool-call streaming: each fragment carries {index, id?, function: {name?, arguments?}}
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = tc_partial.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]

                    chunk = delta.get("content") or ""
                    if chunk:
                        accumulator["content"] += chunk
                        yield chunk

        except requests.exceptions.Timeout:
            accumulator["error"] = f"[LLM error: timed out after {LLM_REQUEST_TIMEOUT}s]"
            yield accumulator["error"]
            return
        except Exception as exc:
            log.exception("LLM request failed")
            accumulator["error"] = f"[LLM error: {exc}]"
            yield accumulator["error"]
            return

        # Finalize any tool calls
        accumulator["tool_calls"] = [
            {
                "id": v["id"] or f"call_{i}",
                "type": "function",
                "function": {"name": v["name"], "arguments": v["arguments"]},
            }
            for i, v in sorted(tc_partial.items())
            if v["name"]
        ]

    return _generate(), accumulator


def _execute_tool_call(name: str, arguments_json: str) -> str:
    """Run a tool by name. Returns the tool result string for the LLM."""
    if name != "search_web":
        return f"(unknown tool: {name})"
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return "(could not parse arguments)"
    query = (args.get("query") or "").strip()
    if not query:
        return "(empty query)"
    log.info("Tool search_web(%r)", query)
    return search.get_search_context(query) or "(no results)"


def ask_stream(
    user_text: str,
    cancel: Optional[threading.Event] = None,
) -> Iterator[str]:
    """
    Yield raw text chunks from the LLM as they arrive over SSE.

    When LLM_TOOLS_ENABLED is true, the model can request a web search via the
    `search_web` tool; the call is executed and the model continues streaming
    with the result. Otherwise, the legacy needs_search() heuristic injects
    search context up-front.
    """
    system_prompt = LLM_SYSTEM_PROMPT

    if SEARCH_ENABLED and not LLM_TOOLS_ENABLED and search.needs_search(user_text):
        log.info("Search triggered (heuristic) for: %s", user_text)
        if cancel and cancel.is_set():
            return
        ctx = search.get_search_context(user_text)
        if ctx:
            system_prompt = ctx + "\n\n" + LLM_SYSTEM_PROMPT + _SEARCH_ADDENDUM
            log.info("Search context injected (%d chars)", len(ctx))
        else:
            log.warning("Search returned no results")

    messages: list = [{"role": "system", "content": system_prompt}]
    messages.extend(_trimmed_history())
    messages.append({"role": "user", "content": user_text})

    log.debug("POST %s model=%s tools=%s", LLM_STUDIO_URL, LLM_MODEL, LLM_TOOLS_ENABLED)

    final_reply = ""
    tools = [_SEARCH_TOOL] if (SEARCH_ENABLED and LLM_TOOLS_ENABLED) else None
    max_tool_rounds = 3

    for _round in range(max_tool_rounds + 1):
        chunk_iter, acc = _stream_one_request(messages, tools, cancel)
        for chunk in chunk_iter:
            yield chunk

        if acc["error"]:
            return  # error was already yielded as a chunk

        if cancel and cancel.is_set():
            return

        if not acc["tool_calls"]:
            final_reply += acc["content"]
            break

        # Append the assistant's tool-call request, then each tool result
        messages.append({
            "role": "assistant",
            "content": acc["content"] or None,
            "tool_calls": acc["tool_calls"],
        })
        for tc in acc["tool_calls"]:
            result = _execute_tool_call(
                tc["function"]["name"],
                tc["function"]["arguments"],
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result[:8000],  # safety cap
            })
        # Loop: model now sees tool results and continues streaming.
    else:
        log.warning("Tool-call loop hit max rounds (%d)", max_tool_rounds)

    final_reply = final_reply.strip()
    if final_reply and not (cancel and cancel.is_set()):
        _append_history(
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": final_reply},
        )
        log.info("Reply complete (%d chars)", len(final_reply))


# Sentence boundary: terminal punctuation followed by whitespace.
# Won't split on "Dr." mid-sentence because there's no whitespace immediately after.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def ask_stream_sentences(
    user_text: str,
    cancel: Optional[threading.Event] = None,
) -> Iterator[Tuple[str, bool]]:
    """
    Yield (sentence, is_last) tuples as the LLM produces them.

    Buffers raw chunks and emits each completed sentence the instant a boundary
    is seen. The final fragment after the stream ends is yielded with is_last=True.
    """
    buffer = ""
    pending: Optional[str] = None
    saw_error = False

    for chunk in ask_stream(user_text, cancel=cancel):
        if chunk.startswith("[LLM error"):
            saw_error = True
            yield chunk, True
            return
        buffer += chunk

        # Emit every fully-bounded sentence in the buffer.
        while True:
            match = _SENTENCE_BOUNDARY.search(buffer)
            if not match:
                break
            sentence = buffer[: match.start()].strip()
            buffer = buffer[match.end():]
            if not sentence:
                continue
            if pending is not None:
                yield pending, False
            pending = sentence

    if saw_error:
        return

    # Flush any tail content as the final sentence.
    tail = buffer.strip()
    if tail:
        if pending is not None:
            yield pending, False
        yield tail, True
    elif pending is not None:
        yield pending, True
