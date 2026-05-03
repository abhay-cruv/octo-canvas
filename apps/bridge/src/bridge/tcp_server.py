"""Slice 8 (post-pivot) — bridge TCP listener.

Runs when `BRIDGE_TRANSPORT=service_proxy`. The bridge becomes a TCP
server on `localhost:<BRIDGE_LISTEN_PORT>` inside the sprite. The
orchestrator dials in via `WSS /v1/sprites/{name}/proxy` (Sprites' TCP
proxy WebSocket), which transparently relays bytes to this listener.

Wire framing: length-prefixed JSON frames (4-byte big-endian length, then
that many bytes of UTF-8 JSON). One inbound frame per `OrchestratorToBridge`
variant; one outbound frame per `BridgeToOrchestrator` variant. We pick
length-prefixed over newline-delimited because Sprites' proxy is a raw
TCP relay — newline boundaries can split mid-frame under load.

One client at a time. A second connecting client receives a
`{"type":"error","kind":"busy"}` frame and is closed. Multi-instance
orchestrator support is the user's problem (route requests to the
owning instance via Redis).

Lives alongside `ws_client.py` (legacy dial-back). The `main.py` arg
flag picks one or the other; both files coexist intact.
"""

from __future__ import annotations

import asyncio
import struct
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from agent_config import ClaudeCredentials

from bridge.chat_mux import ChatMux

_logger = structlog.get_logger("bridge.tcp_server")

# 4-byte length prefix max. ~16 MB per frame — generous for tool result
# previews; smaller would force chunking on big diffs.
_MAX_FRAME_BYTES = 16 * 1024 * 1024


async def _read_frame(reader: asyncio.StreamReader) -> bytes | None:
    """Read one length-prefixed frame. Returns None on clean EOF."""
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError:
        return None
    (length,) = struct.unpack(">I", header)
    if length == 0:
        return b""
    if length > _MAX_FRAME_BYTES:
        raise ValueError(f"frame too large: {length} bytes (max {_MAX_FRAME_BYTES})")
    try:
        return await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise ValueError(
            f"truncated frame: expected {length} bytes, got {len(exc.partial)}"
        ) from exc


async def _write_frame(writer: asyncio.StreamWriter, payload: bytes) -> None:
    if len(payload) > _MAX_FRAME_BYTES:
        raise ValueError(f"frame too large: {len(payload)} bytes")
    writer.write(struct.pack(">I", len(payload)))
    writer.write(payload)
    await writer.drain()


async def run_tcp_server(
    *,
    host: str,
    port: int,
    work_root: str,
    credentials: ClaudeCredentials,
    max_live_chats: int,
    handle_command: Callable[[Any, ChatMux], Awaitable[None]] | None = None,
) -> None:
    """Bind + serve. `handle_command` lets tests inject a custom dispatcher.
    The default dispatch maps `OrchestratorToBridge` variants onto
    `ChatMux.handle_user_message` / `cancel`."""
    # Lazy import — keeps test discovery fast for tests that don't
    # exercise this path.
    from shared_models.wire_protocol import (
        CancelChat,
        OrchestratorToBridgeAdapter,
        UserMessage as WireUserMessage,
    )

    active_lock = asyncio.Lock()
    active_writer: dict[str, asyncio.StreamWriter] = {}
    # Per-chat sequence allocation. Mirrors `WsClient`'s semantics —
    # the orchestrator's wire model requires `seq` on every event-class
    # frame for ordering/replay. Bridge process is the seq authority on
    # its side; orchestrator may rewrite on persist but the bridge view
    # stays monotonic per `chat_id`.
    next_seq: dict[str, int] = {}

    async def emit(chat_id: str, frame_type: str, payload: dict[str, Any]) -> None:
        """ChatMux → wire frame. Allocates per-chat `seq` and stamps the
        frame envelope. Connection-class frames (no chat_id) skip seq."""
        body: dict[str, Any] = {"type": frame_type, "chat_id": chat_id, **payload}
        if chat_id:
            seq = next_seq.get(chat_id, 0) + 1
            next_seq[chat_id] = seq
            body["seq"] = seq
        line = _json_dumps(body).encode("utf-8")
        writer = active_writer.get("w")
        if writer is None:
            return
        try:
            await _write_frame(writer, line)
        except (ConnectionError, asyncio.CancelledError):
            return

    mux = ChatMux(
        cwd=work_root,
        credentials=credentials,
        emit=emit,
        max_live_chats=max_live_chats,
    )

    async def _default_dispatch(frame: Any, mux: ChatMux) -> None:
        if isinstance(frame, WireUserMessage):
            await mux.handle_user_message(
                chat_id=frame.chat_id,
                text=frame.text,
                claude_session_id=frame.claude_session_id,
            )
        elif isinstance(frame, CancelChat):
            await mux.cancel(frame.chat_id)
        # Other variants (Ping/Ack/etc) are reserved or handled inline.

    dispatcher = handle_command or _default_dispatch

    async def _handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        # Newest-wins: the orchestrator reconnects on every WS bounce,
        # and the OLD writer can take seconds to fully die (Sprites
        # /proxy WS doesn't ping → bridge can't tell it's dead).
        # Sending a "busy" frame to the new connection just wedges it.
        # Instead: kick the old writer, take the slot for the new one.
        async with active_lock:
            old = active_writer.pop("w", None)
            active_writer["w"] = writer
        if old is not None:
            _logger.info("bridge.tcp_server.evicted_previous_client")
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
        _logger.info("bridge.tcp_server.client_connected", peer=str(peer))
        try:
            while True:
                payload = await _read_frame(reader)
                if payload is None:
                    break
                if not payload:
                    continue
                try:
                    frame = OrchestratorToBridgeAdapter.validate_json(payload)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "bridge.tcp_server.invalid_frame",
                        error=str(exc)[:200],
                    )
                    continue
                try:
                    await dispatcher(frame, mux)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "bridge.tcp_server.dispatch_error",
                        error=str(exc)[:200],
                    )
        except (ConnectionError, asyncio.CancelledError):
            pass
        except Exception as exc:  # noqa: BLE001 — keep server alive on unexpected failures
            _logger.warning(
                "bridge.tcp_server.client_handler_unhandled",
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
                peer=str(peer),
            )
        finally:
            _logger.info("bridge.tcp_server.client_disconnected", peer=str(peer))
            async with active_lock:
                # Only release the slot if WE still own it. With the
                # newest-wins policy, an evicted predecessor's task can
                # exit AFTER the successor took the slot; we must not
                # clobber the live writer.
                if active_writer.get("w") is writer:
                    active_writer.pop("w", None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    server = await asyncio.start_server(_handle_client, host=host, port=port)
    addr = ", ".join(str(s.getsockname()) for s in server.sockets)
    _logger.info("bridge.tcp_server.listening", address=addr)
    try:
        async with server:
            await server.serve_forever()
    finally:
        await mux.shutdown()


def _json_dumps(obj: dict[str, Any]) -> str:
    """Compact JSON, no spaces, no NaN. Stays tight on the wire."""
    import json as _json
    return _json.dumps(obj, separators=(",", ":"), allow_nan=False)
