from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager

import email_triage.db.models  # noqa: F401 — side effect: registers models with Base.metadata  # pyright: ignore[reportUnusedImport]
import pytest
from email_triage.config import Settings
from email_triage.db import engine as db_engine_module
from email_triage.db.base import Base
from email_triage.deps import get_llm_service, get_settings
from email_triage.main import app
from email_triage.schemas import Category, StreamingTriageResponse, TriageRequest, TriageResponse
from email_triage.services.llm import LLMService
from fastapi.testclient import TestClient
from logfire.testing import capfire as capfire  # noqa: PLC0414 — re-export as pytest fixture
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_API_KEY = "test-api-key"

_MOCK_RESPONSE = TriageResponse(
    category=Category.REFUNDS,
    draft_reply="We will process your refund shortly.",
    confidence=0.95,
)


def _mock_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        groq_api_key="test-groq-key",
        api_key=TEST_API_KEY,
        database_url=None,  # prevent .env DATABASE_URL from being picked up
        bcrypt_rounds=4,  # fast for tests
    )


class MockLLMService(LLMService):
    def __init__(self) -> None:
        pass

    async def triage(self, req: TriageRequest) -> TriageResponse:
        return _MOCK_RESPONSE


class FailingLLMService(LLMService):
    def __init__(self) -> None:
        pass

    async def triage(self, req: TriageRequest) -> TriageResponse:
        import httpx

        raise httpx.ConnectError("Groq unreachable")


_FULL_REPLY = "We will process your refund shortly."
_STREAMING_PARTIALS = [
    StreamingTriageResponse(category=Category.REFUNDS, confidence=0.95, draft_reply=""),
    StreamingTriageResponse(category=Category.REFUNDS, confidence=0.95, draft_reply="We will"),
    StreamingTriageResponse(
        category=Category.REFUNDS, confidence=0.95, draft_reply="We will process"
    ),
    StreamingTriageResponse(category=Category.REFUNDS, confidence=0.95, draft_reply=_FULL_REPLY),
]


class StreamingMockLLMService(LLMService):
    def __init__(self) -> None:
        pass

    async def triage(self, req: TriageRequest) -> TriageResponse:
        return _MOCK_RESPONSE

    @asynccontextmanager
    async def triage_stream(self, req: TriageRequest):  # type: ignore[override]
        class _FakeResult:
            async def stream_output(
                self, *, debounce_by: float | None = None
            ) -> AsyncGenerator[StreamingTriageResponse]:
                for p in _STREAMING_PARTIALS:
                    yield p

        yield _FakeResult()


class FailingStreamLLMService(LLMService):
    def __init__(self) -> None:
        pass

    async def triage(self, req: TriageRequest) -> TriageResponse:
        return _MOCK_RESPONSE

    @asynccontextmanager
    async def triage_stream(self, req: TriageRequest):  # type: ignore[override]
        from email_triage.services.llm import LLMError

        raise LLMError("Groq unreachable")
        yield  # make it a generator


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:  # pyright: ignore[reportUnusedFunction]
    # slowapi keeps an in-memory counter keyed by client IP for the whole
    # process; without a reset the TestClient (always the same IP) accumulates
    # hits across tests and trips the limit in unrelated cases.
    from email_triage.deps import limiter

    limiter.reset()


@pytest.fixture()
def client() -> Generator[TestClient]:
    app.dependency_overrides[get_settings] = _mock_settings
    app.dependency_overrides[get_llm_service] = MockLLMService
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def failing_client() -> Generator[TestClient]:
    app.dependency_overrides[get_settings] = _mock_settings
    app.dependency_overrides[get_llm_service] = FailingLLMService
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def streaming_client() -> Generator[TestClient]:
    app.dependency_overrides[get_settings] = _mock_settings
    app.dependency_overrides[get_llm_service] = StreamingMockLLMService
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def failing_stream_client() -> Generator[TestClient]:
    app.dependency_overrides[get_settings] = _mock_settings
    app.dependency_overrides[get_llm_service] = FailingStreamLLMService
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
async def db_session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    db_engine_module._session_factory = factory  # type: ignore[attr-defined]

    async with factory() as session:
        yield session

    db_engine_module._session_factory = None  # type: ignore[attr-defined]
    await engine.dispose()
