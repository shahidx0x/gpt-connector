from __future__ import annotations

from localcontrol.cli import _clean_ngrok_authtoken


def test_clean_ngrok_authtoken_removes_invalid_edge_characters():
    token = "\u25acabc_DEF-123\u25ac"

    assert _clean_ngrok_authtoken(token) == "abc_DEF-123"
