"""Null Object for autocomplete while Tinymist is not installed: nothing to offer."""

from pathlib import Path

from typst_writer.domain.models import CompletionItem
from typst_writer.ports.rule_checker import CheckerStatus


class NoneCompleter:
    def __init__(self, status: CheckerStatus) -> None:
        self._status = status

    def status(self) -> CheckerStatus:
        return self._status

    async def complete(
        self, root: Path, main: str | None, path: str, content: str, offset: int
    ) -> list[CompletionItem]:
        return []

    async def close(self) -> None:
        return None
