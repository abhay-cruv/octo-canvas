import pytest
from sandbox_provider import MockSandboxProvider, SandboxHandle, SpritesError


@pytest.mark.asyncio
async def test_create_returns_warm_handle_with_url() -> None:
    p = MockSandboxProvider()
    handle = await p.create(sandbox_id="sbx1", labels=["user:42"])
    assert handle.provider == "mock"
    assert handle.payload["name"] == "octo-sbx-sbx1"

    state = await p.status(handle)
    assert state.status == "warm"
    assert state.public_url is not None and state.public_url.startswith("https://")


@pytest.mark.asyncio
async def test_create_twice_with_same_id_raises() -> None:
    p = MockSandboxProvider()
    await p.create(sandbox_id="sbx", labels=[])
    with pytest.raises(SpritesError):
        await p.create(sandbox_id="sbx", labels=[])


@pytest.mark.asyncio
async def test_destroy_makes_status_raise() -> None:
    p = MockSandboxProvider()
    handle = await p.create(sandbox_id="sbx", labels=[])
    await p.destroy(handle)
    with pytest.raises(SpritesError):
        await p.status(handle)


@pytest.mark.asyncio
async def test_destroy_idempotent() -> None:
    p = MockSandboxProvider()
    handle = await p.create(sandbox_id="sbx", labels=[])
    await p.destroy(handle)
    await p.destroy(handle)
    # Destroying a handle that was never created is also a no-op.
    other = SandboxHandle(provider="mock", payload={"name": "octo-sbx-never"})
    await p.destroy(other)


@pytest.mark.asyncio
async def test_wake_forces_running_from_cold() -> None:
    p = MockSandboxProvider()
    handle = await p.create(sandbox_id="sbx", labels=[])
    p._force_cold(handle)  # pyright: ignore[reportPrivateUsage]
    state = await p.wake(handle)
    assert state.status == "running"


@pytest.mark.asyncio
async def test_pause_transitions_to_cold() -> None:
    p = MockSandboxProvider()
    handle = await p.create(sandbox_id="sbx", labels=[])
    # Sprite is `warm` after create; bump to running first to confirm pause
    # works from any alive state.
    await p.wake(handle)
    state = await p.pause(handle)
    assert state.status == "cold"


@pytest.mark.asyncio
async def test_pause_idempotent_on_cold() -> None:
    p = MockSandboxProvider()
    handle = await p.create(sandbox_id="sbx", labels=[])
    await p.pause(handle)
    state = await p.pause(handle)
    assert state.status == "cold"


@pytest.mark.asyncio
async def test_status_for_wrong_provider_raises() -> None:
    p = MockSandboxProvider()
    bad = SandboxHandle(provider="sprites", payload={"name": "x"})
    with pytest.raises(SpritesError):
        await p.status(bad)


@pytest.mark.asyncio
async def test_create_after_destroy_with_same_id_succeeds() -> None:
    """Reset (destroy → create with same sandbox_id) must work."""
    p = MockSandboxProvider()
    h1 = await p.create(sandbox_id="sbx", labels=[])
    await p.destroy(h1)
    h2 = await p.create(sandbox_id="sbx", labels=[])
    state = await p.status(h2)
    assert state.status == "warm"
