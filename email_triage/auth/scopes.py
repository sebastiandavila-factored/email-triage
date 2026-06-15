from __future__ import annotations

from typing import Final

TRIAGE_WRITE: Final = "triage:write"
WORKSPACE_MANAGE: Final = "workspace:manage"
WORKSPACE_DELETE: Final = "workspace:delete"

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "owner": frozenset({TRIAGE_WRITE, WORKSPACE_MANAGE, WORKSPACE_DELETE}),
    "admin": frozenset({TRIAGE_WRITE, WORKSPACE_MANAGE}),
    "member": frozenset({TRIAGE_WRITE}),
}
