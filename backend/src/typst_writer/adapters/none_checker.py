"""Null Object for the rule checker while LTeX+ is not installed: checks find nothing."""

from typst_writer.domain.models import Language, Suggestion
from typst_writer.ports.rule_checker import CheckerStatus


class NoneRuleChecker:
    def __init__(self, status: CheckerStatus) -> None:
        self._status = status

    def status(self) -> CheckerStatus:
        return self._status

    async def check(
        self, path: str, source: str, language: Language, dictionary: list[str]
    ) -> list[Suggestion]:
        return []

    async def forget(self, path: str) -> None:
        return None

    async def close(self) -> None:
        return None
