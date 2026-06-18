"""Business rules for team workspaces, members and invitations.

Repos do SQL; this service does the *rules* that are neither SQL nor HTTP —
last-owner protection, role hierarchy, invite validity. Keeping them here makes
them unit-testable without spinning up the API. Methods take primitives (ids,
roles, emails), never web types, so the service stays transport-agnostic; the
router maps WorkspaceError → HTTPException.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.auth.api_key import hash_secret
from email_triage.auth.scopes import ROLE_SCOPES, WORKSPACE_MANAGE
from email_triage.db.models import Membership, Tenant
from email_triage.db.repos.invitations import InvitationRepo
from email_triage.db.repos.tenants import TenantRepo
from email_triage.db.repos.users import UserRepo

_log = structlog.get_logger()

_INVITE_TTL = timedelta(days=7)
_INVITABLE_ROLES = frozenset({"admin", "member"})
_ALL_ROLES = frozenset({"owner", "admin", "member"})


class WorkspaceError(Exception):
    """A business-rule violation, carrying the HTTP status the router should use."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _expired(expires_at: datetime) -> bool:
    # SQLite (tests) may hand back naive datetimes; treat them as UTC so the
    # comparison never raises aware-vs-naive.
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    return exp < datetime.now(UTC)


class WorkspaceService:
    def __init__(self) -> None:
        self.tenants = TenantRepo()
        self.users = UserRepo()
        self.invitations = InvitationRepo()

    # ── workspaces ─────────────────────────────────────────────────────────────

    async def create_team(self, session: AsyncSession, owner_id: uuid.UUID, name: str) -> Tenant:
        tenant = await self.tenants.create_team(session, name)
        await self.tenants.add_member(session, owner_id, tenant.id, "owner")
        return tenant

    async def list_for_user(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> list[tuple[Tenant, str]]:
        return await self.tenants.list_for_user(session, user_id)

    async def delete_workspace(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        tenant = await self.tenants.get_by_id(session, tenant_id)
        if tenant is None:
            raise WorkspaceError(404, "Workspace not found")
        if tenant.type == "personal":
            raise WorkspaceError(403, "Cannot delete a personal workspace")
        await self.tenants.delete(session, tenant_id)

    # ── members ────────────────────────────────────────────────────────────────

    async def change_role(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_role: str,
        target_uid: uuid.UUID,
        new_role: str,
    ) -> Membership:
        if new_role not in _ALL_ROLES:
            raise WorkspaceError(422, f"Invalid role: {new_role}")

        target = await self.users.get_membership_in(session, target_uid, tenant_id)
        if target is None:
            raise WorkspaceError(404, "User is not a member of this workspace")

        # Hierarchy: an admin may not touch owners nor mint new owners.
        if actor_role != "owner" and (target.role == "owner" or new_role == "owner"):
            raise WorkspaceError(403, "Only an owner can manage owners")

        # Never demote the last owner.
        if (
            target.role == "owner"
            and new_role != "owner"
            and await self.users.count_owners(session, tenant_id) <= 1
        ):
            raise WorkspaceError(409, "Cannot demote the last owner")

        target.role = new_role
        await session.flush()
        _log.info("workspace.role_changed", tenant_id=str(tenant_id), role=new_role)
        return target

    async def remove_member(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_role: str,
        target_uid: uuid.UUID,
    ) -> None:
        target = await self.users.get_membership_in(session, target_uid, tenant_id)
        if target is None:
            raise WorkspaceError(404, "User is not a member of this workspace")

        is_self = actor_id == target_uid
        if not is_self:
            # Removing someone else requires manage scope + the role hierarchy.
            if WORKSPACE_MANAGE not in ROLE_SCOPES.get(actor_role, frozenset()):
                raise WorkspaceError(403, "Scope required: workspace:manage")
            if actor_role != "owner" and target.role == "owner":
                raise WorkspaceError(403, "Only an owner can remove an owner")

        # Never leave a workspace owner-less.
        if target.role == "owner" and await self.users.count_owners(session, tenant_id) <= 1:
            raise WorkspaceError(409, "Cannot remove the last owner")

        await self.users.delete_membership(session, target_uid, tenant_id)
        _log.info("workspace.member_removed", tenant_id=str(tenant_id), self_remove=is_self)

    # ── invitations ────────────────────────────────────────────────────────────

    async def create_invitation(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        invited_by: uuid.UUID,
        email: str,
        role: str,
    ) -> tuple[str, str]:
        """Returns (invitation_id, plaintext_token). Only the token's sha256 is
        stored; the plaintext is shown to the inviter once."""
        if role not in _INVITABLE_ROLES:
            raise WorkspaceError(422, "Invitations may only grant 'admin' or 'member'")
        email = email.strip().lower()

        existing_user = await self.users.get_by_email(session, email)
        if existing_user is not None:
            already = await self.users.get_membership_in(session, existing_user.id, tenant_id)
            if already is not None:
                raise WorkspaceError(409, "That user is already a member")
        if await self.invitations.get_pending_for_email(session, tenant_id, email) is not None:
            raise WorkspaceError(409, "A pending invitation already exists for that email")

        token = secrets.token_urlsafe(32)
        invitation = await self.invitations.create(
            session,
            tenant_id=tenant_id,
            email=email,
            role=role,
            token_hash=hash_secret(token),
            invited_by=invited_by,
            expires_at=datetime.now(UTC) + _INVITE_TTL,
        )
        return str(invitation.id), token

    async def accept_invitation(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        user_email: str,
        token: str,
    ) -> Membership:
        invitation = await self.invitations.get_by_token_hash(session, hash_secret(token))
        if invitation is None:
            raise WorkspaceError(404, "Invitation not found")
        if invitation.status != "pending":
            raise WorkspaceError(409, "Invitation already used or revoked")
        if _expired(invitation.expires_at):
            raise WorkspaceError(410, "Invitation has expired")
        if invitation.email != user_email.strip().lower():
            raise WorkspaceError(403, "This invitation was issued for a different email")

        existing = await self.users.get_membership_in(session, user_id, invitation.tenant_id)
        if existing is not None:
            raise WorkspaceError(409, "You are already a member of this workspace")

        membership = await self.tenants.add_member(
            session, user_id, invitation.tenant_id, invitation.role
        )
        await self.invitations.set_status(
            session, invitation, "accepted", accepted_at=datetime.now(UTC)
        )
        _log.info("workspace.invite_accepted", tenant_id=str(invitation.tenant_id))
        return membership
