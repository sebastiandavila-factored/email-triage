from __future__ import annotations

from typing import Final

TRIAGE_WRITE: Final = "triage:write"
TRIAGE_CONFIGURE: Final = "triage:configure"
PROMPT_PUBLISH: Final = "prompt:publish"
WORKSPACE_MANAGE: Final = "workspace:manage"
WORKSPACE_DELETE: Final = "workspace:delete"
# Read this workspace's observability traces (trace-debug chat, Plan 31). Owner +
# admin only: it surfaces production telemetry, so members are excluded.
TRACES_READ: Final = "traces:read"

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {
            TRIAGE_WRITE,
            TRIAGE_CONFIGURE,
            PROMPT_PUBLISH,
            WORKSPACE_MANAGE,
            WORKSPACE_DELETE,
            TRACES_READ,
        }
    ),
    "admin": frozenset({TRIAGE_WRITE, TRIAGE_CONFIGURE, WORKSPACE_MANAGE, TRACES_READ}),
    "member": frozenset({TRIAGE_WRITE}),
}
