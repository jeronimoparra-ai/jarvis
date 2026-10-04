#!/usr/bin/env python3
"""Redacción de secretos en logs: api_key, token, password, Authorization."""

import logging
import re

_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*['\"]?)([^'\"\s,}]+)"),
    re.compile(r"(?i)(token\s*[:=]\s*['\"]?)([^'\"\s,}]+)"),
    re.compile(r"(?i)(password\s*[:=]\s*['\"]?)([^'\"\s,}]+)"),
    re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}]+)"),
    re.compile(r"\b(gsk_[A-Za-z0-9_-]{8,})"),  # Groq keys
)


def redact(text: str) -> str:
    """Reemplaza valores de secretos por ***. Idempotente y barato."""
    if not text or not isinstance(text, str):
        return text
    for i, pat in enumerate(_PATTERNS):
        if i < 4:
            text = pat.sub(r"\1***", text)
        else:
            text = pat.sub("gsk_***", text)
    return text


class RedactFilter(logging.Filter):
    """Filtro de logging: jamás emite secretos."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: redact(v) for k, v in record.args.items()}
                else:
                    record.args = tuple(
                        redact(a) if isinstance(a, str) else a
                        for a in record.args)
        except Exception:
            pass
        return True
