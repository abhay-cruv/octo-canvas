"""ChatRingBuffer eviction + replay — slice 8 §11."""

from __future__ import annotations

from bridge.ringbuf import ChatRingBuffer


def test_append_and_replay_returns_seqs_above_threshold() -> None:
    rb = ChatRingBuffer()
    for i in range(1, 6):
        rb.append(i, f"frame-{i}".encode())
    out = rb.replay(after_seq=3)
    assert out == [b"frame-4", b"frame-5"]


def test_ack_drops_lower_or_equal_seqs() -> None:
    rb = ChatRingBuffer()
    for i in range(1, 6):
        rb.append(i, f"f{i}".encode())
    rb.ack(3)
    assert rb.size == 2
    assert rb.lowest_seq() == 4
    assert rb.replay(after_seq=0) == [b"f4", b"f5"]


def test_evicts_when_frame_count_exceeded() -> None:
    rb = ChatRingBuffer(max_frames=3, max_bytes=1_000_000)
    for i in range(1, 6):
        rb.append(i, b"x")
    # Only the last 3 retained (frame_count cap).
    assert rb.size == 3
    assert rb.lowest_seq() == 3
    assert rb.highest_seq() == 5


def test_evicts_when_byte_size_exceeded() -> None:
    rb = ChatRingBuffer(max_frames=10_000, max_bytes=10)
    rb.append(1, b"aaaaa")  # 5 bytes
    rb.append(2, b"bbbbb")  # 5 bytes (10 total, at limit)
    rb.append(3, b"cccccc")  # 6 bytes — eviction cascade
    # After append: total before eviction = 16; evict oldest until <=10.
    # Drop seq=1 (5 bytes) → 11; drop seq=2 (5 bytes) → 6 ≤ 10. Only
    # seq=3 remains.
    assert rb.size == 1
    assert rb.lowest_seq() == 3


def test_replay_returns_empty_when_caller_already_caught_up() -> None:
    rb = ChatRingBuffer()
    rb.append(1, b"a")
    rb.append(2, b"b")
    assert rb.replay(after_seq=2) == []
    assert rb.replay(after_seq=99) == []


def test_empty_ring_helpers() -> None:
    rb = ChatRingBuffer()
    assert rb.size == 0
    assert rb.bytes == 0
    assert rb.lowest_seq() is None
    assert rb.highest_seq() is None
