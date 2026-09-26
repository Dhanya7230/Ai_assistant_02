"""
Security helpers: file validation, size limits, and defence against
prompt injection via untrusted document content.

Kept dependency-free and side-effect-free so it is trivially unit-testable.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

# --- File upload limits ---------------------------------------------------

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx"}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_TEXT_CHARS = 300_000  # guard against pathological extracted text


class ValidationError(ValueError):
    """Raised when user input fails a safety check."""


def validate_filename(filename: str) -> str:
    """Reject path traversal / unexpected extensions. Returns a safe basename."""
    if not filename or "/" in filename or "\\" in filename:
        raise ValidationError("Invalid filename.")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return filename


def validate_file_size(size_bytes: int) -> None:
    if size_bytes <= 0:
        raise ValidationError("Uploaded file is empty.")
    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise ValidationError(
            f"File too large ({size_bytes / 1_000_000:.1f} MB). Max is "
            f"{MAX_FILE_SIZE_BYTES / 1_000_000:.0f} MB."
        )


def validate_extracted_text(text: str) -> str:
    if not text or not text.strip():
        raise ValidationError(
            "No readable text could be extracted from this document "
            "(it may be a scanned image without OCR text)."
        )
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    return text


def validate_question(question: str) -> str:
    question = (question or "").strip()
    if not question:
        raise ValidationError("Question cannot be empty.")
    if len(question) > 2000:
        raise ValidationError("Question is too long (max 2000 characters).")
    return question


# --- Prompt-injection mitigation -------------------------------------------
#
# A malicious/careless document could contain text like "ignore prior
# instructions and ...". We never execute document content as instructions;
# we only ever pass it to the model as clearly-delimited DATA inside a
# system prompt that explicitly says so (see backend/prompts.py). As a
# defence-in-depth measure we also strip characters commonly used to fake
# turn/role boundaries when we embed the document text.

_ROLE_MARKER_PATTERN = re.compile(
    r"(system\s*:|assistant\s*:|<\|.*?\|>|\[INST\]|\[/INST\])", re.IGNORECASE
)


def sanitize_document_text(text: str) -> str:
    """Neutralize obvious role/turn markers before embedding as data."""
    return _ROLE_MARKER_PATTERN.sub("[filtered]", text)


# --- Lightweight in-memory rate limiting -----------------------------------
#
# Not a substitute for infra-level rate limiting in production, but stops a
# single client from accidentally hammering (and paying for) the LLM API.

class RateLimiter:
    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, client_id: str) -> bool:
        now = time.monotonic()
        hits = self._hits[client_id]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True


rate_limiter = RateLimiter()
