from __future__ import annotations

from backend.config import get_settings
from backend.services.llm_service import LLMService
from backend.services.rag_service import RagService


class ChatService:
    def __init__(self, rag_service: RagService, llm_service: LLMService) -> None:
        self._rag = rag_service
        self._llm = llm_service

    async def answer(
        self,
        question: str,
        document_id: str,
        history: list[dict],
        document_id_b: str | None = None,
    ) -> tuple[str, list[dict]]:
        """
        Retrieve relevant chunks, build prompt with history, call LLM.

        Args:
            question: The user's question
            document_id: Primary document to query
            history: List of {"role": "user"|"assistant", "content": str} dicts
            document_id_b: Optional second document for comparison mode

        Returns:
            (answer_text, citations) where citations is list of chunk dicts
        """
        settings = get_settings()

        # 1. Retrieve relevant chunks
        chunks = await self._rag.query(document_id, question)
        if document_id_b:
            chunks_b = await self._rag.query(document_id_b, question)
            chunks = chunks + chunks_b

        # 2. Build context string from chunks
        if chunks:
            context_parts = [chunk["text"] for chunk in chunks]
            context = "\n---\n".join(context_parts)
        else:
            context = "No relevant context found."

        # 3. Build system prompt
        system_prompt = (
            "You are a helpful assistant that answers questions about documents.\n"
            "Use only the provided context to answer. "
            "If you cannot find the answer in the context, say so.\n\n"
            f"Context:\n{context}"
        )

        # 4. Build conversation prompt from history + question
        # Use last CHAT_MAX_HISTORY_MESSAGES messages
        max_hist = settings.CHAT_MAX_HISTORY_MESSAGES
        recent_history = history[-max_hist:] if len(history) > max_hist else history

        # Format as a simple conversation string
        conversation_parts = []
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            conversation_parts.append(f"{role.capitalize()}: {content}")

        conversation_parts.append(f"User: {question}")
        prompt = "\n".join(conversation_parts)

        # 5. Call LLM
        answer = await self._llm.complete(prompt, system=system_prompt)

        return answer, chunks
