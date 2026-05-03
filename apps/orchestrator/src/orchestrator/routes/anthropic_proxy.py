"""Slice 8: Anthropic reverse proxy.

The slice-7 invariant — "real Anthropic key never enters the sprite" —
rests on this route. The bridge inside the sprite hits
`POST {orchestrator}/api/_internal/anthropic-proxy/{sandbox_id}/v1/messages`
with `Authorization: Bearer <BRIDGE_TOKEN>`. We validate the bearer
against `Sandbox.bridge_token_hash`, strip it, swap in the real
`x-api-key` from `BridgeRuntimeConfig._anthropic_api_key`, and reverse-
proxy streaming to api.anthropic.com.

Contract locked in slice7.md §6b + slice8.md §4. **Async-correctness
audit:** this module must NOT import `requests` / `urllib` / `time.sleep`
— the test suite enforces that.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator, Mapping

import httpx
import structlog
from beanie import PydanticObjectId
from db.models import Sandbox
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

router = APIRouter()
_logger = structlog.get_logger("anthropic_proxy")

# RFC 7230 §6.1 hop-by-hop headers — never forwarded across a proxy.
# Plus auth headers we handle ourselves on each leg.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)
_DROP_INBOUND = _HOP_BY_HOP | {"authorization"}
_DROP_OUTBOUND = _HOP_BY_HOP | {"authorization", "x-api-key"}

# Public Anthropic API. Overridable by tests via `app.state.anthropic_proxy_upstream_base`.
_DEFAULT_UPSTREAM_BASE = "https://api.anthropic.com"


def _filter_inbound(
    headers: "Mapping[str, str]", *, real_key: str
) -> dict[str, str]:
    """Drop hop-by-hop + Authorization from the inbound bridge request,
    set `x-api-key: <real>` for the upstream call to Anthropic.

    Accepts any header mapping (Starlette's `Headers` or httpx's `Headers`)
    so this helper works on both request and response sides without a cast."""
    out = {k: v for k, v in headers.items() if k.lower() not in _DROP_INBOUND}
    out["x-api-key"] = real_key
    return out


def _filter_outbound(headers: "Mapping[str, str]") -> dict[str, str]:
    """Drop hop-by-hop + auth-related headers from the upstream response
    before relaying back to the bridge."""
    return {k: v for k, v in headers.items() if k.lower() not in _DROP_OUTBOUND}


def _bearer_token(authorization: str) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


async def _validate_bearer(sandbox_id: str, token: str | None) -> bool:
    """sha256 + `hmac.compare_digest` against `Sandbox.bridge_token_hash`.
    Returns False on missing/wrong/badly-formatted token, missing
    sandbox, or destroyed sandbox. Single response shape on the route
    side — no diagnostic detail to avoid leaking probe info.
    """
    if not token:
        return False
    try:
        sb_id = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001 — bson.InvalidId + ValueError + TypeError
        return False
    sandbox = await Sandbox.get(sb_id)
    if sandbox is None:
        return False
    if sandbox.status == "destroyed":
        return False
    if sandbox.bridge_token_hash is None:
        return False
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, sandbox.bridge_token_hash)


@router.api_route(
    "/anthropic-proxy/{sandbox_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def anthropic_proxy(
    sandbox_id: str, path: str, request: Request
) -> Response:
    token = _bearer_token(request.headers.get("authorization", ""))
    if not await _validate_bearer(sandbox_id, token):
        # Single response shape for missing/wrong/bad-format/wrong-sandbox/
        # destroyed — no probe channel.
        return Response(status_code=401)

    bridge_config = getattr(request.app.state, "bridge_config", None)
    real_key: str | None = (
        getattr(bridge_config, "_anthropic_api_key", None)
        if bridge_config is not None
        else None
    )
    if not real_key:
        return Response(status_code=503)

    client: httpx.AsyncClient | None = getattr(
        request.app.state, "anthropic_proxy_client", None
    )
    if client is None:
        return Response(status_code=503)

    upstream_base: str = getattr(
        request.app.state,
        "anthropic_proxy_upstream_base",
        _DEFAULT_UPSTREAM_BASE,
    )
    upstream_url = f"{upstream_base.rstrip('/')}/{path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    swapped = _filter_inbound(request.headers, real_key=real_key)

    upstream_req = client.build_request(
        method=request.method,
        url=upstream_url,
        headers=swapped,
        content=request.stream(),
    )
    try:
        upstream = await client.send(upstream_req, stream=True)
    except httpx.RequestError as exc:
        _logger.warning(
            "anthropic_proxy.upstream_error",
            error=str(exc)[:200],
            sandbox_id=sandbox_id,
        )
        return Response(status_code=502)

    # Don't echo upstream 5xx bodies — they could mention key prefixes
    # or rate-limit-bucket identifiers we don't want bridges seeing.
    if upstream.status_code >= 500:
        await upstream.aclose()
        return Response(status_code=502)

    out_headers = _filter_outbound(upstream.headers)
    # Drop transport-encoding-related headers because we're going to
    # restream as decompressed bytes. httpx's `aiter_bytes()` already
    # decompresses the upstream body — keeping a stale `Content-Encoding`
    # header (or `Content-Length` for the compressed size) makes the
    # client try to gunzip plaintext → "Decompression error: ZlibError"
    # in claude-agent-sdk.
    for h in ("content-encoding", "content-length"):
        out_headers.pop(h, None)
    # Anti-buffering for SSE: any nginx in front of us must NOT buffer
    # message-stream chunks (would defeat the streaming UX).
    out_headers["cache-control"] = "no-cache"
    out_headers["x-accel-buffering"] = "no"

    async def relay() -> AsyncIterator[bytes]:
        try:
            # `aiter_bytes()` auto-decompresses gzip/deflate/brotli per the
            # upstream's `Content-Encoding`. Combined with stripping that
            # header above, the client sees plaintext SSE chunks.
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            # Idempotent — also called in the BackgroundTask below for
            # the case where the generator never starts (e.g. client
            # disconnect before first chunk).
            await upstream.aclose()

    return StreamingResponse(
        relay(),
        status_code=upstream.status_code,
        headers=out_headers,
        background=BackgroundTask(upstream.aclose),
    )
