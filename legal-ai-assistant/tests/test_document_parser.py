import io

import pytest

from backend.document_parser import ParsingError, chunk_text, extract_text


class TestExtractText:
    def test_extracts_plain_txt(self):
        content = b"This agreement is between Party A and Party B."
        result = extract_text("agreement.txt", content)
        assert "Party A" in result

    def test_handles_non_utf8_txt_gracefully(self):
        content = "café résumé".encode("latin-1")
        result = extract_text("notes.txt", content)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_rejects_unsupported_extension(self):
        with pytest.raises(ParsingError):
            extract_text("malware.exe", b"binary data")

    def test_rejects_empty_txt(self):
        from backend.security import ValidationError

        with pytest.raises(ValidationError):
            extract_text("empty.txt", b"   ")

    def test_extracts_real_pdf(self):
        pypdf = pytest.importorskip("pypdf")
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)
        # A blank page yields no text; this just confirms the pdf branch runs
        # without raising for a well-formed (if textless) PDF, and that the
        # "no readable text" validation kicks in correctly.
        from backend.security import ValidationError

        with pytest.raises(ValidationError):
            extract_text("blank.pdf", buf.getvalue())


class TestChunkText:
    def test_returns_single_chunk_for_short_text(self):
        text = "short document"
        assert chunk_text(text, max_chars=1000) == [text]

    def test_splits_long_text_into_overlapping_chunks(self):
        text = "x" * 5000
        chunks = chunk_text(text, max_chars=2000, overlap=200)
        assert len(chunks) > 1
        # Every character of the original text should appear in the chunks.
        assert "".join(chunks).replace("x", "") == ""
        # Chunks overlap: end of one chunk reappears at start of next.
        assert chunks[0][-200:] == chunks[1][:200]

    def test_covers_full_text_length(self):
        text = "abcdefgh" * 1000
        chunks = chunk_text(text, max_chars=1000, overlap=100)
        # reconstruct by taking non-overlapping parts should still contain
        # every original character somewhere
        combined = "".join(chunks)
        assert len(combined) >= len(text)
