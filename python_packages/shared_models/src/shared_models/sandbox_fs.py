"""Pydantic shapes for `/api/sandboxes/{id}/fs*` (slice 6).

Both list and read share the same endpoint with `?list=true|false`. We
return a discriminated response so the FE can branch cleanly.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _FsModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FsEntryDto(_FsModel):
    name: str
    type: Literal["file", "dir"]
    size: int


class FsListResponse(_FsModel):
    type: Literal["list"] = "list"
    path: str
    entries: list[FsEntryDto]


class FsFileResponse(_FsModel):
    type: Literal["file"] = "file"
    path: str
    # UTF-8 text. Binary files are detected server-side and rejected with
    # 415 — slice 6 doesn't ship a hex viewer; the FE only opens text.
    content: str
    # Hex-encoded sha256 of the raw bytes. Round-trips as the If-Match
    # value on save. Lowercase, no quotes.
    sha: str
    size: int


FsReadResponse = Annotated[
    FsListResponse | FsFileResponse,
    Field(discriminator="type"),
]


class FsWriteRequest(_FsModel):
    content: str


class FsWriteResponse(_FsModel):
    path: str
    sha: str
    size: int


class FsRenameRequest(_FsModel):
    new_path: str


class FsRenameResponse(_FsModel):
    path: str
    new_path: str
