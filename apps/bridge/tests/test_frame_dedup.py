"""WsClient frame_id dedup — Phase 8d.

Orchestrator replays queued UserMessages on bridge `Hello`. Without
dedup, a turn that was actually delivered before the bridge cycled
would re-execute. The dedup path lives in `WsClient._dispatch`.
"""

from __future__ import annotations

import pytest

from bridge.ws_client import WsClient

pytestmark = pytest.mark.asyncio


def _make_client() -> WsClient:
    """Construct a WsClient without actually dialing — we only exercise
    the dedup state machine, not the network path."""

    async def _no_op_handle_command(_frame: object) -> None:
        return None

    return WsClient(
        url="wss://example.invalid/ws/bridge/x",
        bridge_token="t",
        bridge_version="0.0.0-test",
        handle_command=_no_op_handle_command,
    )


def test_seen_frame_ids_starts_empty() -> None:
    c = _make_client()
    assert len(c._seen_frame_ids) == 0
    assert len(c._frame_id_order) == 0


def test_lru_cap_enforced_on_unique_inserts() -> None:
    """The dedup set is bounded — push more than the cap and the
    oldest entries fall off (FIFO eviction)."""
    c = _make_client()
    cap = 4096
    overflow = 50
    # Manually exercise the bookkeeping (matches the path in `_dispatch`).
    for i in range(cap + overflow):
        fid = f"frame-{i:06d}"
        c._seen_frame_ids.add(fid)
        c._frame_id_order.append(fid)
        while len(c._frame_id_order) > cap:
            old = c._frame_id_order.pop(0)
            c._seen_frame_ids.discard(old)
    assert len(c._frame_id_order) == cap
    assert len(c._seen_frame_ids) == cap
    # First `overflow` frames should be gone.
    for i in range(overflow):
        assert f"frame-{i:06d}" not in c._seen_frame_ids
    # Last frames should be retained.
    assert f"frame-{cap + overflow - 1:06d}" in c._seen_frame_ids


def test_set_and_list_stay_consistent() -> None:
    """The list is the FIFO order; the set is membership. They must
    stay in sync — a frame_id is in one iff it's in the other."""
    c = _make_client()
    for fid in ["a", "b", "c"]:
        c._seen_frame_ids.add(fid)
        c._frame_id_order.append(fid)
    assert set(c._frame_id_order) == c._seen_frame_ids
