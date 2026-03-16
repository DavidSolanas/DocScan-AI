# tests/test_llm_service.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services.llm_service import (
    LLMConnectionError,
    LLMParseError,
    LLMService,
    LLMTimeoutError,
    OllamaProvider,
    get_llm_service,
)


def _mock_httpx_client(response_text: str = "hello", status_code: int = 200):
    """Return a mock httpx async context manager that yields a mock client."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {"response": response_text}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


async def test_ollama_provider_happy_path():
    mock_client = _mock_httpx_client("test response")
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        result = await provider.complete("say hello")
    assert result == "test response"


async def test_ollama_provider_no_format_key_when_json_mode_false():
    mock_client = _mock_httpx_client()
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        await provider.complete("prompt", json_mode=False)
    payload = mock_client.post.call_args[1]["json"]
    assert "format" not in payload


async def test_ollama_provider_format_json_when_json_mode_true():
    mock_client = _mock_httpx_client()
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        await provider.complete("prompt", json_mode=True)
    payload = mock_client.post.call_args[1]["json"]
    assert payload["format"] == "json"


async def test_ollama_provider_system_prompt_included():
    mock_client = _mock_httpx_client()
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        await provider.complete("prompt", system="You are helpful")
    payload = mock_client.post.call_args[1]["json"]
    assert payload["system"] == "You are helpful"


async def test_ollama_provider_connect_error_raises_llm_connection_error():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        with pytest.raises(LLMConnectionError):
            await provider.complete("prompt")


async def test_ollama_provider_timeout_raises_llm_timeout_error():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        with pytest.raises(LLMTimeoutError):
            await provider.complete("prompt")


async def test_llm_service_complete_json_happy_path():
    mock_client = _mock_httpx_client('{"key": "value"}')
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        svc = LLMService(provider=provider, max_retries=2)
        result = await svc.complete_json("prompt")
    assert result == {"key": "value"}


async def test_llm_service_complete_json_retries_on_bad_json():
    bad_resp = MagicMock()
    bad_resp.json.return_value = {"response": "not json {{{"}
    bad_resp.raise_for_status = MagicMock()

    good_resp = MagicMock()
    good_resp.json.return_value = {"response": '{"key": "ok"}'}
    good_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=[bad_resp, good_resp])

    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        svc = LLMService(provider=provider, max_retries=2)
        result = await svc.complete_json("prompt")
    assert result == {"key": "ok"}
    assert mock_client.post.call_count == 2


async def test_llm_service_complete_json_raises_llm_parse_error_after_max_retries():
    mock_client = _mock_httpx_client("not valid json {{{")
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        svc = LLMService(provider=provider, max_retries=2)
        with pytest.raises(LLMParseError):
            await svc.complete_json("prompt")
    # Should have tried max_retries + 1 times total
    assert mock_client.post.call_count == 3


async def test_llm_service_connection_error_not_retried():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    with patch("backend.services.llm_service.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider(model="llama3.1:8b", host="http://localhost:11434", timeout=30)
        svc = LLMService(provider=provider, max_retries=2)
        with pytest.raises(LLMConnectionError):
            await svc.complete_json("prompt")
    # Connection errors are not retried — only 1 attempt
    assert mock_client.post.call_count == 1


async def test_get_llm_service_returns_llm_service():
    from backend.config import get_settings
    get_settings.cache_clear()
    svc = get_llm_service()
    assert isinstance(svc, LLMService)
