"""Tests for the Triage Studio MCP server (F4).

The tools are thin wrappers over ``ApiClient``, so we test the client against an
httpx MockTransport (real request building + error translation, no network) and
assert the server registered the expected typed tools.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

pytest.importorskip("mcp")  # skip cleanly if the optional MCP extra isn't installed

from email_triage.mcp_server import ApiClient, ApiError, server  # noqa: E402

_WID = "11111111-1111-1111-1111-111111111111"


def _client(handler: Any) -> ApiClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://test")
    return ApiClient(
        "http://test",
        api_key="wk_key",
        session_token="jwt",
        workspace_id=_WID,
        http=http,
    )


# ── ApiClient behaviour ───────────────────────────────────────────────────────


async def test_classify_uses_api_key_header() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(
            200, json={"category": "refunds", "draft_reply": "ok", "confidence": 0.9}
        )

    result = await _client(handler).classify("subj", "a@b.com", "body")
    assert seen["path"] == "/triage"
    assert seen["key"] == "wk_key"
    assert result["category"] == "refunds"


async def test_list_categories_uses_bearer_and_workspace() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[{"slug": "refunds"}])

    result = await _client(handler).list_categories()
    assert seen["path"] == f"/workspaces/{_WID}/categories"
    assert seen["auth"] == "Bearer jwt"
    assert result[0]["slug"] == "refunds"


async def test_create_category_posts_body() -> None:
    import json as _json

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _json.loads(request.content)
        return httpx.Response(201, json={"slug": "returns"})

    await _client(handler).create_category("returns", "Returns", "desc")
    assert seen["body"] == {"slug": "returns", "name": "Returns", "description": "desc"}


async def test_http_error_is_translated_to_actionable_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "Scope required: triage:configure"})

    with pytest.raises(ApiError) as exc:
        await _client(handler).create_category("x", "X", "d")
    assert "403" in str(exc.value)
    assert "triage:configure" in str(exc.value)


async def test_network_error_is_translated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ApiError) as exc:
        await _client(handler).list_categories()
    assert "Cannot reach" in str(exc.value)


async def test_missing_api_key_is_actionable() -> None:
    client = ApiClient("http://test", api_key=None, session_token="jwt", workspace_id=_WID)
    with pytest.raises(ApiError) as exc:
        await client.classify("s", "a@b.com", "b")
    assert "TRIAGE_API_KEY" in str(exc.value)


async def test_missing_token_is_actionable() -> None:
    client = ApiClient("http://test", api_key="k", session_token=None, workspace_id=_WID)
    with pytest.raises(ApiError) as exc:
        await client.list_categories()
    assert "TRIAGE_SESSION_TOKEN" in str(exc.value)


async def test_missing_workspace_is_actionable() -> None:
    client = ApiClient("http://test", api_key="k", session_token="jwt", workspace_id=None)
    with pytest.raises(ApiError) as exc:
        await client.preview_prompt()
    assert "TRIAGE_WORKSPACE_ID" in str(exc.value)


# ── Server registration ───────────────────────────────────────────────────────


async def test_server_exposes_typed_tools() -> None:
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert {
        "classify_email",
        "list_categories",
        "create_category",
        "add_example",
        "preview_prompt",
        "list_prompt_versions",
    } <= names
    classify = next(t for t in tools if t.name == "classify_email")
    # The schema is derived from the typed signature (domain 4: tool design).
    assert set(classify.input_schema["properties"]) == {"subject", "sender", "body"}
