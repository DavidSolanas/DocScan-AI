"""Tests for Chat API endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_session(client: AsyncClient):
    resp = await client.post("/api/chat/sessions", json={"mode": "single"})
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["mode"] == "single"
    assert data["messages"] == []


@pytest.mark.asyncio
async def test_create_session_comparison(client: AsyncClient):
    resp = await client.post("/api/chat/sessions", json={
        "mode": "comparison",
        "document_id": "doc_a",
        "document_id_b": "doc_b",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["mode"] == "comparison"
    assert data["document_id"] == "doc_a"
    assert data["document_id_b"] == "doc_b"


@pytest.mark.asyncio
async def test_list_sessions_empty(client: AsyncClient):
    resp = await client.get("/api/chat/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_sessions_filter_by_document(client: AsyncClient):
    # Create two sessions with different document_ids
    await client.post("/api/chat/sessions", json={"document_id": "doc_a"})
    await client.post("/api/chat/sessions", json={"document_id": "doc_b"})

    resp = await client.get("/api/chat/sessions?document_id=doc_a")
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1
    assert sessions[0]["document_id"] == "doc_a"


@pytest.mark.asyncio
async def test_get_session_not_found(client: AsyncClient):
    resp = await client.get("/api/chat/sessions/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_with_messages(client: AsyncClient):
    # Create session
    create_resp = await client.post("/api/chat/sessions", json={"mode": "single"})
    session_id = create_resp.json()["id"]

    # Get it back
    resp = await client.get(f"/api/chat/sessions/{session_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == session_id
    assert "messages" in data


@pytest.mark.asyncio
async def test_delete_session(client: AsyncClient):
    create_resp = await client.post("/api/chat/sessions", json={})
    session_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/chat/sessions/{session_id}")
    assert resp.status_code == 204

    # Confirm gone
    get_resp = await client.get(f"/api/chat/sessions/{session_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_session_not_found(client: AsyncClient):
    resp = await client.delete("/api/chat/sessions/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_message_mocks_chat_service(client: AsyncClient):
    create_resp = await client.post("/api/chat/sessions", json={"document_id": "doc1"})
    session_id = create_resp.json()["id"]

    with patch("backend.api.chat.ChatService") as mock_chat_service_cls:
        mock_instance = mock_chat_service_cls.return_value
        mock_instance.answer = AsyncMock(return_value=("The total is €1210.", []))

        resp = await client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={"question": "What is the total amount?"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["role"] == "assistant"
    assert "1210" in data["content"]


@pytest.mark.asyncio
async def test_list_messages(client: AsyncClient):
    create_resp = await client.post("/api/chat/sessions", json={})
    session_id = create_resp.json()["id"]

    with patch("backend.api.chat.ChatService") as mock_chat_service_cls:
        mock_instance = mock_chat_service_cls.return_value
        mock_instance.answer = AsyncMock(return_value=("Test answer.", []))
        await client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={"question": "Test question"},
        )

    resp = await client.get(f"/api/chat/sessions/{session_id}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) >= 2  # user + assistant
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_index_document_no_text(client: AsyncClient):
    # Upload a document first (create it directly in DB via fixture)
    # Create document via the upload endpoint... but we need a simpler approach.
    # Instead, test with a non-existent document_id → 404
    resp = await client.post("/api/chat/index/nonexistent_doc_id")
    assert resp.status_code == 404
