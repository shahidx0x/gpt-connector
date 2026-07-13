from __future__ import annotations

from localcontrol.cli import _clean_ngrok_authtoken
from localcontrol.ngrok_values import normalize_ngrok_domain, normalize_public_url


def test_clean_ngrok_authtoken_removes_invalid_edge_characters():
    token = "\u25acabc_DEF-123\u25ac"

    assert _clean_ngrok_authtoken(token) == "abc_DEF-123"


def test_normalize_ngrok_domain_accepts_url_with_trailing_slash():
    assert normalize_ngrok_domain(" https://demo.ngrok-free.app/ ") == "demo.ngrok-free.app"


def test_normalize_public_url_removes_trailing_slash_and_adds_scheme():
    assert normalize_public_url("demo.ngrok-free.app/") == "https://demo.ngrok-free.app"
