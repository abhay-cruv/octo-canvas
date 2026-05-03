"""Bridge idle-exit watcher — Phase 8d.

The bridge daemon exits cleanly after a configurable idle window so
Sprites can hibernate the sandbox. This is the unit-level test of
`_wait_for_idle`; the integration with the actual WSS dialer is
exercised by manual smoke against a real sprite.
"""

from __future__ import annotations

import asyncio

import pytest

from bridge.main import _wait_for_idle

pytestmark = pytest.mark.asyncio


class _FakeMux:
    def __init__(self, has_live: bool = False) -> None:
        self._has_live = has_live

    def has_live_chats(self) -> bool:
        return self._has_live


async def test_returns_quickly_when_no_chats() -> None:
    """`idle_after_s=0` + tight poll → returns inside two ticks."""
    mux = _FakeMux(has_live=False)
    await asyncio.wait_for(
        _wait_for_idle(mux, idle_after_s=0, poll_s=0.05), timeout=2.0
    )


async def test_does_not_return_while_chats_live() -> None:
    """If `has_live_chats()` keeps returning True the watcher never
    returns within the test budget."""
    mux = _FakeMux(has_live=True)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            _wait_for_idle(mux, idle_after_s=0, poll_s=0.05), timeout=1.0
        )


async def test_resets_on_new_chat_during_quiet_window() -> None:
    """A chat appearing mid-window resets the timer — the watcher
    only returns after the window holds steady-quiet end-to-end."""
    state = {"live": False}

    class FlippingMux:
        def has_live_chats(self) -> bool:
            return state["live"]

    mux = FlippingMux()

    async def flipper() -> None:
        await asyncio.sleep(0.4)
        state["live"] = True
        await asyncio.sleep(0.4)
        state["live"] = False

    flip_task = asyncio.create_task(flipper())
    # idle_after_s=0.6 is longer than each ~0.4s quiet stretch — so
    # the flip mid-window resets the counter, and the watcher can't
    # return inside the 1.0s budget.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            _wait_for_idle(mux, idle_after_s=1, poll_s=0.05), timeout=1.0
        )
    flip_task.cancel()
    try:
        await flip_task
    except asyncio.CancelledError:
        pass
