from __future__ import annotations

from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _parse_url(database_url: str) -> tuple[object, dict[str, object]]:
    """Return (url, connect_args), converting libpq sslmode to asyncpg ssl."""
    url = make_url(database_url)
    connect_args: dict[str, object] = {}
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    if sslmode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = "require"
    elif sslmode == "disable":
        connect_args["ssl"] = False
    url = url.set(query=query)
    return url, connect_args


def init_db(database_url: str) -> AsyncEngine:
    global _engine, _session_factory
    url, connect_args = _parse_url(database_url)
    _engine = create_async_engine(
        url,  # type: ignore[arg-type]
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
        connect_args=connect_args,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    return _session_factory


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
