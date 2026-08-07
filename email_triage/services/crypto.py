"""Symmetric encryption for secrets at rest (Gmail refresh tokens, Plan 36).

The Gmail ``refresh_token`` is a long-lived credential that grants read access to a
user's mailbox. It must never be stored in the clear: a database leak would otherwise
expose every connected inbox. ``TokenCipher`` wraps Fernet (AES-128-CBC + HMAC-SHA256,
authenticated) with a key held only in the backend env (``GMAIL_TOKEN_ENC_KEY``).

Rotating the key invalidates every stored token (users would have to reconnect);
double-key rotation is deliberately out of scope for v1.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class TokenCipherError(Exception):
    """Raised when a ciphertext cannot be decrypted (wrong key or tampered)."""


class TokenCipher:
    """Encrypt/decrypt short secrets with a Fernet key.

    The key is a url-safe base64-encoded 32-byte value (``Fernet.generate_key()``).
    """

    def __init__(self, key: str) -> None:
        # Fernet validates the key shape here; a malformed key raises immediately at
        # construction (fail fast on misconfiguration) rather than at first use.
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str, ttl: int | None = None) -> str:
        """Decrypt a token. With ``ttl`` (seconds), also reject tokens older than that —
        used to bound the lifetime of the encrypted OAuth ``state`` (Plan 36)."""
        try:
            return self._fernet.decrypt(token.encode(), ttl=ttl).decode()
        except InvalidToken as exc:
            raise TokenCipherError("cannot decrypt token (wrong key or tampered)") from exc

    @staticmethod
    def generate_key() -> str:
        """A fresh Fernet key, for populating ``GMAIL_TOKEN_ENC_KEY``."""
        return Fernet.generate_key().decode()
