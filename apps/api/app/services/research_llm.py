from __future__ import annotations

import copy
import json
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings


class ResearchLLMError(RuntimeError):
    """A provider failure that is safe to handle with an evidence-only fallback."""


_CIRCUIT_LOCK = threading.Lock()
_CIRCUIT_OPEN_UNTIL: dict[str, float] = {}
_CIRCUIT_COOLDOWN_SECONDS = 15.0


def provider_name(settings: Settings) -> str:
    return str(getattr(settings, "research_llm_provider", "groq") or "groq").strip().lower()


def model_metadata(settings: Settings) -> dict[str, str]:
    return {"provider": provider_name(settings), "name": settings.research_llm_model}


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        cleaned = cleaned.removesuffix("```").strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            value = json.loads(cleaned[start : end + 1])
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the provider-safe strict form without mutating the caller's schema."""
    normalized = copy.deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(normalized)
    return normalized


def _openai_compatible_payload(
    *, prompt: str, settings: Settings, max_output_tokens: int, json_schema: dict[str, Any] | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": settings.research_llm_model,
        "messages": [
            {
                "role": "system",
                "content": "Return only valid JSON matching the requested schema. Do not add markdown.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_completion_tokens": max(64, min(int(max_output_tokens), 480)),
    }
    if json_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "research_response",
                "strict": True,
                "schema": _strict_json_schema(json_schema),
            },
        }
    else:
        payload["response_format"] = {"type": "json_object"}
    if provider_name(settings) == "groq":
        payload["reasoning_effort"] = "low"
    return payload


def _ollama_payload(
    *, prompt: str, settings: Settings, max_output_tokens: int, json_schema: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "model": settings.research_llm_model,
        "stream": False,
        "format": json_schema or "json",
        "options": {
            "temperature": 0.1,
            "num_predict": max(64, min(int(max_output_tokens), 480)),
        },
        "prompt": prompt,
    }


def _response_content(raw: dict[str, Any], provider: str) -> str:
    if provider == "ollama":
        return str(raw.get("response") or "")
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        )
    return ""


def call_json_model(
    *,
    prompt: str,
    settings: Settings,
    max_output_tokens: int = 240,
    json_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the configured provider within one bounded end-to-end timeout budget."""
    provider = provider_name(settings)
    if provider not in {"groq", "openai_compatible", "ollama"}:
        raise ResearchLLMError("unsupported_research_llm_provider")

    circuit_key = f"{provider}:{settings.research_llm_base_url}:{settings.research_llm_model}"
    with _CIRCUIT_LOCK:
        if _CIRCUIT_OPEN_UNTIL.get(circuit_key, 0.0) > time.monotonic():
            raise ResearchLLMError("research_model_circuit_open")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "AiStockCN-Research/1.0 (+https://aistockcn.com)",
    }
    if provider == "ollama":
        url = f"{settings.research_llm_base_url.rstrip('/')}/api/generate"
        payload = _ollama_payload(
            prompt=prompt,
            settings=settings,
            max_output_tokens=max_output_tokens,
            json_schema=json_schema,
        )
    else:
        api_key = str(getattr(settings, "research_llm_api_key", "") or "").strip()
        if not api_key:
            raise ResearchLLMError("research_model_credentials_missing")
        headers["Authorization"] = f"Bearer {api_key}"
        url = f"{settings.research_llm_base_url.rstrip('/')}/chat/completions"
        payload = _openai_compatible_payload(
            prompt=prompt,
            settings=settings,
            max_output_tokens=max_output_tokens,
            json_schema=json_schema,
        )

    timeout_budget = max(float(settings.research_llm_timeout_seconds), 1.0)
    deadline = time.monotonic() + timeout_budget
    attempts = max(int(getattr(settings, "research_llm_max_retries", 1)), 0) + 1
    last_error: Exception | None = None

    for attempt in range(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=remaining) as response:
                raw = json.loads(response.read().decode("utf-8"))
            result = _extract_json_object(_response_content(raw, provider))
            if not result:
                raise ResearchLLMError("research_model_invalid_response")
            with _CIRCUIT_LOCK:
                _CIRCUIT_OPEN_UNTIL.pop(circuit_key, None)
            return result
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 409, 429} and exc.code < 500:
                break
        except (TimeoutError, URLError, json.JSONDecodeError, ResearchLLMError) as exc:
            last_error = exc
            if isinstance(exc, TimeoutError):
                break

        if attempt < attempts - 1:
            delay = min(0.35 * (2 ** attempt), max(deadline - time.monotonic(), 0.0))
            if delay > 0:
                time.sleep(delay)

    with _CIRCUIT_LOCK:
        _CIRCUIT_OPEN_UNTIL[circuit_key] = time.monotonic() + _CIRCUIT_COOLDOWN_SECONDS
    if isinstance(last_error, ResearchLLMError):
        raise last_error
    raise ResearchLLMError("research_model_unavailable") from last_error
