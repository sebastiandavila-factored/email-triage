"""Triage Studio MCP server (Triage Studio F4).

Exposes the product as typed MCP tools so any Claude client can classify emails and
operate the Studio. It is a *client of the HTTP API* — it never imports the app or
the DB, so RBAC and business rules stay in one place (FastAPI) and this works against
a deployed instance.

Config comes from the environment only (never from tool args or the prompt):
- TRIAGE_API_URL        base URL of the FastAPI service (default http://localhost:8000)
- TRIAGE_API_KEY        workspace API key, for POST /triage (X-API-Key)
- TRIAGE_SESSION_TOKEN  Bearer JWT, for the Studio endpoints
- TRIAGE_WORKSPACE_ID   the workspace {tid} the Studio tools act on

Run over stdio (Claude Desktop / Code):  ``triage-mcp``
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

_DEFAULT_URL = "http://localhost:8000"
_TIMEOUT = 30.0


class ApiError(Exception):
    """An actionable error surfaced to the model (never a raw stack trace)."""


class ApiClient:
    """Thin async wrapper over the Triage HTTP API with error translation."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        session_token: str | None = None,
        workspace_id: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._http = http or httpx.AsyncClient(base_url=base_url, timeout=_TIMEOUT)
        self._api_key = api_key
        self._token = session_token
        self._wid = workspace_id

    def _api_key_headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ApiError("Set TRIAGE_API_KEY (the workspace API key) to classify emails.")
        return {"X-API-Key": self._api_key}

    def _bearer_headers(self) -> dict[str, str]:
        if not self._token:
            raise ApiError("Set TRIAGE_SESSION_TOKEN (a Bearer JWT) to use the Studio tools.")
        return {"Authorization": f"Bearer {self._token}"}

    def _workspace(self) -> str:
        if not self._wid:
            raise ApiError("Set TRIAGE_WORKSPACE_ID to the workspace these tools operate on.")
        return self._wid

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            resp = await self._http.request(method, path, headers=headers, json=json)
        except httpx.RequestError as exc:
            raise ApiError(f"Cannot reach the Triage API: {exc}") from exc
        if resp.is_success:
            return resp.json() if resp.content else None
        # Translate a 4xx/5xx into a message the model can act on.
        detail: Any
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise ApiError(f"API returned {resp.status_code}: {detail}")

    # ── tools' backing calls ────────────────────────────────────────────────────

    async def classify(self, subject: str, sender: str, body: str) -> Any:
        return await self._request(
            "POST",
            "/triage",
            headers=self._api_key_headers(),
            json={"subject": subject, "sender": sender, "body": body},
        )

    async def list_categories(self) -> Any:
        return await self._request(
            "GET", f"/workspaces/{self._workspace()}/categories", headers=self._bearer_headers()
        )

    async def create_category(self, slug: str, name: str, description: str) -> Any:
        return await self._request(
            "POST",
            f"/workspaces/{self._workspace()}/categories",
            headers=self._bearer_headers(),
            json={"slug": slug, "name": name, "description": description},
        )

    async def add_example(
        self,
        category_id: str,
        kind: str,
        subject: str,
        body: str,
        expected_reply: str | None,
    ) -> Any:
        return await self._request(
            "POST",
            f"/workspaces/{self._workspace()}/categories/{category_id}/examples",
            headers=self._bearer_headers(),
            json={
                "kind": kind,
                "subject": subject,
                "body": body,
                "expected_reply": expected_reply,
            },
        )

    async def preview_prompt(self) -> Any:
        return await self._request(
            "POST",
            f"/workspaces/{self._workspace()}/prompt/preview",
            headers=self._bearer_headers(),
        )

    async def list_versions(self) -> Any:
        return await self._request(
            "GET",
            f"/workspaces/{self._workspace()}/prompt/versions",
            headers=self._bearer_headers(),
        )


def build_client() -> ApiClient:
    """Construct the client from the environment (called lazily on first tool use)."""
    return ApiClient(
        base_url=os.getenv("TRIAGE_API_URL", _DEFAULT_URL),
        api_key=os.getenv("TRIAGE_API_KEY"),
        session_token=os.getenv("TRIAGE_SESSION_TOKEN"),
        workspace_id=os.getenv("TRIAGE_WORKSPACE_ID"),
    )


_client: ApiClient | None = None


def _client_instance() -> ApiClient:
    global _client
    if _client is None:
        _client = build_client()
    return _client


server = MCPServer(
    name="triage-studio",
    version="0.1.0",
    instructions=(
        "Classify support emails and manage a workspace's Triage Studio configuration "
        "(categories, few-shot examples, prompt). Credentials come from the server's "
        "environment; never ask the user to paste API keys or tokens into tool arguments."
    ),
)


@server.tool()
async def classify_email(subject: str, sender: str, body: str) -> Any:
    """Classify one support email into the workspace's taxonomy and draft a reply.

    Returns {category, draft_reply, confidence}. Uses the workspace API key.
    """
    return await _client_instance().classify(subject, sender, body)


@server.tool()
async def list_categories() -> Any:
    """List the configured triage categories for the workspace."""
    return await _client_instance().list_categories()


@server.tool()
async def create_category(slug: str, name: str, description: str) -> Any:
    """Create a triage category. slug is lowercase [a-z0-9_], stable and immutable."""
    return await _client_instance().create_category(slug, name, description)


@server.tool()
async def add_example(
    category_id: str,
    subject: str,
    body: str,
    kind: str = "positive",
    expected_reply: str | None = None,
) -> Any:
    """Attach a few-shot example to a category. kind is 'positive' or 'negative'."""
    return await _client_instance().add_example(category_id, kind, subject, body, expected_reply)


@server.tool()
async def preview_prompt() -> Any:
    """Compile and return the workspace's current draft prompt (does not publish)."""
    return await _client_instance().preview_prompt()


@server.tool()
async def list_prompt_versions() -> Any:
    """List the workspace's published prompt versions (newest first)."""
    return await _client_instance().list_versions()


def main() -> None:
    """Console entrypoint (``triage-mcp``): serve the tools over stdio."""
    server.run("stdio")


if __name__ == "__main__":
    main()
