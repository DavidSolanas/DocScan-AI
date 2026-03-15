# backend/services/llm_service.py
from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

import httpx

from backend.config import get_settings


# --- Exceptions ---

class LLMError(Exception):
    """Base class for LLM errors."""


class LLMConnectionError(LLMError):
    """Ollama unreachable."""


class LLMTimeoutError(LLMError):
    """Ollama did not respond in time."""


class LLMResponseError(LLMError):
    """Unexpected response structure from Ollama."""


class LLMParseError(LLMError):
    """JSON parse failed after all retries."""


# --- Provider protocol ---

@runtime_checkable
class LLMProvider(Protocol):
    async def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> str: ...


# --- Ollama implementation ---

class OllamaProvider:
    def __init__(self, model: str, host: str, timeout: float) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    async def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> str:
        payload: dict = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(f"{self.host}/api/generate", json=payload)
                response.raise_for_status()
                return response.json()["response"]
            except httpx.ConnectError as exc:
                raise LLMConnectionError(str(exc)) from exc
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(str(exc)) from exc
            except httpx.HTTPStatusError as exc:
                raise LLMResponseError(f"HTTP {exc.response.status_code}: {exc}") from exc
            except (KeyError, ValueError) as exc:
                raise LLMResponseError(str(exc)) from exc


# --- Service wrapper with retry ---

class LLMService:
    def __init__(self, provider: LLMProvider, max_retries: int = 2) -> None:
        self._provider = provider
        self._max_retries = max_retries

    async def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> str:
        """Single completion. Does NOT retry — surfaces errors immediately."""
        return await self._provider.complete(prompt, system=system, json_mode=json_mode)

    async def complete_json(
        self, prompt: str, system: str | None = None
    ) -> dict:
        """Completion with JSON mode. Retries up to max_retries on JSONDecodeError only."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            raw = await self._provider.complete(prompt, system=system, json_mode=True)
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                last_exc = exc
        raise LLMParseError(f"JSON parse failed after {self._max_retries + 1} attempts") from last_exc


# --- Factory ---

def get_llm_service() -> LLMService:
    settings = get_settings()
    provider = OllamaProvider(
        model=settings.OLLAMA_DEFAULT_MODEL,
        host=settings.OLLAMA_HOST,
        timeout=float(settings.OLLAMA_TIMEOUT),
    )
    return LLMService(provider=provider, max_retries=settings.LLM_MAX_RETRIES)
