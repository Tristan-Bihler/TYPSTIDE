"""Request/response and WebSocket message models. Mirrored in frontend/src/api/types.ts."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from typst_writer.domain.models import (
    DictionaryWord,
    Language,
    Problem,
    Suggestion,
    SuggestionSource,
)
from typst_writer.ports.rule_checker import CheckerStatus
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


class OverlaysRequest(BaseModel):
    """Unsaved editor buffers by workspace-relative path."""

    overlays: dict[str, str] = {}


class RenderRequest(OverlaysRequest):
    params: dict[str, Any] = {}


class RenderResponse(BaseModel):
    code: str


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
    version: int | None = None  # the client's edit counter, echoed in `suggestions`


class DocOpened(BaseModel):
    """A file was opened in the editor: check it (the preview is not affected)."""

    type: Literal["doc_opened"]
    path: str
    content: str
    version: int | None = None


class TypingPaused(BaseModel):
    """No typing for a moment: the local AI may check the edited paragraphs."""

    type: Literal["typing_paused"]
    path: str
    version: int | None = None
    cursor: int = Field(default=0, ge=0)  # UTF-16 offset of the cursor


class PreviewClick(BaseModel):
    """A click in the preview: show that place in the source."""

    type: Literal["preview_click"]
    page: int = Field(ge=1)
    y: float = Field(ge=0)  # pt from the top of the page


class CursorMoved(BaseModel):
    """The cursor moved to another paragraph: where is it in the preview?"""

    type: Literal["cursor_moved"]
    path: str
    offset: int = Field(ge=0)  # UTF-16


class DocClosed(BaseModel):
    type: Literal["doc_closed"]
    path: str


class Refresh(BaseModel):
    type: Literal["refresh"]


ClientMessage = Annotated[
    DocChanged | DocOpened | TypingPaused | PreviewClick | CursorMoved | DocClosed | Refresh,
    Field(discriminator="type"),
]


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


class SuggestionsMessage(BaseModel):
    """Findings for one file, replacing earlier ones from the same source."""

    type: Literal["suggestions"] = "suggestions"
    path: str
    version: int | None
    source: SuggestionSource
    suggestions: list[Suggestion]


class Jump(BaseModel):
    """Answer to preview_click: the source position (UTF-16 offset) to show."""

    type: Literal["jump"] = "jump"
    path: str
    offset: int


class PreviewPosition(BaseModel):
    """Answer to cursor_moved: where the cursor's paragraph is in the preview."""

    type: Literal["preview_position"] = "preview_position"
    path: str
    offset: int
    page: int
    y: float


class WordCount(BaseModel):
    """Prose words of the main document (main file + included chapters) and per file."""

    type: Literal["word_count"] = "word_count"
    total: int
    files: dict[str, int]


class LocalCheckStatus(BaseModel):
    """How many paragraphs the local AI still has to check (0 = idle)."""

    type: Literal["local_check_status"] = "local_check_status"
    pending: int


class CheckerStatusMessage(BaseModel):
    type: Literal["checker_status"] = "checker_status"
    status: CheckerStatus


# --- REST: spelling and grammar ------------------------------------------------------


class GrammarLanguageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language


class DictionaryWordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language
    word: DictionaryWord
