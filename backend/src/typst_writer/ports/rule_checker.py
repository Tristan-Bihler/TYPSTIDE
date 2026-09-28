from typing import Literal, Protocol

from pydantic import BaseModel

from typst_writer.domain.models import Language, Suggestion

CheckerState = Literal["not_installed", "installing", "starting", "ready", "failed"]


class CheckerStatus(BaseModel):
    state: CheckerState
    reason: str = ""  # shown in the status bar tooltip
    progress: float | None = None  # 0..1 while installing, if known


class RuleChecker(Protocol):
    """Rule-based spelling and grammar check (offline)."""

    def status(self) -> CheckerStatus: ...

    async def check(
        self, path: str, source: str, language: Language, dictionary: list[str]
    ) -> list[Suggestion]:
        """Findings for the whole file (`source` of workspace path `path`), with UTF-16
        offsets. Raises CheckerUnavailableError."""
        ...

    async def close(self) -> None: ...
