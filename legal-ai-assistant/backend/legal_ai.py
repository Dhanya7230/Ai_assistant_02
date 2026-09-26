"""
Thin async wrapper around the Anthropic Messages API.

Isolated here so:
  - the API key is only ever read from the environment, server-side
  - it can be mocked easily in tests (no real network calls in the test suite)
  - retry/timeout/error handling lives in one place
"""
from __future__ import annotations

import os

import httpx

from backend import prompts
from backend.document_parser import chunk_text
from backend.security import sanitize_document_text

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2000
REQUEST_TIMEOUT_SECONDS = 60


class LLMError(RuntimeError):
    pass


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError(
            "Server is not configured with an ANTHROPIC_API_KEY. "
            "Set it in your .env file (see .env.example)."
        )
    return key


async def _call_claude(prompt: str) -> str:
    headers = {
        "x-api-key": _get_api_key(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError("The AI service timed out. Please try again.") from exc
        except httpx.RequestError as exc:
            raise LLMError(f"Could not reach the AI service: {exc}") from exc

    if resp.status_code == 401:
        raise LLMError("AI service rejected the API key (check ANTHROPIC_API_KEY).")
    if resp.status_code == 429:
        raise LLMError("Rate limited by the AI service. Please wait and try again.")
    if resp.status_code >= 400:
        raise LLMError(f"AI service error ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    if not parts:
        raise LLMError("AI service returned no content.")
    return "\n".join(parts)


async def _summarize_chunk(chunk: str) -> str:
    """Used only when a document must be split; produces a factual digest
    of one chunk so the final prompt can reason over the whole document
    without exceeding context limits."""
    prompt = (
        "Summarize the key clauses, obligations, and any risks in this "
        "excerpt of a larger legal document, in plain factual bullet "
        "points (no preamble):\n\n" + chunk
    )
    return await _call_claude(prompt)


async def _condense_if_needed(document_text: str) -> str:
    document_text = sanitize_document_text(document_text)
    chunks = chunk_text(document_text)
    if len(chunks) == 1:
        return chunks[0]
    summaries = [await _summarize_chunk(c) for c in chunks]
    return "\n\n---\n\n".join(summaries)


async def simplify_document(document_text: str) -> str:
    working_text = await _condense_if_needed(document_text)
    return await _call_claude(prompts.simplify_prompt(working_text))


async def answer_question(document_text: str, question: str, history: str = "") -> str:
    working_text = await _condense_if_needed(document_text)
    return await _call_claude(prompts.qa_prompt(working_text, question, history))


async def compare_documents(document_a: str, document_b: str) -> str:
    a = await _condense_if_needed(document_a)
    b = await _condense_if_needed(document_b)
    return await _call_claude(prompts.compare_prompt(a, b))


async def generate_checklist(document_text: str, goal: str = "") -> str:
    working_text = await _condense_if_needed(document_text)
    return await _call_claude(prompts.checklist_prompt(working_text, goal))
