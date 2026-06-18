from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from email_triage.db.engine import get_session_factory
from email_triage.db.models import User
from email_triage.db.repos.invitations import InvitationRepo
from email_triage.db.repos.tenants import TenantRepo
from email_triage.db.repos.users import UserRepo
from email_triage.deps import (
    CurrentUserDep,
    DeleteWorkspaceDep,
    ManageMembersDep,
    SettingsDep,
    WorkspaceMemberDep,
)
from email_triage.services.workspace import WorkspaceError, WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
invitations_router = APIRouter(prefix="/invitations", tags=["workspaces"])


def _factory():  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    return factory


def _http(exc: WorkspaceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


# ── Schemas ───────────────────────────────────────────────────────────────────


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    plan: str
    role: str


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime


class CreateWorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ChangeRoleIn(BaseModel):
    role: str


class CreateInviteIn(BaseModel):
    email: EmailStr
    role: str


class CreateInviteOut(BaseModel):
    invitation_id: str
    email: str
    role: str
    link: str
    message: str = "Share this link with the invitee. It expires in 7 days."


class AcceptInviteIn(BaseModel):
    token: str


class AcceptInviteOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    role: str
    message: str = "Joined workspace."


# ── Workspaces ────────────────────────────────────────────────────────────────


@router.post("")
async def create_workspace(body: CreateWorkspaceIn, ctx: CurrentUserDep) -> WorkspaceOut:
    async with _factory()() as session, session.begin():
        tenant = await WorkspaceService().create_team(session, ctx.user_id, body.name)
        return WorkspaceOut(
            id=tenant.id, name=tenant.name, type=tenant.type, plan=tenant.plan, role="owner"
        )


@router.get("")
async def list_workspaces(ctx: CurrentUserDep) -> list[WorkspaceOut]:
    async with _factory()() as session:
        rows = await WorkspaceService().list_for_user(session, ctx.user_id)
    return [
        WorkspaceOut(id=t.id, name=t.name, type=t.type, plan=t.plan, role=role) for t, role in rows
    ]


@router.get("/{tid}")
async def get_workspace(tid: uuid.UUID, ctx: WorkspaceMemberDep) -> WorkspaceOut:
    async with _factory()() as session:
        tenant = await TenantRepo().get_by_id(session, tid)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceOut(
        id=tenant.id, name=tenant.name, type=tenant.type, plan=tenant.plan, role=ctx.role
    )


@router.delete("/{tid}", status_code=204)
async def delete_workspace(tid: uuid.UUID, ctx: DeleteWorkspaceDep) -> None:
    try:
        async with _factory()() as session, session.begin():
            await WorkspaceService().delete_workspace(session, tid)
    except WorkspaceError as exc:
        raise _http(exc) from exc


# ── Members ───────────────────────────────────────────────────────────────────


@router.get("/{tid}/members")
async def list_members(tid: uuid.UUID, ctx: WorkspaceMemberDep) -> list[MemberOut]:
    async with _factory()() as session:
        rows = await UserRepo().list_members(session, tid)
    return [
        MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=role)
        for u, role in rows
    ]


@router.patch("/{tid}/members/{uid}")
async def change_member_role(
    tid: uuid.UUID, uid: uuid.UUID, body: ChangeRoleIn, ctx: ManageMembersDep
) -> MemberOut:
    try:
        async with _factory()() as session, session.begin():
            membership = await WorkspaceService().change_role(
                session, tid, ctx.role, uid, body.role
            )
            user = await session.get(User, uid)
            assert user is not None  # change_role already verified membership
            return MemberOut(
                user_id=uid, email=user.email, display_name=user.display_name, role=membership.role
            )
    except WorkspaceError as exc:
        raise _http(exc) from exc


@router.delete("/{tid}/members/{uid}", status_code=204)
async def remove_member(tid: uuid.UUID, uid: uuid.UUID, ctx: WorkspaceMemberDep) -> None:
    # WorkspaceMemberDep (not Manage): self-remove (leave) is allowed for anyone;
    # the service enforces workspace:manage when removing someone else.
    try:
        async with _factory()() as session, session.begin():
            await WorkspaceService().remove_member(session, tid, ctx.user_id, ctx.role, uid)
    except WorkspaceError as exc:
        raise _http(exc) from exc


# ── Invitations ───────────────────────────────────────────────────────────────


@router.post("/{tid}/invitations")
async def create_invitation(
    tid: uuid.UUID, body: CreateInviteIn, ctx: ManageMembersDep, settings: SettingsDep
) -> CreateInviteOut:
    try:
        async with _factory()() as session, session.begin():
            invitation_id, token = await WorkspaceService().create_invitation(
                session, tid, ctx.user_id, str(body.email), body.role
            )
    except WorkspaceError as exc:
        raise _http(exc) from exc
    return CreateInviteOut(
        invitation_id=invitation_id,
        email=str(body.email).strip().lower(),
        role=body.role,
        link=f"{settings.frontend_url}/accept-invite#token={token}",
    )


@router.get("/{tid}/invitations")
async def list_invitations(tid: uuid.UUID, ctx: ManageMembersDep) -> list[InvitationOut]:
    async with _factory()() as session:
        rows = await InvitationRepo().list_pending(session, tid)
    return [
        InvitationOut(id=i.id, email=i.email, role=i.role, status=i.status, expires_at=i.expires_at)
        for i in rows
    ]


@router.delete("/{tid}/invitations/{iid}", status_code=204)
async def revoke_invitation(tid: uuid.UUID, iid: uuid.UUID, ctx: ManageMembersDep) -> None:
    async with _factory()() as session, session.begin():
        invitation = await InvitationRepo().get_by_id(session, iid)
        if invitation is None or invitation.tenant_id != tid:
            raise HTTPException(status_code=404, detail="Invitation not found")
        await InvitationRepo().set_status(session, invitation, "revoked")


@invitations_router.post("/accept")
async def accept_invitation(body: AcceptInviteIn, ctx: CurrentUserDep) -> AcceptInviteOut:
    try:
        async with _factory()() as session, session.begin():
            membership = await WorkspaceService().accept_invitation(
                session, ctx.user_id, ctx.email, body.token
            )
            tenant = await TenantRepo().get_by_id(session, membership.tenant_id)
            assert tenant is not None
            return AcceptInviteOut(
                tenant_id=tenant.id, tenant_name=tenant.name, role=membership.role
            )
    except WorkspaceError as exc:
        raise _http(exc) from exc
