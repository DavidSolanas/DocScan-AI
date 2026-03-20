# backend/services/llm_service.py
from __future__ import annotations

import base64
import json
import re
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


# --- JSON extraction helpers ---

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


def _extract_json(raw: str) -> str:
    """Best-effort extraction of a JSON object or array from an LLM response.

    Handles:
    - <think>...</think> blocks (Qwen3, DeepSeek-R1, etc.)
    - Markdown code fences (```json ... ```)
    - Leading/trailing prose around the JSON
    """
    # 1. Strip thinking blocks
    cleaned = _THINK_RE.sub("", raw).strip()

    # 2. Try direct parse on cleaned text
    if cleaned and cleaned[0] in ("{", "["):
        return cleaned

    # 3. Extract from code fence
    m = _CODE_FENCE_RE.search(cleaned)
    if m:
        return m.group(1).strip()

    # 4. Find first { or [ and last matching } or ]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = cleaned.find(open_c)
        if start != -1:
            end = cleaned.rfind(close_c)
            if end > start:
                return cleaned[start:end + 1]

    return cleaned  # give up, return as-is and let json.loads report the error


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

    async def complete_vision(self, prompt: str, image_bytes: bytes) -> str:
        """Send an image + text prompt to Ollama via /api/chat (multimodal).

        Uses base64-encoded image in the messages[].images array.
        Response text is at message.content (NOT response like /api/generate).
        """
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(f"{self.host}/api/chat", json=payload)
                response.raise_for_status()
                return response.json()["message"]["content"]
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
        """Single completion. Does NOT retry — surfaces errors immediately.

        Strips <think> blocks so callers doing regex/keyword matching aren't confused
        by reasoning tokens from models like Qwen3.
        """
        raw = await self._provider.complete(prompt, system=system, json_mode=json_mode)
        return _THINK_RE.sub("", raw).strip()

    async def complete_json(
        self, prompt: str, system: str | None = None
    ) -> dict:
        """Completion with JSON mode. Retries up to max_retries on JSONDecodeError only.

        Handles models that wrap JSON in <think> blocks or markdown code fences
        (e.g. Qwen3, DeepSeek-R1).
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            raw = await self._provider.complete(prompt, system=system, json_mode=True)
            try:
                return json.loads(_extract_json(raw))
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
