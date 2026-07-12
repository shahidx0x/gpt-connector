from __future__ import annotations

import re


_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?P<value>sk-[A-Za-z0-9_\-]{20,})"),
    re.compile(r"(?P<value>gh[pousr]_[A-Za-z0-9_]{20,})"),
    re.compile(r"(?P<value>AKIA[0-9A-Z]{16})"),
    re.compile(
        r"(?i)(?P<prefix>\b(?:api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*)"
        r"(?P<value>[\"']?[^\"'\s,;]{8,}[\"']?)"
    ),
    re.compile(r"(?i)(?P<prefix>\bBearer\s+)(?P<value>[A-Za-z0-9._\-]{12,})"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----",
        re.MULTILINE,
    ),
]


def _replacement(match: re.Match[str]) -> str:
    prefix = match.groupdict().get("prefix") or ""
    return f"{prefix}[REDACTED]"


def redact_text(text: str) -> tuple[str, int]:
    redacted = text
    total = 0
    for pattern in _SECRET_PATTERNS:
        redacted, count = pattern.subn(_replacement, redacted)
        total += count
    return redacted, total

