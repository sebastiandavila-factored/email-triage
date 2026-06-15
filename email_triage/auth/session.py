from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt

_ALGORITHM = "HS256"


def create_access_token(secret: str, user_id: uuid.UUID, expire_minutes: int = 30) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_access_token(secret: str, token: str) -> uuid.UUID | None:
    try:
        payload: dict[str, object] = jwt.decode(token, secret, algorithms=[_ALGORITHM])
        return uuid.UUID(str(payload["sub"]))
    except jwt.PyJWTError, KeyError, ValueError:
        return None
