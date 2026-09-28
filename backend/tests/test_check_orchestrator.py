import asyncio
from typing import cast

import pytest

from typst_writer.domain.models import Suggestion
from typst_writer.services.check_orchestrator import CheckOrchestrator
from typst_writer.services.grammar import GrammarService

pytestmark = pytest.mark.anyio


class SlowGrammar:
    """Stands in for GrammarService: each check takes a moment and echoes the text."""

    def __init__(self) -> None:
        self.checked: list[str] = []
        self.forgotten: list[str] = []

    async def check(self, path: str, source: str) -> list[Suggestion]:
        self.checked.append(source)
        await asyncio.sleep(0.05)
        return [
            Suggestion(
                id=source,
                source="rule",
                start=0,
                end=1,
                original="",
                replacement="",
                reason=source,
                category="grammar",
            )
        ]

    async def forget(self, path: str) -> None:
        self.forgotten.append(path)


def _orchestrator(
    grammar: SlowGrammar, sent: list[tuple[str, int | None, str]], max_chars: int = 1000
) -> CheckOrchestrator:
    async def send(path: str, version: int | None, found: list[Suggestion]) -> None:
        sent.append((path, version, found[0].reason if found else ""))

    return CheckOrchestrator(cast(GrammarService, grammar), send, max_chars)


async def test_a_burst_of_changes_collapses_into_one_more_check() -> None:
    grammar = SlowGrammar()
    sent: list[tuple[str, int | None, str]] = []
    checks = _orchestrator(grammar, sent)
    for version in range(1, 6):
        checks.update("a.typ", f"text {version}", version)
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.3)
    assert grammar.checked == ["text 1", "text 5"]
    # The result for text 1 was already outdated when it arrived: only the newest is sent.
    assert sent == [("a.typ", 5, "text 5")]
    await checks.stop()


async def test_files_are_checked_independently_and_closing_forgets() -> None:
    grammar = SlowGrammar()
    sent: list[tuple[str, int | None, str]] = []
    checks = _orchestrator(grammar, sent)
    checks.update("a.typ", "A", 1)
    checks.update("b.typ", "B", 1)
    checks.update("notes.txt", "C", 1)  # not Typst: never checked
    await asyncio.sleep(0.2)
    assert sorted(sent) == [("a.typ", 1, "A"), ("b.typ", 1, "B")]
    checks.close("a.typ")
    await asyncio.sleep(0.05)
    assert grammar.forgotten == ["a.typ"]
    await checks.stop()


async def test_too_long_files_get_no_findings() -> None:
    grammar = SlowGrammar()
    sent: list[tuple[str, int | None, str]] = []
    checks = _orchestrator(grammar, sent, max_chars=5)
    checks.update("a.typ", "far too long", 3)
    await asyncio.sleep(0.05)
    assert grammar.checked == []
    assert sent == [("a.typ", 3, "")]
    await checks.stop()


async def test_nothing_runs_after_stop() -> None:
    grammar = SlowGrammar()
    sent: list[tuple[str, int | None, str]] = []
    checks = _orchestrator(grammar, sent)
    checks.update("a.typ", "one", 1)
    await asyncio.sleep(0.01)
    checks.update("a.typ", "two", 2)
    await checks.stop()
    await asyncio.sleep(0.2)
    assert grammar.checked == ["one"]
    assert sent == []
