"""Small JSON file for local app state (last workspace, main file per workspace)."""

from pathlib import Path

from pydantic import BaseModel, ValidationError


class WorkspaceState(BaseModel):
    main: str | None = None


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
