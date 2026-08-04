from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from email_triage.db.engine import get_session_factory
from email_triage.db.models import PromptVersion, TriageExample
from email_triage.deps import (
    ConfigureTriageDep,
    PublishPromptDep,
    WorkspaceMemberDep,
    clear_triage_service_cache,
)
from email_triage.services.prompt_compiler import TemplateOverrides
from email_triage.services.prompt_studio import PromptStudioError, PromptStudioService

router = APIRouter(prefix="/workspaces/{tid}", tags=["triage-config"])


def _factory():  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    return factory


def _http(exc: PromptStudioError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


# ── Schemas ───────────────────────────────────────────────────────────────────


class ExampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    kind: str
    subject: str
    body: str
    expected_reply: str | None


class CreateExampleIn(BaseModel):
    kind: str = "positive"
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    expected_reply: str | None = None


class DraftIO(BaseModel):
    role: str | None = None
    task: str | None = None
    guardrails: str | None = None
    tone: str | None = None


class PreviewOut(BaseModel):
    prompt: str
    allowed_slugs: list[str]


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    is_active: bool
    accuracy: float | None
    macro_f1: float | None
    published_at: datetime


def _example_out(ex: TriageExample) -> ExampleOut:
    return ExampleOut.model_validate(ex)


def _version_out(v: PromptVersion) -> VersionOut:
    return VersionOut.model_validate(v)


# ── Examples ──────────────────────────────────────────────────────────────────


@router.get("/categories/{cid}/examples")
async def list_examples(
    tid: uuid.UUID, cid: uuid.UUID, ctx: WorkspaceMemberDep
) -> list[ExampleOut]:
    async with _factory()() as session:
        rows = await PromptStudioService().list_examples(session, tid, cid)
    return [_example_out(e) for e in rows]


@router.post("/categories/{cid}/examples", status_code=201)
async def add_example(
    tid: uuid.UUID, cid: uuid.UUID, body: CreateExampleIn, ctx: ConfigureTriageDep
) -> ExampleOut:
    try:
        async with _factory()() as session, session.begin():
            example = await PromptStudioService().add_example(
                session,
                tid,
                cid,
                body.kind,
                body.subject,
                body.body,
                body.expected_reply,
                ctx.user_id,
            )
            return _example_out(example)
    except PromptStudioError as exc:
        raise _http(exc) from exc


@router.delete("/examples/{eid}", status_code=204)
async def delete_example(tid: uuid.UUID, eid: uuid.UUID, ctx: ConfigureTriageDep) -> None:
    try:
        async with _factory()() as session, session.begin():
            await PromptStudioService().delete_example(session, tid, eid)
    except PromptStudioError as exc:
        raise _http(exc) from exc


# ── Draft / preview ───────────────────────────────────────────────────────────


@router.get("/prompt/draft")
async def get_draft(tid: uuid.UUID, ctx: WorkspaceMemberDep) -> DraftIO:
    async with _factory()() as session:
        ov = await PromptStudioService().get_draft_overrides(session, tid)
    return DraftIO(role=ov.role, task=ov.task, guardrails=ov.guardrails, tone=ov.tone)


@router.put("/prompt/draft")
async def save_draft(tid: uuid.UUID, body: DraftIO, ctx: ConfigureTriageDep) -> DraftIO:
    overrides = TemplateOverrides(
        role=body.role, task=body.task, guardrails=body.guardrails, tone=body.tone
    )
    async with _factory()() as session, session.begin():
        await PromptStudioService().save_draft(session, tid, overrides, ctx.user_id)
    return body


@router.post("/prompt/preview")
async def preview_prompt(tid: uuid.UUID, ctx: ConfigureTriageDep) -> PreviewOut:
    try:
        async with _factory()() as session:
            draft = await PromptStudioService().compile_draft(session, tid)
    except PromptStudioError as exc:
        raise _http(exc) from exc
    return PreviewOut(prompt=draft.prompt, allowed_slugs=sorted(draft.allowed_slugs))


# ── Versions / publish / rollback ─────────────────────────────────────────────


@router.get("/prompt/versions")
async def list_versions(tid: uuid.UUID, ctx: WorkspaceMemberDep) -> list[VersionOut]:
    async with _factory()() as session:
        rows = await PromptStudioService().versions.list_for_tenant(session, tid)
    return [_version_out(v) for v in rows]


@router.post("/prompt/publish", status_code=201)
async def publish_prompt(tid: uuid.UUID, ctx: PublishPromptDep) -> VersionOut:
    try:
        async with _factory()() as session, session.begin():
            version = await PromptStudioService().publish(session, tid, ctx.user_id)
            out = _version_out(version)
    except PromptStudioError as exc:
        raise _http(exc) from exc
    clear_triage_service_cache()  # serve the freshly published version
    return out


@router.post("/prompt/versions/{v}/activate")
async def activate_version(tid: uuid.UUID, v: int, ctx: PublishPromptDep) -> VersionOut:
    try:
        async with _factory()() as session, session.begin():
            version = await PromptStudioService().rollback(session, tid, v)
            out = _version_out(version)
    except PromptStudioError as exc:
        raise _http(exc) from exc
    clear_triage_service_cache()
    return out
