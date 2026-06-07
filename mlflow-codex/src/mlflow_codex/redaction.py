from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

SECRET_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "password",
    "passwd",
    "secret",
    "client_secret",
    "authorization",
    "auth",
    "cookie",
    "private_key",
    "ssh_key",
    "credential",
    "credentials",
    "bearer",
    "x-api-key",
}


def redact(value: Any, *, max_string_length: int | None = None) -> Any:
    """Return a JSON-safe copy with common secret fields redacted."""
    if is_dataclass(value):
        return redact(asdict(value), max_string_length=max_string_length)

    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                cleaned[key_text] = "[REDACTED]"
            else:
                cleaned[key_text] = redact(child, max_string_length=max_string_length)
        return cleaned

    if isinstance(value, str):
        if max_string_length is not None and len(value) > max_string_length:
            omitted = len(value) - max_string_length
            return value[:max_string_length] + f"...[truncated {omitted} chars]"
        return value

    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
        return redact(text, max_string_length=max_string_length)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(child, max_string_length=max_string_length) for child in value]

    return value


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("_", "-")
    compact = normalized.replace("-", "")
    return normalized in SECRET_KEYS or compact in SECRET_KEYS
