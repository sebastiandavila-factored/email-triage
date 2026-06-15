from __future__ import annotations

import base64
import hashlib
import secrets


def generate_code_verifier() -> str:
    """RFC 7636 §4.1: 43–128 URL-safe chars."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """RFC 7636 §4.2: S256 — SHA-256 then base64url without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
