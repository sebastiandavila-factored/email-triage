"""Per-tenant API keys, Stripe-style: ``et_<tenant_id>_<secret>``.

Why not bcrypt (the previous scheme)?
- bcrypt is a *slow* hash, designed for low-entropy human passwords so that
  brute force stays expensive. An API key is `secrets.token_urlsafe(32)` →
  256 bits of entropy; brute force is already impossible, so bcrypt buys
  nothing and costs ~250 ms per check.
- Worse, bcrypt hashes are not searchable: you cannot look a key up, so the
  old code scanned *every* tenant and ran bcrypt against each — O(N) work and
  a CPU-exhaustion (DoS) vector that grows with the customer base.

The fix is to make the presented key *self-locating*: the plaintext carries
the tenant id in the clear, so verification is a single O(1) lookup followed
by a constant-time hash comparison of the high-entropy secret. sha256 is the
right primitive here precisely because the secret is high-entropy.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

_PREFIX = "et"
_SECRET_BYTES = 32  # → 43-char url-safe secret, 256 bits of entropy


def issue_api_key(tenant_id: uuid.UUID) -> tuple[str, str]:
    """Return ``(plaintext_key, stored_hash)`` for a tenant.

    The plaintext is shown to the user exactly once; only the hash is stored.
    """
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    plaintext = f"{_PREFIX}_{tenant_id}_{secret}"
    return plaintext, hash_secret(secret)


def hash_secret(secret: str) -> str:
    """sha256 of the secret, hex-encoded. Deterministic → searchable."""
    return hashlib.sha256(secret.encode()).hexdigest()


def parse_api_key(key: str) -> tuple[uuid.UUID, str] | None:
    """Split ``et_<tenant_id>_<secret>`` → ``(tenant_id, secret)`` or None.

    A UUID never contains ``_`` (only hyphens), so ``split("_", 2)`` cleanly
    isolates the secret even though the secret's alphabet includes ``_``.
    """
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != _PREFIX:
        return None
    try:
        return uuid.UUID(parts[1]), parts[2]
    except ValueError:
        return None


def secret_matches(secret: str, stored_hash: str) -> bool:
    """Constant-time comparison to avoid leaking the hash via timing."""
    return hmac.compare_digest(hash_secret(secret), stored_hash)
