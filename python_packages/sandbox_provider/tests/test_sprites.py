"""SpritesProvider tests via a fake SDK client — no real network hits.

We don't use the actual `sprites-py` SDK here; we monkey-patch the
provider's internal client with a fake that records calls. This keeps the
test surface focused on provider behaviour (mapping, error wrapping, idempotent
destroy) without taking on the SDK's HTTP machinery.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from sandbox_provider import SandboxHandle, SpritesError, SpritesProvider
from sprites import NotFoundError, SpriteError


@dataclass
class _FakeSprite:
    name: str
    id: str | None = None
    status: str | None = None
    url: str | None = None


@dataclass
class _FakeClient:
    sprites: dict[str, _FakeSprite] = field(default_factory=dict)
    raise_on_create: BaseException | None = None
    raise_on_get: BaseException | None = None
    raise_on_delete: BaseException | None = None
    last_command: list[Any] = field(default_factory=list)

    def create_sprite(self, name: str, config: Any = None) -> _FakeSprite:
        if self.raise_on_create is not None:
            raise self.raise_on_create
        if name in self.sprites:
            raise SpriteError(f"sprite {name!r} already exists")
        self.sprites[name] = _FakeSprite(
            name=name,
            id=f"sprite-{name}",
            status="warm",
            url=f"https://{name}.sprites.app",
        )
        return _FakeSprite(name=name)  # SDK returns partial; matches reality

    def get_sprite(self, name: str) -> _FakeSprite:
        if self.raise_on_get is not None:
            raise self.raise_on_get
        sprite = self.sprites.get(name)
        if sprite is None:
            raise NotFoundError(f"sprite {name!r} not found")
        return sprite

    def delete_sprite(self, name: str) -> None:
        if self.raise_on_delete is not None:
            raise self.raise_on_delete
        if name not in self.sprites:
            raise NotFoundError(f"sprite {name!r} not found")
        del self.sprites[name]

    def sprite(self, name: str) -> "_FakeSpriteWrapper":
        return _FakeSpriteWrapper(name=name, client=self)

    def close(self) -> None:
        pass


@dataclass
class _FakeSpriteWrapper:
    name: str
    client: _FakeClient

    def command(self, *args: str) -> "_FakeCommand":
        self.client.last_command.append(args)
        return _FakeCommand()


@dataclass
class _FakeCommand:
    def run(self) -> None:
        return None


def _build_provider(fake: _FakeClient) -> SpritesProvider:
    p = SpritesProvider(token="test-token")
    p._client = fake  # pyright: ignore[reportAttributeAccessIssue]
    return p


@pytest.mark.asyncio
async def test_create_returns_handle_with_id_and_url() -> None:
    fake = _FakeClient()
    p = _build_provider(fake)
    handle = await p.create(sandbox_id="sbx1", labels=["env:test"])
    assert handle.provider == "sprites"
    assert handle.payload["name"] == "vibe-sbx-sbx1"
    assert handle.payload["id"] == "sprite-vibe-sbx-sbx1"

    state = await p.status(handle)
    assert state.status == "warm"
    assert state.public_url == "https://vibe-sbx-sbx1.sprites.app"


@pytest.mark.asyncio
async def test_create_propagates_sprite_error_as_non_retriable() -> None:
    fake = _FakeClient(raise_on_create=SpriteError("403 forbidden"))
    p = _build_provider(fake)
    with pytest.raises(SpritesError) as exc_info:
        await p.create(sandbox_id="sbx", labels=[])
    assert exc_info.value.retriable is False


@pytest.mark.asyncio
async def test_create_5xx_is_retriable() -> None:
    fake = _FakeClient(raise_on_create=SpriteError("503 unavailable"))
    p = _build_provider(fake)
    with pytest.raises(SpritesError) as exc_info:
        await p.create(sandbox_id="sbx", labels=[])
    assert exc_info.value.retriable is True


@pytest.mark.asyncio
async def test_destroy_404_is_idempotent() -> None:
    fake = _FakeClient(raise_on_delete=NotFoundError("not found"))
    p = _build_provider(fake)
    handle = SandboxHandle(provider="sprites", payload={"name": "vibe-sbx-x"})
    # Should not raise.
    await p.destroy(handle)


@pytest.mark.asyncio
async def test_status_404_raises_non_retriable() -> None:
    fake = _FakeClient(raise_on_get=NotFoundError("missing"))
    p = _build_provider(fake)
    handle = SandboxHandle(provider="sprites", payload={"name": "vibe-sbx-x"})
    with pytest.raises(SpritesError) as exc_info:
        await p.status(handle)
    assert exc_info.value.retriable is False


@pytest.mark.asyncio
async def test_status_maps_sprite_states() -> None:
    fake = _FakeClient()
    fake.sprites["vibe-sbx-x"] = _FakeSprite(
        name="vibe-sbx-x", id="id", status="cold", url="u"
    )
    p = _build_provider(fake)
    handle = SandboxHandle(provider="sprites", payload={"name": "vibe-sbx-x"})
    assert (await p.status(handle)).status == "cold"
    fake.sprites["vibe-sbx-x"].status = "running"
    assert (await p.status(handle)).status == "running"
    # Unknown status maps to warm with a warning.
    fake.sprites["vibe-sbx-x"].status = "starting"
    assert (await p.status(handle)).status == "warm"


@pytest.mark.asyncio
async def test_wake_issues_no_op_command_and_returns_state() -> None:
    fake = _FakeClient()
    fake.sprites["vibe-sbx-x"] = _FakeSprite(
        name="vibe-sbx-x", id="id", status="cold", url="u"
    )
    p = _build_provider(fake)
    handle = SandboxHandle(provider="sprites", payload={"name": "vibe-sbx-x"})
    state = await p.wake(handle)
    # Wake calls command("true") on the sprite.
    assert fake.last_command == [("true",)]
    # Then re-fetches status — still cold in the fake (no auto-warm).
    assert state.status == "cold"


@pytest.mark.asyncio
async def test_handle_for_wrong_provider_raises() -> None:
    p = _build_provider(_FakeClient())
    bad = SandboxHandle(provider="mock", payload={"name": "x"})
    with pytest.raises(SpritesError):
        await p.status(bad)


@pytest.mark.asyncio
async def test_constructor_rejects_empty_token() -> None:
    with pytest.raises(ValueError):
        SpritesProvider(token="")
