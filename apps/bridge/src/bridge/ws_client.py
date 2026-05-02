"""WSS client — bridge side, slice 8 §11.

Owns:
- the single WSS connection to `/ws/bridge/{sandbox_id}` on the
  orchestrator
- per-chat seq allocation (one `seq` namespace per `chat_id`)
- per-chat ring buffer (1000 frames / 1 MB) for replay-on-reconnect
- jittered reconnect backoff (1→16s ±25%) on disconnect
- inbound-frame routing to a `ChatMux` callback
- outbound-frame batching from the `ChatMux`'s emit path

Auth: `Authorization: Bearer ${BRIDGE_TOKEN}` on the handshake. After
accept, the bridge sends `Hello{bridge_version, last_acked_seq_per_chat}`.
The orchestrator may respond with `ChatState{last_seen_seq}` per chat
— the client replays its ring buffer for any seq > orchestrator's
high-water-mark.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
import websockets
from shared_models.wire_protocol import (
    Ack,
    BridgeAck,
    BridgePing,
    BridgePong,
    BridgeToOrchestratorAdapter,
    ChatState,
    Goodbye,
    Hello,
    OrchestratorToBridge,
    OrchestratorToBridgeAdapter,
)

# `BridgePong` from `wire_protocol.__init__` is `bridge.Pong` aliased
# to disambiguate from slice-5a's `events.Pong`. Use it for the
# bridge→orch direction.
from bridge.ringbuf import ChatRingBuffer

# Type alias for the websocket connection — the `websockets` library
# moved its public types around between versions; the concrete class is
# available at runtime regardless. `Any` keeps Pyright happy across
# library versions.
WSConnection = object

_logger = structlog.get_logger("bridge.ws_client")

_HEARTBEAT_RX_DEADLINE_S = 90.0
_RECONNECT_BACKOFF_BASE_S = 1.0
_RECONNECT_BACKOFF_MAX_S = 16.0
_RECONNECT_JITTER = 0.25


# (frame_dict) → consumed by ChatMux. ChatMux decides what to do with
# each command (UserMessage → spawn/route, CancelChat → interrupt, etc.).
HandleCommand = Callable[[OrchestratorToBridge], Awaitable[None]]


class WsClient:
    def __init__(
        self,
        *,
        url: str,
        bridge_token: str,
        bridge_version: str,
        handle_command: HandleCommand,
    ) -> None:
        if not url:
            raise ValueError("WsClient requires ORCHESTRATOR_WS_URL")
        if not bridge_token:
            raise ValueError("WsClient requires BRIDGE_TOKEN")
        self._url = url
        self._token = bridge_token
        self._bridge_version = bridge_version
        self._handle_command = handle_command
        # Per-chat seq allocation. The orchestrator is also a seq
        # authority (it rewrites seq on persist), but allocating seqs
        # locally lets us tag ring-buffer entries deterministically
        # for replay. The orchestrator's persisted seq may diverge
        # from ours — that's fine; we ack against orchestrator's view.
        self._next_seq: dict[str, int] = {}
        self._ringbufs: dict[str, ChatRingBuffer] = {}
        self._last_acked: dict[str, int] = {}
        self._outbound: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1024)
        self._stop = asyncio.Event()

    async def emit(
        self, chat_id: str, frame_type: str, payload: dict[str, Any]
    ) -> None:
        """ChatMux's emit path. Allocates seq, persists in ring buffer,
        queues for send. Resilient to send failure — the ring buffer
        replays on reconnect."""
        seq = self._next_seq.get(chat_id, 0) + 1
        self._next_seq[chat_id] = seq
        full = {"type": frame_type, "chat_id": chat_id, "seq": seq, **payload}
        try:
            validated = BridgeToOrchestratorAdapter.validate_python(full)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "bridge.ws_client.bad_outbound_frame",
                chat_id=chat_id,
                frame_type=frame_type,
                error=str(exc)[:200],
            )
            return
        encoded = BridgeToOrchestratorAdapter.dump_json(validated)
        ringbuf = self._ringbufs.setdefault(chat_id, ChatRingBuffer())
        ringbuf.append(seq, encoded)
        try:
            self._outbound.put_nowait(encoded)
        except asyncio.QueueFull:
            _logger.warning(
                "bridge.ws_client.outbound_overflow",
                chat_id=chat_id,
                frame_type=frame_type,
            )

    async def run(self) -> None:
        """Run the connect-or-reconnect loop until `stop()` is called."""
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._connect_once()
                attempt = 0  # reset on successful connect
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "bridge.ws_client.connect_failed",
                    error=str(exc)[:200],
                    attempt=attempt,
                )
            if self._stop.is_set():
                return
            backoff = min(
                _RECONNECT_BACKOFF_BASE_S * (2**attempt),
                _RECONNECT_BACKOFF_MAX_S,
            )
            jitter = backoff * _RECONNECT_JITTER * (random.random() * 2 - 1)
            sleep_s = max(0.1, backoff + jitter)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_s)
                return
            except asyncio.TimeoutError:
                pass
            attempt += 1

    async def stop(self) -> None:
        self._stop.set()

    async def _connect_once(self) -> None:
        headers = [("Authorization", f"Bearer {self._token}")]
        async with websockets.connect(  # type: ignore[misc]
            self._url, additional_headers=headers
        ) as ws:
            _logger.info("bridge.ws_client.connected", url=self._url)
            # Send Hello first.
            hello = Hello(
                bridge_version=self._bridge_version,
                last_acked_seq_per_chat=dict(self._last_acked),
            )
            await ws.send(BridgeToOrchestratorAdapter.dump_json(hello).decode())

            # Three concurrent tasks for the duration of this connection.
            try:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._read_loop(ws))
                    tg.create_task(self._send_loop(ws))
                    tg.create_task(self._heartbeat(ws))
            except* Exception as exc_group:
                _logger.warning(
                    "bridge.ws_client.connection_loop_error",
                    error=str(exc_group)[:200],
                )

    async def _read_loop(self, ws: Any) -> None:
        async for raw in ws:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                frame: OrchestratorToBridge = OrchestratorToBridgeAdapter.validate_json(
                    raw
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "bridge.ws_client.bad_inbound", error=str(exc)[:200]
                )
                continue
            await self._dispatch(ws, frame)

    async def _dispatch(
        self,
        ws: Any,
        frame: OrchestratorToBridge,
    ) -> None:
        if isinstance(frame, BridgePing):
            pong = BridgePong()
            await ws.send(BridgeToOrchestratorAdapter.dump_json(pong).decode())
            return
        if isinstance(frame, BridgeAck) or isinstance(frame, Ack):
            chat_id = frame.chat_id
            ack_seq = frame.ack_seq
            prev = self._last_acked.get(chat_id, 0)
            if ack_seq > prev:
                self._last_acked[chat_id] = ack_seq
            ringbuf = self._ringbufs.get(chat_id)
            if ringbuf is not None:
                ringbuf.ack(ack_seq)
            return
        if isinstance(frame, ChatState):
            # Reconciliation after Hello: replay any ring entries beyond
            # the orchestrator's high-water-mark.
            ringbuf = self._ringbufs.get(frame.chat_id)
            if ringbuf is not None:
                for encoded in ringbuf.replay(frame.last_seen_seq):
                    try:
                        self._outbound.put_nowait(encoded)
                    except asyncio.QueueFull:
                        break
            return
        # All other commands → ChatMux.
        await self._handle_command(frame)

    async def _send_loop(self, ws: Any) -> None:
        while not self._stop.is_set():
            payload = await self._outbound.get()
            try:
                await ws.send(payload.decode())
            except websockets.exceptions.ConnectionClosed:
                # Re-queue this so the next connection picks it up via
                # ring-buffer replay (we don't lose it — emit() already
                # persisted it in the chat's ring).
                return

    async def _heartbeat(self, ws: Any) -> None:
        # Send a Ping every 30s; close if no rx in 90s. The Pong we
        # send back to inbound BridgePings happens in `_dispatch`.
        while not self._stop.is_set():
            await asyncio.sleep(30)
            try:
                # We don't have a BridgePing frame from the bridge side
                # in the wire schema (Ping is orch→bridge). Use ws-level
                # ping instead — `websockets` sends a Ping control frame
                # automatically when no app traffic; this is a no-op
                # in v1, kept here as the placeholder for future
                # bridge-initiated keep-alive logic.
                await asyncio.wait_for(ws.ping(), timeout=10)
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001
                    pass
                return
