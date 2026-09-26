import io

import pytest
from fastapi.testclient import TestClient

from backend import legal_ai, main


@pytest.fixture
def client():
    return TestClient(main.app)


class TestUpload:
    def test_upload_txt_returns_extracted_text(self, client):
        resp = client.post(
            "/api/upload",
            files={"file": ("doc.txt", io.BytesIO(b"Sample agreement text."), "text/plain")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "doc.txt"
        assert body["text"] == "Sample agreement text."
        assert "Sample agreement" in body["preview"]

    def test_upload_rejects_bad_extension(self, client):
        resp = client.post(
            "/api/upload",
            files={"file": ("virus.exe", io.BytesIO(b"binary"), "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_upload_rejects_empty_file(self, client):
        resp = client.post(
            "/api/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_rejects_oversized_file(self, client):
        big_content = b"a" * (6 * 1024 * 1024)
        resp = client.post(
            "/api/upload",
            files={"file": ("big.txt", io.BytesIO(big_content), "text/plain")},
        )
        assert resp.status_code == 400


class TestSimplify:
    def test_simplify_requires_document_text(self, client):
        resp = client.post("/api/simplify", data={"document_text": "   "})
        assert resp.status_code == 400

    def test_simplify_returns_ai_result(self, client, monkeypatch):
        async def fake_simplify(text):
            assert text == "The tenant shall pay rent."
            return "## Plain-Language Summary\nThis is a lease."

        monkeypatch.setattr(legal_ai, "simplify_document", fake_simplify)
        resp = client.post("/api/simplify", data={"document_text": "The tenant shall pay rent."})
        assert resp.status_code == 200
        assert "lease" in resp.json()["result"]

    def test_simplify_surfaces_llm_error_as_502(self, client, monkeypatch):
        async def failing_simplify(text):
            raise legal_ai.LLMError("AI service unavailable")

        monkeypatch.setattr(legal_ai, "simplify_document", failing_simplify)
        resp = client.post("/api/simplify", data={"document_text": "some text"})
        assert resp.status_code == 502


class TestAsk:
    def test_ask_rejects_empty_question(self, client):
        resp = client.post(
            "/api/ask", data={"document_text": "doc text", "question": "   "}
        )
        assert resp.status_code == 400

    def test_ask_rejects_empty_document_text(self, client):
        resp = client.post(
            "/api/ask", data={"document_text": "   ", "question": "When is rent due?"}
        )
        assert resp.status_code == 400

    def test_ask_returns_answer(self, client, monkeypatch):
        async def fake_answer(text, question, history=""):
            return f"Answer to: {question}"

        monkeypatch.setattr(legal_ai, "answer_question", fake_answer)
        resp = client.post(
            "/api/ask",
            data={"document_text": "doc text", "question": "When is rent due?"},
        )
        assert resp.status_code == 200
        assert "When is rent due?" in resp.json()["result"]


class TestChecklist:
    def test_checklist_returns_ai_result(self, client, monkeypatch):
        async def fake_checklist(text, goal=""):
            return "- [ ] Verify the deposit amount"

        monkeypatch.setattr(legal_ai, "generate_checklist", fake_checklist)
        resp = client.post("/api/checklist", data={"document_text": "doc text"})
        assert resp.status_code == 200
        assert "deposit" in resp.json()["result"]


class TestCompare:
    def test_compare_two_documents(self, client, monkeypatch):
        async def fake_compare(a, b):
            assert a == "Doc A text"
            assert b == "Doc B text"
            return "## Key Differences\n- Different obligations"

        monkeypatch.setattr(legal_ai, "compare_documents", fake_compare)
        resp = client.post(
            "/api/compare",
            data={"document_text_a": "Doc A text", "document_text_b": "Doc B text"},
        )
        assert resp.status_code == 200
        assert "Key Differences" in resp.json()["result"]

    def test_compare_rejects_missing_second_document(self, client):
        resp = client.post(
            "/api/compare",
            data={"document_text_a": "Doc A text", "document_text_b": "   "},
        )
        assert resp.status_code == 400


class TestHealth:
    def test_health_check(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestStatelessness:
    def test_no_server_side_storage_between_requests(self, client, monkeypatch):
        """Regression test for the Vercel serverless issue: nothing about
        one request should be recoverable in a later request without the
        client re-sending it."""
        assert not hasattr(main, "_sessions")
