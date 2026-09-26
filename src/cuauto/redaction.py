from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

SECRET_KEYS = re.compile(r"(?i)(password|passwd|secret|token|cookie|authorization|api[_-]?key)")
BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def redact(value: Any, pii_fields: frozenset[str] = frozenset(), max_string: int = 8_000) -> Any:
    """Recursively redact secrets/PII and bound persisted data."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:200]:
            clean_key = str(key)[:100]
            if SECRET_KEYS.search(clean_key) or clean_key.casefold() in pii_fields:
                out[clean_key] = "[REDACTED]"
            else:
                out[clean_key] = redact(item, pii_fields, max_string)
        return out
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(v, pii_fields, max_string) for v in list(value)[:200]]
    if isinstance(value, str):
        text = BEARER.sub("Bearer [REDACTED]", value)
        text = EMAIL.sub("[REDACTED_EMAIL]", text)
        text = SSN.sub("[REDACTED_SSN]", text)
        return text[:max_string]
    return value


def contains_secret(value: Any) -> bool:
    text = str(value)
    return bool(BEARER.search(text) or SSN.search(text) or SECRET_KEYS.search(text))
