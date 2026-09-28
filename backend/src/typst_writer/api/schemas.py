"""Request/response and WebSocket message models. Mirrored in frontend/src/api/types.ts."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from typst_writer.domain.models import Problem
from typst_writer.services.workspace import WorkspaceInfo


class HealthResponse(BaseModel):
    status: Literal["ok"]
    typst_version: str


class ErrorResponse(BaseModel):
    detail: str
    code: str
    problems: list[Problem] = []


# --- REST requests -------------------------------------------------------------------


class OpenWorkspaceRequest(BaseModel):
    path: str


class CreateEntryRequest(BaseModel):
    parent: str = ""
    name: str
    overwrite: bool = False


class RenameRequest(BaseModel):
    path: str
    new_name: str
    overwrite: bool = False


class SaveFileRequest(BaseModel):
    path: str
    content: str


class SetMainRequest(BaseModel):
    path: str | None


class ExportRequest(BaseModel):
    overlays: dict[str, str] = {}


class FileContent(BaseModel):
    path: str
    content: str


class EntryPath(BaseModel):
    path: str


# --- WebSocket: client -> server ---------------------------------------------------------


class DocChanged(BaseModel):
    type: Literal["doc_changed"]
    path: str
    content: str


class DocClosed(BaseModel):
    type: Literal["doc_closed"]
    path: str


class Refresh(BaseModel):
    type: Literal["refresh"]


ClientMessage = Annotated[DocChanged | DocClosed | Refresh, Field(discriminator="type")]


# --- WebSocket: server -> client ---------------------------------------------------------

CompileState = Literal["compiling", "ok", "error", "no_main", "no_workspace"]


class CompileStatus(BaseModel):
    type: Literal["compile_status"] = "compile_status"
    state: CompileState
    main: str | None
    duration_ms: float | None = None


class PageUpdate(BaseModel):
    index: int
    hash: str
    svg: str | None  # None: unchanged since the last message on this connection


class PreviewPages(BaseModel):
    type: Literal["preview_pages"] = "preview_pages"
    pages: list[PageUpdate]


class ProblemsMessage(BaseModel):
    type: Literal["problems"] = "problems"
    problems: list[Problem]


class WorkspaceChanged(BaseModel):
    type: Literal["workspace_changed"] = "workspace_changed"
    workspace: WorkspaceInfo | None
    reopened: bool  # True when a different folder was opened: drop all open buffers
