import pytest

from backend import legal_ai


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


class FakeAsyncClient:
    """Stand-in for httpx.AsyncClient so no real network call is made."""

    def __init__(self, response: FakeResponse, timeout=None):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        return self._response


@pytest.fixture
def set_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")


def _install_fake_client(monkeypatch, response: FakeResponse):
    def factory(*args, **kwargs):
        return FakeAsyncClient(response)

    monkeypatch.setattr(legal_ai.httpx, "AsyncClient", factory)


class TestCallClaude:
    @pytest.mark.asyncio
    async def test_returns_text_content_on_success(self, monkeypatch, set_api_key):
        response = FakeResponse(200, {"content": [{"type": "text", "text": "Plain summary here."}]})
        _install_fake_client(monkeypatch, response)
        result = await legal_ai._call_claude("some prompt")
        assert result == "Plain summary here."

    @pytest.mark.asyncio
    async def test_raises_on_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(legal_ai.LLMError, match="ANTHROPIC_API_KEY"):
            await legal_ai._call_claude("prompt")

    @pytest.mark.asyncio
    async def test_raises_on_401(self, monkeypatch, set_api_key):
        response = FakeResponse(401)
        _install_fake_client(monkeypatch, response)
        with pytest.raises(legal_ai.LLMError, match="API key"):
            await legal_ai._call_claude("prompt")

    @pytest.mark.asyncio
    async def test_raises_on_429(self, monkeypatch, set_api_key):
        response = FakeResponse(429)
        _install_fake_client(monkeypatch, response)
        with pytest.raises(legal_ai.LLMError, match="Rate limited"):
            await legal_ai._call_claude("prompt")

    @pytest.mark.asyncio
    async def test_raises_on_empty_content(self, monkeypatch, set_api_key):
        response = FakeResponse(200, {"content": []})
        _install_fake_client(monkeypatch, response)
        with pytest.raises(legal_ai.LLMError, match="no content"):
            await legal_ai._call_claude("prompt")


class TestHighLevelFunctions:
    @pytest.mark.asyncio
    async def test_simplify_document_calls_claude_with_simplify_prompt(
        self, monkeypatch, set_api_key
    ):
        captured = {}

        async def fake_call_claude(prompt):
            captured["prompt"] = prompt
            return "result"

        monkeypatch.setattr(legal_ai, "_call_claude", fake_call_claude)
        result = await legal_ai.simplify_document("The tenant shall pay rent.")
        assert result == "result"
        assert "Plain-Language Summary" in captured["prompt"]
        assert "tenant shall pay rent" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_answer_question_includes_question_in_prompt(self, monkeypatch, set_api_key):
        captured = {}

        async def fake_call_claude(prompt):
            captured["prompt"] = prompt
            return "answer"

        monkeypatch.setattr(legal_ai, "_call_claude", fake_call_claude)
        result = await legal_ai.answer_question("doc text", "What is the deposit?")
        assert result == "answer"
        assert "What is the deposit?" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_long_document_is_chunked_and_summarized_first(self, monkeypatch, set_api_key):
        calls = []

        async def fake_call_claude(prompt):
            calls.append(prompt)
            return "chunk summary" if len(calls) < 3 else "final result"

        monkeypatch.setattr(legal_ai, "_call_claude", fake_call_claude)
        long_doc = "clause text. " * 5000  # forces multiple chunks
        result = await legal_ai.simplify_document(long_doc)
        assert result == "final result"
        # at least one chunk-summarization call plus the final call
        assert len(calls) >= 2
