# Legal Document Assistant

A GenAI-powered tool that helps non-lawyers understand, compare, and navigate
legal documents. **Informational only — not a substitute for advice from a
licensed lawyer** (this is stated in the UI and baked into every AI prompt).

## What it does

- **Simplify & highlight risks** — plain-language summary, key clauses &
  obligations, potential risks/red flags, suggested next steps.
- **Ask questions** — Q&A grounded only in the uploaded document (it says
  "not in the document" rather than guessing).
- **Generate a checklist** — actionable checkbox list of things to verify
  before signing/acting.
- **Compare two documents** — differences, inconsistencies, and which terms
  tend to favor which party.

## Quick start (5 minutes)

```bash
cd legal-ai-assistant
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and paste your Anthropic API key (console.anthropic.com -> API Keys)

uvicorn backend.main:app --reload
# open http://localhost:8000
```

Run the tests any time with:

```bash
pytest
```

## Architecture

```
frontend/   vanilla HTML/CSS/JS, no build step, no framework
   index.html   semantic structure, labeled forms, ARIA live regions
   styles.css   high-contrast, dark-mode aware, visible focus states
   app.js       fetch() calls to the backend; tiny markdown renderer

backend/
   main.py            FastAPI routes (stateless), error handling
   legal_ai.py         Anthropic API calls (server-side only)
   document_parser.py  PDF / DOCX / TXT -> plain text, chunking
   prompts.py           prompt templates (single source of truth)
   security.py          validation, sanitization, rate limiting

tests/       53 unit + integration tests, no real network calls
```

## Deploying to Vercel

```bash
npm i -g vercel   # if you don't have the CLI
cd legal-ai-assistant
vercel
# then set your API key as an env var (do this once):
vercel env add ANTHROPIC_API_KEY
vercel --prod
```

`api/index.py` is the entrypoint Vercel's Python builder requires; it just
re-exports the real app from `backend/main.py`. `vercel.json` routes every
request to that one function, which internally handles both `/api/*` and
serving the frontend.

**Why the backend is stateless:** serverless platforms don't guarantee two
requests from the same browser session hit the same running instance. An
earlier version of this app stored uploaded documents in a server-side
dict keyed by session ID — that works with a single long-running `uvicorn`
process locally, but breaks intermittently on Vercel (a later request can
land on an instance that never saw the upload). The fix: `/api/upload`
returns the extracted text to the browser, and the browser sends it back
with every later request. Nothing about the document is stored server-side
at any point — a stricter privacy property, and the thing that actually
makes this deploy correctly on serverless.

One practical consequence: `maxDuration` in `vercel.json` is set to 30s for
large documents. 30s+ function durations require a Vercel Pro plan; on the
free Hobby tier, requests are capped around 10s, so very long documents
may need trimming or a paid plan.

## How each judging parameter is addressed

**Security**
- API key lives only in the backend's `.env` / environment — the frontend
  and browser never see it, so it can't leak via devtools or network tab.
- Upload validation: extension allow-list, 5 MB size cap, path-traversal
  filename check, "no extractable text" rejection.
- Prompt-injection defence: the document is always wrapped in explicit
  `---DOCUMENT START/END---` markers with the model told it's data, not
  instructions; obvious role-marker strings (`system:`, `[INST]`, etc.) are
  stripped before the document is embedded.
- Per-client in-memory rate limiting on every AI-calling endpoint.
- The backend is stateless: it never writes an uploaded document to disk
  or holds it in server memory beyond the single request that's using it.
  The document only exists in the user's own browser tab and in transit
  over HTTPS — closing the tab discards it completely. CORS is restricted
  to the app's own origin.

**Efficiency**
- Async FastAPI + async `httpx` calls — the server isn't blocked while
  waiting on the LLM.
- Long documents are automatically chunked and map-reduced (per-chunk
  factual digest, then a single final reasoning call) instead of failing
  or silently truncating.
- No unnecessary re-uploads: a document is parsed once per session and
  reused across simplify/ask/checklist calls.

**Testing**
- 53 tests across validation, parsing, prompt construction, the AI wrapper
  (fully mocked — no real API calls, so tests are fast/free/deterministic),
  and the HTTP endpoints (via FastAPI's `TestClient`).
- Both happy paths and failure paths are covered (bad extensions, oversized
  files, empty questions, expired sessions, upstream AI errors → correct
  HTTP status codes).

**Accessibility**
- Semantic HTML5 (`header`, `main`, `section`, real `<label for>` on every
  input), a skip-to-content link, and visible `:focus-visible` outlines.
- `aria-live="polite"` regions for upload status and AI results, so screen
  reader users hear updates without losing their place.
- Color palette meets WCAG AA contrast; a `prefers-color-scheme: dark`
  variant is included; layout uses relative units and is responsive.
- No functionality depends on color alone or on JavaScript-only mouse
  events — all controls are real `<button>`/`<input>` elements operable by
  keyboard.

**Code quality**
- Clear module boundaries (routing / AI calls / parsing / prompts /
  security), type hints, docstrings explaining *why*, no dead code.
- Frontend has no build step or framework — fewer moving parts, easy to
  audit line by line.
- Errors are translated into typed exceptions (`ValidationError`,
  `ParsingError`, `LLMError`) and mapped centrally to HTTP responses,
  instead of scattered try/except with generic messages.

**Problem statement alignment**
- Directly covers 5 of the listed use cases (simplifying documents,
  comparing documents, highlighting clauses/risks/inconsistencies,
  Q&A on a provided document, generating checklists/next steps) with a
  working end-to-end app rather than a mockup.
- Every prompt explicitly frames output as informational and recommends
  consulting a lawyer — matching the "assist, don't replace legal advice"
  constraint.

## Known limitations (be ready to say these out loud)

- Scanned/image-only PDFs have no OCR text to extract — the app tells the
  user this rather than failing silently. Adding OCR (e.g. `pytesseract`)
  is a natural next step if time allows.
- Rate limiting is per-process/in-memory; on serverless (Vercel) each
  instance has its own counter, so it's a soft deterrent rather than a
  hard guarantee. Behind multiple instances you'd want a shared store
  (e.g. Redis / Vercel KV) for a real guarantee.
- Because the client resends the full document text on every action, very
  long documents increase request payload size on each call. Fine for
  typical contracts/leases; a genuinely huge document might hit request
  size limits before it hits the AI context limit.
