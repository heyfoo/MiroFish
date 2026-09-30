"""
OpenAI Chat Completions compatibility helpers.

This module keeps existing behavior for legacy models/providers while
gracefully adapting request parameters for GPT-5 and later models.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# GPT-5 and later official model ids reject non-default temperature and the
# legacy max_tokens parameter. Match only a leading "gpt-<major>" so names
# such as "my-gpt-5-proxy" stay on the legacy request shape.
_MODERN_OPENAI_MODEL = re.compile(r"gpt-(\d+)", re.IGNORECASE)


def uses_completion_tokens_api(model: Optional[str]) -> bool:
    """Return True for GPT-5 and later models that require the newer request shape."""
    if not model:
        return False
    match = _MODERN_OPENAI_MODEL.match(model.strip())
    if not match:
        return False
    return int(match.group(1)) >= 5


def is_gpt5_family(model: Optional[str]) -> bool:
    """Return True when model belongs to GPT-5 family aliases/snapshots."""
    if not model:
        return False
    normalized = model.strip().lower()
    return normalized.startswith("gpt-5") and uses_completion_tokens_api(model)


def create_chat_completion(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Create a chat completion with model-specific request parameters.

    Compatibility strategy:
    - For GPT-5 and later, avoid sending temperature by default.
    - For token limit, use `max_completion_tokens` on those models, `max_tokens` otherwise.
    - Preserve the legacy request shape for every earlier model and third-party provider.
    - Propagate provider errors unchanged instead of guessing from message text.
    """
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    if response_format is not None:
        kwargs["response_format"] = response_format

    modern_openai = uses_completion_tokens_api(model)

    if temperature is not None and not modern_openai:
        kwargs["temperature"] = temperature

    if max_tokens is not None:
        if modern_openai:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

    return client.chat.completions.create(**kwargs)


def extract_chat_completion_text(response: Any) -> str:
    """Extract plain text from chat completion response across SDK content shapes."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    message = getattr(choices[0], "message", None)
    if message is None:
        return ""

    content = getattr(message, "content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text_obj = item.get("text")
                if isinstance(text_obj, dict):
                    text_obj = text_obj.get("value")
                if isinstance(text_obj, str):
                    chunks.append(text_obj)
                elif isinstance(item.get("content"), str):
                    chunks.append(item["content"])
                continue

            text_obj = getattr(item, "text", None)
            if isinstance(text_obj, dict):
                text_obj = text_obj.get("value")
            if isinstance(text_obj, str):
                chunks.append(text_obj)
                continue

            content_obj = getattr(item, "content", None)
            if isinstance(content_obj, str):
                chunks.append(content_obj)

        return "".join(chunks).strip()

    return str(content or "")
