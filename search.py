"""
search.py — SearXNG + Jina Reader web search module

Exposes:
  needs_search(text)        → bool: heuristic to detect if a query needs web search
  get_search_context(query) → str: formatted search results ready to inject into LLM prompt
  
Configuration from .env file via config.py
"""

import re
import requests

# Load configuration from .env
from config import (
    SEARCH_SEARXNG_URL,
    SEARCH_JINA_URL,
    SEARCH_NUM_RESULTS,
    SEARCH_FETCH_FULL_PAGES,
    SEARCH_MAX_PAGE_CHARS,
    SEARCH_TIMEOUT,
    SEARCH_JINA_TIMEOUT,
)

# ---------------------------------------------------------------------------
# Aliases for backward compatibility
# ---------------------------------------------------------------------------

SEARXNG_URL = SEARCH_SEARXNG_URL
JINA_URL = SEARCH_JINA_URL
NUM_RESULTS = SEARCH_NUM_RESULTS
FETCH_FULL_PAGES = SEARCH_FETCH_FULL_PAGES
MAX_PAGE_CHARS = SEARCH_MAX_PAGE_CHARS
# SEARCH_TIMEOUT is used directly (imported from config)
# JINA_TIMEOUT is used directly (imported from config)

# ---------------------------------------------------------------------------
# Keywords that strongly suggest a web search is needed
# ---------------------------------------------------------------------------

_SEARCH_TRIGGERS = [
    # Recency / news
    r"\b(latest|recent|current|today|now|right now|this week|this month|this year)\b",
    r"\b(news|update|updates|announcement|just released|just launched)\b",
    # Facts / lookup
    r"\b(who is|what is|where is|when is|how much|how many|price of|cost of)\b",
    r"\b(weather|temperature|forecast)\b",
    r"\b(score|result|match|game|winner|standings)\b",
    # Explicit search intent
    r"\b(search|look up|find|google|check|tell me about)\b",
    # Time-sensitive topics
    r"\b(stock|share price|crypto|bitcoin|rate|exchange rate)\b",
    r"\b(election|politics|government|policy|law|bill)\b",
]

_SEARCH_PATTERN = re.compile(
    "|".join(_SEARCH_TRIGGERS),
    re.IGNORECASE
)

# Short queries (< 4 words) that are conversational — never search these
_CONVERSATIONAL_PATTERN = re.compile(
    r"^(hi|hello|hey|thanks|thank you|ok|okay|bye|goodbye|yes|no|sure|great|cool|nice|what\?|huh\?|really\?|wow)[\s!?.]*$",
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def needs_search(text: str) -> bool:
    """
    Heuristic: returns True if the query likely needs a web search.

    Checks for:
    - Conversational phrases (never search)
    - Trigger keywords that imply recency or factual lookup
    """
    text = text.strip()

    if not text:
        return False

    # Skip obvious small talk
    if _CONVERSATIONAL_PATTERN.match(text):
        return False

    # Trigger on keyword match
    if _SEARCH_PATTERN.search(text):
        return True

    return False


def get_search_context(query: str) -> str:
    """
    Runs a SearXNG search for `query`, optionally fetches full pages via
    Jina Reader, and returns a formatted context string ready to be
    injected into the LLM system prompt.

    Returns an empty string if search fails or yields no results.
    """
    results = _search(query)
    if not results:
        return ""

    context_parts = [f'Web search results for: "{query}"\n']

    for i, result in enumerate(results, 1):
        title   = result.get("title", "").strip()
        snippet = result.get("content", "").strip()
        url     = result.get("url", "").strip()

        context_parts.append(f"[{i}] {title}")
        if snippet:
            context_parts.append(snippet)
        if url:
            context_parts.append(f"Source: {url}")

        # Fetch full page content for top N results
        if i <= FETCH_FULL_PAGES and url:
            full_text = _fetch_page(url)
            if full_text:
                context_parts.append(f"Full content:\n{full_text}")

        context_parts.append("")  # blank line between results

    return "\n".join(context_parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _search(query: str) -> list[dict]:
    """Query SearXNG JSON API and return up to NUM_RESULTS results."""
    try:
        print(f"[Search] Querying SearXNG for: {query}")
        resp = requests.get(
            SEARXNG_URL,
            params={"q": query, "format": "json"},
            timeout=SEARCH_TIMEOUT,
        )
        if resp.status_code == 403:
            print("[Search] ⚠ SearXNG returned 403 — JSON format may not be enabled.")
            print("         Edit settings.yml and add 'json' under search.formats, then restart Docker.")
            return []
        resp.raise_for_status()
        results = resp.json().get("results", [])[:NUM_RESULTS]
        print(f"[Search] Got {len(results)} results.")
        return results
    except requests.exceptions.ConnectionError:
        print("[Search] ⚠ Could not connect to SearXNG at", SEARXNG_URL)
        return []
    except Exception as e:
        print(f"[Search] Error: {e}")
        return []


def _fetch_page(url: str) -> str:
    """Fetch a URL via Jina Reader and return truncated plain text."""
    try:
        print(f"[Search] Fetching full page via Jina: {url[:60]}...")
        resp = requests.get(
            JINA_URL + url,
            headers={"Accept": "text/plain"},
            timeout=SEARCH_JINA_TIMEOUT,
        )
        text = resp.text.strip()
        if len(text) > MAX_PAGE_CHARS:
            text = text[:MAX_PAGE_CHARS] + "... [truncated]"
        return text
    except Exception as e:
        print(f"[Search] Jina fetch failed for {url[:60]}: {e}")
        return ""