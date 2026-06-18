"""Business-rule tests for WorkspaceService (Plan 21), against a real SQLite
session — no mocks, so repos + rules are exercised together."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from email_triage.auth.api_key import hash_secret
from email_triage.db.models import User
from email_triage.db.repos.invitations import InvitationRepo
from email_triage.db.repos.tenants import TenantRepo
from email_triage.db.repos.users import UserRepo
from email_triage.services.workspace import WorkspaceError, WorkspaceService
from sqlalchemy.ext.asyncio import AsyncSession


async def _mk_user(session: AsyncSession, email: str) -> User:
    user = User(email=email, display_name=email.split("@")[0], email_verified=True)
    session.add(user)
    await session.flush()
    return user


# ── workspaces ────────────────────────────────────────────────────────────────


async def test_create_team_makes_creator_owner(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "owner@acme.com")
    tenant = await WorkspaceService().create_team(db_session, owner.id, "Acme")

    assert tenant.type == "team"
    membership = await UserRepo().get_membership_in(db_session, owner.id, tenant.id)
    assert membership is not None and membership.role == "owner"


async def test_delete_personal_workspace_forbidden(db_session: AsyncSession) -> None:
    tenant = await TenantRepo().create_personal(db_session, "Solo's workspace")
    with pytest.raises(WorkspaceError) as exc:
        await WorkspaceService().delete_workspace(db_session, tenant.id)
    assert exc.value.status_code == 403


async def test_delete_team_workspace_ok(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "owner@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    await svc.delete_workspace(db_session, tenant.id)
    assert await TenantRepo().get_by_id(db_session, tenant.id) is None


# ── roles ─────────────────────────────────────────────────────────────────────


async def test_owner_promotes_member_to_admin(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    member = await _mk_user(db_session, "m@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    await TenantRepo().add_member(db_session, member.id, tenant.id, "member")

    updated = await svc.change_role(db_session, tenant.id, "owner", member.id, "admin")
    assert updated.role == "admin"


async def test_admin_cannot_manage_owner(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    admin = await _mk_user(db_session, "a@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    await TenantRepo().add_member(db_session, admin.id, tenant.id, "admin")

    with pytest.raises(WorkspaceError) as exc:
        await svc.change_role(db_session, tenant.id, "admin", owner.id, "member")
    assert exc.value.status_code == 403


async def test_cannot_demote_last_owner(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")

    with pytest.raises(WorkspaceError) as exc:
        await svc.change_role(db_session, tenant.id, "owner", owner.id, "member")
    assert exc.value.status_code == 409


# ── remove / leave ────────────────────────────────────────────────────────────


async def test_member_can_leave(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    member = await _mk_user(db_session, "m@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    await TenantRepo().add_member(db_session, member.id, tenant.id, "member")

    await svc.remove_member(db_session, tenant.id, member.id, "member", member.id)
    assert await UserRepo().get_membership_in(db_session, member.id, tenant.id) is None


async def test_member_cannot_remove_others(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    member = await _mk_user(db_session, "m@acme.com")
    other = await _mk_user(db_session, "x@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    await TenantRepo().add_member(db_session, member.id, tenant.id, "member")
    await TenantRepo().add_member(db_session, other.id, tenant.id, "member")

    with pytest.raises(WorkspaceError) as exc:
        await svc.remove_member(db_session, tenant.id, member.id, "member", other.id)
    assert exc.value.status_code == 403


async def test_cannot_remove_last_owner(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")

    with pytest.raises(WorkspaceError) as exc:
        await svc.remove_member(db_session, tenant.id, owner.id, "owner", owner.id)
    assert exc.value.status_code == 409


# ── invitations ───────────────────────────────────────────────────────────────


async def test_invite_and_accept(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")

    _, token = await svc.create_invitation(
        db_session, tenant.id, owner.id, "New@Acme.com", "member"
    )
    invitee = await _mk_user(db_session, "new@acme.com")

    membership = await svc.accept_invitation(db_session, invitee.id, "new@acme.com", token)
    assert membership.role == "member"
    assert membership.tenant_id == tenant.id


async def test_accept_wrong_email_forbidden(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    _, token = await svc.create_invitation(
        db_session, tenant.id, owner.id, "new@acme.com", "member"
    )
    intruder = await _mk_user(db_session, "intruder@evil.com")

    with pytest.raises(WorkspaceError) as exc:
        await svc.accept_invitation(db_session, intruder.id, "intruder@evil.com", token)
    assert exc.value.status_code == 403


async def test_accept_expired_invitation(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    # Craft an already-expired invitation directly.
    token = "expired-token"
    await InvitationRepo().create(
        db_session,
        tenant_id=tenant.id,
        email="late@acme.com",
        role="member",
        token_hash=hash_secret(token),
        invited_by=owner.id,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    invitee = await _mk_user(db_session, "late@acme.com")

    with pytest.raises(WorkspaceError) as exc:
        await svc.accept_invitation(db_session, invitee.id, "late@acme.com", token)
    assert exc.value.status_code == 410


async def test_invite_owner_role_rejected(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    with pytest.raises(WorkspaceError) as exc:
        await svc.create_invitation(db_session, tenant.id, owner.id, "x@acme.com", "owner")
    assert exc.value.status_code == 422


async def test_invite_existing_member_rejected(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    member = await _mk_user(db_session, "m@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    await TenantRepo().add_member(db_session, member.id, tenant.id, "member")

    with pytest.raises(WorkspaceError) as exc:
        await svc.create_invitation(db_session, tenant.id, owner.id, "m@acme.com", "member")
    assert exc.value.status_code == 409


async def test_invite_duplicate_pending_rejected(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "o@acme.com")
    svc = WorkspaceService()
    tenant = await svc.create_team(db_session, owner.id, "Acme")
    await svc.create_invitation(db_session, tenant.id, owner.id, "dup@acme.com", "member")

    with pytest.raises(WorkspaceError) as exc:
        await svc.create_invitation(db_session, tenant.id, owner.id, "dup@acme.com", "member")
    assert exc.value.status_code == 409
