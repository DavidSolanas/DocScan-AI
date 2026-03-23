"""Tests for rag_service. All ChromaDB and Ollama calls are mocked."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.schemas.extraction import AnchorFields, ExtractionResult
from backend.services.llm_service import LLMConnectionError
from backend.services.rag_service import RagService


def make_extraction(
    issuer_name="ACME SL",
    issuer_cif="B12345678",
    recipient_name="XYZ SA",
    recipient_cif="A87654321",
    invoice_number="2024/001",
    issue_date="2024-01-15",
    base_imponible=Decimal("1000.00"),
    iva_rate=Decimal("21"),
    iva_amount=Decimal("210.00"),
    total_amount=Decimal("1210.00"),
) -> ExtractionResult:
    anchor = AnchorFields(
        issuer_name=issuer_name,
        issuer_cif=issuer_cif,
        recipient_name=recipient_name,
        recipient_cif=recipient_cif,
        invoice_number=invoice_number,
        issue_date=issue_date,
        base_imponible=base_imponible,
        iva_rate=iva_rate,
        iva_amount=iva_amount,
        total_amount=total_amount,
    )
    return ExtractionResult(
        anchor=anchor,
        discovered={},
        issues=[],
        requires_review=False,
        llm_model="test",
        extraction_timestamp="2024-01-15T00:00:00",
    )


# 1. Basic chunking
def test_chunk_text_basic():
    svc = RagService()
    text = "Hello world\n\nSecond paragraph\n\nThird paragraph"
    chunks = svc._chunk_text(text)
    assert len(chunks) >= 1
    assert any("Hello world" in c for c in chunks)


# 2. Overlap
def test_chunk_text_overlap(monkeypatch):
    """Short chunk_size forces overlap to carry over."""
    from backend.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_CHUNK_SIZE", 30)
    monkeypatch.setattr(settings, "RAG_CHUNK_OVERLAP", 10)
    monkeypatch.setattr(settings, "RAG_MAX_CHUNKS", 50)

    svc = RagService()
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 5  # 130 chars
    chunks = svc._chunk_text(text)
    assert len(chunks) >= 2


# 3. Max chunks respected
def test_chunk_text_max_chunks(monkeypatch):
    from backend.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_CHUNK_SIZE", 50)
    monkeypatch.setattr(settings, "RAG_CHUNK_OVERLAP", 5)
    monkeypatch.setattr(settings, "RAG_MAX_CHUNKS", 3)

    svc = RagService()
    # Generate lots of text
    text = "\n\n".join([f"Paragraph {i} with some content here." for i in range(20)])
    chunks = svc._chunk_text(text)
    assert len(chunks) <= 3


# 4. Empty text
def test_chunk_text_empty():
    svc = RagService()
    assert svc._chunk_text("") == []
    assert svc._chunk_text("   ") == []


# 5. Invoice summary - full anchor
def test_build_invoice_summary_full():
    svc = RagService()
    result = make_extraction()
    summary = svc._build_invoice_summary(result)
    assert "Invoice Summary:" in summary
    assert "ACME SL" in summary
    assert "B12345678" in summary
    assert "XYZ SA" in summary
    assert "2024/001" in summary
    assert "1000.00" in summary
    assert "21" in summary
    assert "1210.00" in summary


# 6. Invoice summary - minimal anchor
def test_build_invoice_summary_minimal():
    svc = RagService()
    result = make_extraction(
        issuer_name=None, issuer_cif=None,
        recipient_name=None, recipient_cif=None,
        invoice_number="INV-001",
        issue_date=None,
        base_imponible=None, iva_rate=None, iva_amount=None, total_amount=None,
    )
    summary = svc._build_invoice_summary(result)
    assert "INV-001" in summary
    assert "CIF" not in summary  # no CIF since both are None


# 7. index_document calls embeddings and ChromaDB add
@pytest.mark.asyncio
async def test_index_document_calls_embeddings():
    svc = RagService()
    mock_collection = MagicMock()
    mock_collection.delete = MagicMock()
    mock_collection.add = MagicMock()
    svc._collection = mock_collection

    fake_embedding = [0.1, 0.2, 0.3]
    with patch.object(svc, "_get_embedding", new=AsyncMock(return_value=fake_embedding)):
        n = await svc.index_document("doc123", "Hello world\n\nSecond chunk text here")

    assert n > 0
    mock_collection.add.assert_called_once()
    add_call = mock_collection.add.call_args
    ids = add_call.kwargs.get("ids") or (add_call.args[0] if add_call.args else [])
    assert all(id_.startswith("doc123_") for id_ in ids)


# 8. index_document with extraction prepends summary
@pytest.mark.asyncio
async def test_index_document_with_extraction():
    svc = RagService()
    mock_collection = MagicMock()
    mock_collection.delete = MagicMock()
    mock_collection.add = MagicMock()
    svc._collection = mock_collection

    fake_embedding = [0.1, 0.2, 0.3]
    result = make_extraction()
    with patch.object(svc, "_get_embedding", new=AsyncMock(return_value=fake_embedding)):
        n = await svc.index_document("doc123", "Some invoice text", extraction_result=result)

    assert n >= 2  # at least: summary chunk + text chunk
    add_call = mock_collection.add.call_args
    docs = add_call.kwargs.get("documents") or (add_call.args[0] if add_call.args else [])
    assert any("Invoice Summary:" in d for d in docs)


# 9. query returns sorted results
@pytest.mark.asyncio
async def test_query_returns_ranked_results():
    svc = RagService()
    mock_collection = MagicMock()
    mock_collection.query = MagicMock(return_value={
        "documents": [["chunk A", "chunk B"]],
        "metadatas": [
            [{"document_id": "doc1", "chunk_index": 0}, {"document_id": "doc1", "chunk_index": 1}]
        ],
        "distances": [[0.1, 0.5]],
    })
    svc._collection = mock_collection

    with patch.object(svc, "_get_embedding", new=AsyncMock(return_value=[0.1, 0.2])):
        results = await svc.query("doc1", "what is the total?")

    assert len(results) == 2
    assert results[0]["distance"] < results[1]["distance"]
    assert results[0]["text"] == "chunk A"


# 10. _get_embedding raises LLMConnectionError on connect error
@pytest.mark.asyncio
async def test_get_embedding_connection_error():
    svc = RagService()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(LLMConnectionError):
            await svc._get_embedding("test text")


# 11. _chunk_pages tracks page number for each chunk
def test_chunk_pages_tracks_page_number():
    """_chunk_pages returns (text, page_number) tuples with correct 0-based page index."""
    svc = RagService()
    page_texts = [
        "First page content here.",
        "Second page content here.",
        "Third page content here.",
    ]
    result = svc._chunk_pages(page_texts)
    # Should have at least one tuple per non-empty page
    assert len(result) >= 3
    # All entries are (str, int) tuples
    for text, page_num in result:
        assert isinstance(text, str)
        assert isinstance(page_num, int)
    # Check page numbers are correct (0-based)
    page_nums = [pn for _, pn in result]
    assert 0 in page_nums  # first page
    assert 1 in page_nums  # second page
    assert 2 in page_nums  # third page


def test_chunk_pages_empty_page_skipped():
    """_chunk_pages skips empty pages and assigns correct page numbers."""
    svc = RagService()
    page_texts = ["First page.", "", "Third page."]
    result = svc._chunk_pages(page_texts)
    texts = [t for t, _ in result]
    page_nums = [pn for _, pn in result]
    # Empty page 1 should be skipped
    assert 1 not in page_nums
    assert 0 in page_nums
    assert 2 in page_nums


# 12. index_document with page_texts stores page_number in metadata
@pytest.mark.asyncio
async def test_index_document_with_page_texts_stores_page_number():
    """index_document with page_texts passes page_number in metadata for each chunk."""
    svc = RagService()
    mock_collection = MagicMock()
    mock_collection.delete = MagicMock()
    mock_collection.add = MagicMock()
    svc._collection = mock_collection

    fake_embedding = [0.1, 0.2, 0.3]
    page_texts = ["Page one content.", "Page two content.", "Page three content."]

    with patch.object(svc, "_get_embedding", new=AsyncMock(return_value=fake_embedding)):
        n = await svc.index_document(
            "doc_pages",
            "Full text fallback",
            page_texts=page_texts,
        )

    assert n > 0
    mock_collection.add.assert_called_once()
    add_call = mock_collection.add.call_args
    metadatas = add_call.kwargs.get("metadatas") or []
    # Each metadata entry should have page_number key (not None for page-level chunks)
    assert all("page_number" in m for m in metadatas), f"Missing page_number in: {metadatas}"
    page_numbers_in_meta = [m["page_number"] for m in metadatas]
    assert any(pn is not None for pn in page_numbers_in_meta)


@pytest.mark.asyncio
async def test_index_document_without_page_texts_sets_page_number_none():
    """index_document without page_texts sets page_number=None in metadata."""
    svc = RagService()
    mock_collection = MagicMock()
    mock_collection.delete = MagicMock()
    mock_collection.add = MagicMock()
    svc._collection = mock_collection

    fake_embedding = [0.1, 0.2, 0.3]
    with patch.object(svc, "_get_embedding", new=AsyncMock(return_value=fake_embedding)):
        n = await svc.index_document("doc_nopages", "Hello world\n\nSecond chunk text here")

    assert n > 0
    add_call = mock_collection.add.call_args
    metadatas = add_call.kwargs.get("metadatas") or []
    # Without page_texts, page_number should be None for all chunks
    assert all(m.get("page_number") is None for m in metadatas), (
        f"Expected page_number=None, got: {metadatas}"
    )


# 13. query returns page_number in results
@pytest.mark.asyncio
async def test_query_returns_page_number_in_results():
    """query() includes page_number key in each result dict."""
    svc = RagService()
    mock_collection = MagicMock()
    mock_collection.query = MagicMock(return_value={
        "documents": [["chunk A", "chunk B"]],
        "metadatas": [
            [
                {"document_id": "doc1", "chunk_index": 0, "page_number": 0},
                {"document_id": "doc1", "chunk_index": 1, "page_number": 1},
            ]
        ],
        "distances": [[0.1, 0.5]],
    })
    svc._collection = mock_collection

    with patch.object(svc, "_get_embedding", new=AsyncMock(return_value=[0.1, 0.2])):
        results = await svc.query("doc1", "what is the total?")

    assert len(results) == 2
    assert "page_number" in results[0], f"'page_number' key missing from result: {results[0]}"
    assert results[0]["page_number"] == 0
    assert results[1]["page_number"] == 1


@pytest.mark.asyncio
async def test_query_returns_page_number_none_when_missing():
    """query() returns page_number=None when metadata lacks the key."""
    svc = RagService()
    mock_collection = MagicMock()
    mock_collection.query = MagicMock(return_value={
        "documents": [["chunk A"]],
        "metadatas": [
            [{"document_id": "doc1", "chunk_index": 0}],  # no page_number
        ],
        "distances": [[0.2]],
    })
    svc._collection = mock_collection

    with patch.object(svc, "_get_embedding", new=AsyncMock(return_value=[0.1, 0.2])):
        results = await svc.query("doc1", "question")

    assert "page_number" in results[0]
    assert results[0]["page_number"] is None
