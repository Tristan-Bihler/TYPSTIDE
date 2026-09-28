from pathlib import Path
from typing import Protocol

from typst_writer.domain.models import CompletionItem
from typst_writer.ports.rule_checker import CheckerStatus


class Completer(Protocol):
    """Completion for Typst code, labels and citations (Tinymist, or nothing)."""

    def status(self) -> CheckerStatus: ...

    async def complete(
        self, root: Path, main: str | None, path: str, content: str, offset: int
    ) -> list[CompletionItem]:
        """Completions at UTF-16 `offset` in `content`, the current text of workspace file
        `path`. `main` is the main file (for labels from every chapter). Raises
        CheckerUnavailableError."""
        ...

    async def close(self) -> None: ...
