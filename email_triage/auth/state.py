from __future__ import annotations

import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def _signer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="oauth2-pkce-state")


def generate_pkce_cookie(secret: str, code_verifier: str) -> tuple[str, str]:
    """Sign a payload containing the code_verifier and a random state token.

    Returns ``(signed_cookie_value, state_token)``. The caller sets the cookie
    and sends the same state to Google; on callback the two must match (CSRF).
    """
    state_token = secrets.token_urlsafe(16)
    payload = {"cv": code_verifier, "st": state_token}
    return _signer(secret).dumps(payload), state_token  # type: ignore[return-value]


def unpack_pkce_cookie(
    secret: str,
    cookie_value: str,
    max_age: int = 300,
) -> tuple[str, str] | None:
    """Verify and unpack the PKCE cookie.

    Returns (code_verifier, state_token) or None if invalid/expired.
    """
    try:
        payload: dict[str, str] = _signer(secret).loads(cookie_value, max_age=max_age)
        return payload["cv"], payload["st"]
    except BadSignature, SignatureExpired, KeyError:
        return None
