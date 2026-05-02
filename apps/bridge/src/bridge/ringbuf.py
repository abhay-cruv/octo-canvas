"""Per-chat ring buffer for replay-on-reconnect — slice 8 §11.

Bounds: 1000 frames OR 1 MB (whichever hits first). On reconnect the
bridge sends `Hello{last_acked_seq_per_chat}` and the orchestrator
responds with a `ChatState{last_seen_seq}` per chat. Anything in our
ring with seq > orchestrator's high-water-mark is resent.

Bytes-bound is a soft estimate (we use the JSON-encoded size of each
frame at insert time). We trade exactness for not having to carry a
full JSON encoder in the buffer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

_MAX_FRAMES = 1000
_MAX_BYTES = 1_000_000


@dataclass
class _Slot:
    seq: int
    json_bytes: bytes


class ChatRingBuffer:
    """Per-chat ring with seq-ordered eviction. Thread-unsafe; the
    bridge runs all chat I/O on a single asyncio loop."""

    def __init__(
        self,
        max_frames: int = _MAX_FRAMES,
        max_bytes: int = _MAX_BYTES,
    ) -> None:
        self._max_frames = max_frames
        self._max_bytes = max_bytes
        self._slots: deque[_Slot] = deque()
        self._bytes = 0

    def append(self, seq: int, json_bytes: bytes) -> None:
        """Insert. seq must be strictly greater than the previously
        appended seq (caller's responsibility)."""
        self._slots.append(_Slot(seq=seq, json_bytes=json_bytes))
        self._bytes += len(json_bytes)
        # Evict oldest until under both limits.
        while self._slots and (
            len(self._slots) > self._max_frames or self._bytes > self._max_bytes
        ):
            popped = self._slots.popleft()
            self._bytes -= len(popped.json_bytes)

    def ack(self, ack_seq: int) -> None:
        """Drop everything with seq <= ack_seq."""
        while self._slots and self._slots[0].seq <= ack_seq:
            popped = self._slots.popleft()
            self._bytes -= len(popped.json_bytes)

    def replay(self, after_seq: int) -> list[bytes]:
        """Return the JSON bytes for every retained frame with seq >
        after_seq. Used on reconnect after `ChatState{last_seen_seq}`."""
        return [s.json_bytes for s in self._slots if s.seq > after_seq]

    @property
    def size(self) -> int:
        return len(self._slots)

    @property
    def bytes(self) -> int:
        return self._bytes

    def lowest_seq(self) -> int | None:
        return self._slots[0].seq if self._slots else None

    def highest_seq(self) -> int | None:
        return self._slots[-1].seq if self._slots else None
