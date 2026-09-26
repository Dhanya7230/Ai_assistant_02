"""
FastAPI backend for the Legal Document Assistant.

Deliberately STATELESS: the server never holds an uploaded document across
requests. `/api/upload` parses a file and hands the extracted text back to
the client; every later call (simplify/ask/checklist/compare) sends that
text back in the request body.

Why: this app is designed to run on serverless platforms (e.g. Vercel),
where each request may be handled by a different, short-lived instance.
An in-memory "session store" keyed by a session_id would work locally but
break intermittently in that environment, since the instance that served
`/api/upload` is not guaranteed to be the one that serves the next call.
Being stateless sidesteps that entirely, at the cost of re-sending document
text on each call — acceptable for typical legal-document sizes.

Other design choices:
  - The Anthropic API key lives only in this backend's environment; the
    frontend never sees it.
  - A simple in-memory rate limiter throttles abuse per client (best-effort
    only on serverless, where it resets per instance — see README).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import legal_ai
from backend.document_parser import ParsingError, extract_text
from backend.security import (
    ValidationError,
    rate_limiter,
    validate_extracted_text,
    validate_filename,
    validate_file_size,
    validate_question,
)

app = FastAPI(title="Legal Document Assistant", version="1.1.0")

# Restrict CORS to same-origin use; add your deployed domain here if the
# frontend is ever served from a different origin than the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _require_rate_limit(request: Request) -> None:
    client_id = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_id):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")


def _require_document_text(document_text: str) -> str:
    """Re-validate text coming back from the client on every call — never
    trust that a value round-tripped through the browser is still safe."""
    return validate_extracted_text(document_text)


# --- Error handling ----------------------------------------------------------

@app.exception_handler(ValidationError)
async def validation_error_handler(_, exc: ValidationError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ParsingError)
async def parsing_error_handler(_, exc: ParsingError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(legal_ai.LLMError)
async def llm_error_handler(_, exc: legal_ai.LLMError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


# --- API ----------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_document(request: Request, file: UploadFile = File(...)):
    """Parses the file and returns the extracted text to the client.
    Nothing is retained server-side after this response is sent."""
    _require_rate_limit(request)
    validate_filename(file.filename)
    content = await file.read()
    validate_file_size(len(content))
    text = extract_text(file.filename, content)

    preview = text[:400] + ("…" if len(text) > 400 else "")
    return {"filename": file.filename, "text": text, "preview": preview}


@app.post("/api/simplify")
async def simplify(request: Request, document_text: str = Form(...)):
    _require_rate_limit(request)
    text = _require_document_text(document_text)
    result = await legal_ai.simplify_document(text)
    return {"result": result}


@app.post("/api/ask")
async def ask(
    request: Request,
    document_text: str = Form(...),
    question: str = Form(...),
    history: str = Form(""),
):
    _require_rate_limit(request)
    text = _require_document_text(document_text)
    question = validate_question(question)
    result = await legal_ai.answer_question(text, question, history)
    return {"result": result}


@app.post("/api/checklist")
async def checklist(request: Request, document_text: str = Form(...), goal: str = Form("")):
    _require_rate_limit(request)
    text = _require_document_text(document_text)
    result = await legal_ai.generate_checklist(text, goal)
    return {"result": result}


@app.post("/api/compare")
async def compare(
    request: Request,
    document_text_a: str = Form(...),
    document_text_b: str = Form(...),
):
    _require_rate_limit(request)
    text_a = _require_document_text(document_text_a)
    text_b = _require_document_text(document_text_b)
    result = await legal_ai.compare_documents(text_a, text_b)
    return {"result": result}


# --- Static frontend for LOCAL DEV ONLY --------------------------------
#
# On Vercel, the /public folder is served directly by the platform itself
# (see vercel.json) — the request never reaches this function at all for
# non-/api paths, so this mount is never used there. It exists only so
# `uvicorn backend.main:app --reload` serves the UI locally. It is
# explicitly opt-in (VERCEL env var is unset locally, set to "1" on
# Vercel) so it can never shadow an API route in production — a mount at
# "/" only supports GET/HEAD, and if it were ever hit for e.g. a POST to
# /api/upload it would return 405 instead of running the real handler.

import os  # noqa: E402

if not os.environ.get("VERCEL"):
    _frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if _frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")