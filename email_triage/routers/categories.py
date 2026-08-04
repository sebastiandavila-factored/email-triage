from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from email_triage.db.engine import get_session_factory
from email_triage.db.models import Category
from email_triage.deps import ConfigureTriageDep, WorkspaceMemberDep
from email_triage.services.triage_config import TriageConfigError, TriageConfigService

router = APIRouter(prefix="/workspaces/{tid}/categories", tags=["triage-config"])


def _factory():  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    return factory


def _http(exc: TriageConfigError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


# ── Schemas ───────────────────────────────────────────────────────────────────


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str
    is_active: bool
    sort_order: int


class CreateCategoryIn(BaseModel):
    slug: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)


class UpdateCategoryIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


def _to_out(category: Category) -> CategoryOut:
    return CategoryOut.model_validate(category)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
async def list_categories(
    tid: uuid.UUID,
    ctx: WorkspaceMemberDep,
    active: bool = Query(default=False, description="Only active categories"),
) -> list[CategoryOut]:
    async with _factory()() as session:
        rows = await TriageConfigService().list_categories(session, tid, active_only=active)
    return [_to_out(c) for c in rows]


@router.post("", status_code=201)
async def create_category(
    tid: uuid.UUID, body: CreateCategoryIn, ctx: ConfigureTriageDep
) -> CategoryOut:
    try:
        async with _factory()() as session, session.begin():
            category = await TriageConfigService().create_category(
                session, tid, body.slug, body.name, body.description
            )
            return _to_out(category)
    except TriageConfigError as exc:
        raise _http(exc) from exc


@router.patch("/{cid}")
async def update_category(
    tid: uuid.UUID, cid: uuid.UUID, body: UpdateCategoryIn, ctx: ConfigureTriageDep
) -> CategoryOut:
    try:
        async with _factory()() as session, session.begin():
            category = await TriageConfigService().update_category(
                session,
                tid,
                cid,
                name=body.name,
                description=body.description,
                is_active=body.is_active,
                sort_order=body.sort_order,
            )
            return _to_out(category)
    except TriageConfigError as exc:
        raise _http(exc) from exc


@router.delete("/{cid}", status_code=204)
async def delete_category(tid: uuid.UUID, cid: uuid.UUID, ctx: ConfigureTriageDep) -> None:
    try:
        async with _factory()() as session, session.begin():
            await TriageConfigService().delete_category(session, tid, cid)
    except TriageConfigError as exc:
        raise _http(exc) from exc
