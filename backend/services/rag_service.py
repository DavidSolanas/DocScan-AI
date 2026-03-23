from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from backend.config import get_settings
from backend.services.llm_service import LLMConnectionError, LLMResponseError, LLMTimeoutError

if TYPE_CHECKING:
    from backend.schemas.extraction import ExtractionResult

logger = logging.getLogger(__name__)


class RagService:
    """ChromaDB-backed RAG service using Ollama embeddings."""

    def __init__(self) -> None:
        self._collection = None  # lazy singleton per instance

    def _get_collection(self):
        """Lazy-initialize ChromaDB PersistentClient and collection."""
        if self._collection is None:
            import chromadb
            settings = get_settings()
            client = chromadb.PersistentClient(path=str(settings.CHROMA_DIR))
            self._collection = client.get_or_create_collection(
                name="docscanai_chunks",
                metadata={"hnsw:space": "cosine"},
                embedding_function=None,  # we pass vectors explicitly
            )
        return self._collection

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks."""
        settings = get_settings()
        chunk_size = settings.RAG_CHUNK_SIZE
        overlap = settings.RAG_CHUNK_OVERLAP
        max_chunks = settings.RAG_MAX_CHUNKS

        if not text.strip():
            return []

        # Split on paragraph breaks first, then sentence breaks, then hard cut
        parts: list[str] = []
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            if len(para) <= chunk_size:
                parts.append(para)
            else:
                # split on ". "
                for sent in para.split(". "):
                    sent = sent.strip()
                    if sent:
                        parts.append(sent)

        # Now merge parts into chunks of ~chunk_size with overlap
        chunks: list[str] = []
        current = ""
        for part in parts:
            if not current:
                current = part
            elif len(current) + len(part) + 2 <= chunk_size:
                current = current + "\n\n" + part
            else:
                chunks.append(current)
                # Carry overlap from end of previous chunk
                overlap_text = current[-overlap:] if len(current) > overlap else current
                current = overlap_text + "\n\n" + part

        if current:
            chunks.append(current)

        # Hard-cut any chunk that still exceeds chunk_size
        final: list[str] = []
        for chunk in chunks:
            if len(chunk) <= chunk_size:
                final.append(chunk)
            else:
                for i in range(0, len(chunk), chunk_size - overlap):
                    piece = chunk[i:i + chunk_size]
                    if piece.strip():
                        final.append(piece)

        return final[:max_chunks]

    def _build_invoice_summary(self, result: ExtractionResult) -> str:
        """Human-readable summary of anchor fields for indexing."""
        a = result.anchor
        lines = ["Invoice Summary:"]
        if a.issuer_name or a.issuer_cif:
            name = a.issuer_name or ""
            cif = f" (CIF: {a.issuer_cif})" if a.issuer_cif else ""
            lines.append(f"Issuer: {name}{cif}")
        if a.recipient_name or a.recipient_cif:
            name = a.recipient_name or ""
            cif = f" (CIF: {a.recipient_cif})" if a.recipient_cif else ""
            lines.append(f"Recipient: {name}{cif}")
        if a.invoice_number:
            lines.append(f"Invoice number: {a.invoice_number}")
        if a.issue_date:
            lines.append(f"Date: {a.issue_date}")
        if a.base_imponible is not None:
            currency = a.currency or "EUR"
            lines.append(f"Base imponible: {a.base_imponible} {currency}")
        if a.iva_rate is not None and a.iva_amount is not None:
            lines.append(f"IVA ({a.iva_rate}%): {a.iva_amount}")
        if a.total_amount is not None:
            lines.append(f"Total: {a.total_amount}")
        return "\n".join(lines)

    async def _get_embedding(self, text: str) -> list[float]:
        """Call Ollama /api/embeddings to get a vector for text."""
        settings = get_settings()
        url = f"{settings.OLLAMA_HOST.rstrip('/')}/api/embeddings"
        payload = {"model": settings.OLLAMA_EMBED_MODEL, "prompt": text}
        try:
            async with httpx.AsyncClient(timeout=float(settings.OLLAMA_TIMEOUT)) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                emb = response.json().get("embedding")
                if emb is None:
                    raise LLMResponseError("Ollama embeddings response missing 'embedding' key")
                return emb
        except httpx.ConnectError as exc:
            raise LLMConnectionError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise LLMConnectionError(f"Ollama embeddings HTTP error: {status}") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(str(exc)) from exc

    async def index_document(
        self,
        document_id: str,
        text: str,
        extraction_result: ExtractionResult | None = None,
    ) -> int:
        """Index document text into ChromaDB. Returns number of chunks indexed."""
        collection = self._get_collection()

        # Delete existing chunks for this document
        try:
            collection.delete(where={"document_id": document_id})
        except Exception:
            pass  # collection may be empty

        chunks = self._chunk_text(text)

        # Prepend invoice summary chunk if extraction available
        if extraction_result is not None:
            summary = self._build_invoice_summary(extraction_result)
            chunks = [summary] + chunks

        settings = get_settings()
        chunks = chunks[:settings.RAG_MAX_CHUNKS]

        if not chunks:
            return 0

        ids = [f"{document_id}_{i}" for i in range(len(chunks))]
        metadatas = [{"document_id": document_id, "chunk_index": i} for i in range(len(chunks))]

        # Get embeddings for all chunks
        embeddings = []
        for chunk in chunks:
            emb = await self._get_embedding(chunk)
            embeddings.append(emb)

        collection.add(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return len(chunks)

    async def query(
        self,
        document_id: str,
        question: str,
        top_k: int | None = None,
    ) -> list[dict]:
        """Query ChromaDB for relevant chunks. Returns sorted by distance."""
        settings = get_settings()
        k = top_k if top_k is not None else settings.RAG_TOP_K
        collection = self._get_collection()

        question_emb = await self._get_embedding(question)
        results = collection.query(
            query_embeddings=[question_emb],
            n_results=k,
            where={"document_id": document_id},
            include=["documents", "metadatas", "distances"],
        )

        output = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                output.append({
                    "text": doc,
                    "chunk_index": meta.get("chunk_index", 0),
                    "distance": dist,
                })
        # Already sorted by distance ascending (ChromaDB default)
        return output

    def delete_index(self, document_id: str) -> None:
        """Remove all chunks for a document from ChromaDB."""
        collection = self._get_collection()
        try:
            collection.delete(where={"document_id": document_id})
        except Exception:
            pass
