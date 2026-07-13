from __future__ import annotations

import re
from urllib.parse import urlparse

SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def clean_ngrok_authtoken(token: str) -> str:
    return re.sub(r"^[^A-Za-z0-9_-]+|[^A-Za-z0-9_-]+$", "", token.strip())


def normalize_ngrok_domain(value: str | None) -> str | None:
    if value is None:
        return None

    text = value.strip().rstrip("/")
    if not text:
        return None

    if SCHEME_RE.match(text):
        parsed = urlparse(text)
        text = parsed.hostname or parsed.netloc or parsed.path

    text = re.split(r"[/?#]", text, maxsplit=1)[0].strip().rstrip("/")
    return text or None


def normalize_public_url(value: str | None) -> str | None:
    if value is None:
        return None

    text = value.strip().rstrip("/")
    if not text:
        return None

    if not SCHEME_RE.match(text):
        text = f"https://{text}"

    return text.rstrip("/") or None
