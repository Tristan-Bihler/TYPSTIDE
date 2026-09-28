"""Small JSON file for local app state (last workspace, main file per workspace)."""

from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

MAX_OPEN_TABS = 50


class OpenTab(BaseModel):
    path: str
    cursor: int = Field(default=0, ge=0)  # UTF-16 offset


class OpenTabs(BaseModel):
    """The editor tabs of a workspace, restored when it is opened again."""

    tabs: list[OpenTab] = Field(default_factory=list, max_length=MAX_OPEN_TABS)
    active: str | None = None


class WorkspaceState(BaseModel):
    main: str | None = None
    open_tabs: OpenTabs = OpenTabs()


class AppState(BaseModel):
    last_workspace: str | None = None
    workspaces: dict[str, WorkspaceState] = {}


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppState:
        try:
            return AppState.model_validate_json(self.path.read_bytes())
        except (FileNotFoundError, ValidationError):
            return AppState()  # missing or corrupt: start fresh rather than refuse to start

    def save(self, state: AppState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.path)
