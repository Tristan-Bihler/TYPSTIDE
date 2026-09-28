import sys
from pathlib import Path

import pytest

from typst_writer.adapters.ltex import LtexChecker, is_spelling_rule
from typst_writer.domain.errors import CheckerUnavailableError
from typst_writer.ports.rule_checker import CheckerStatus

pytestmark = pytest.mark.anyio

FAKE_LTEX = Path(__file__).parent / "fakes" / "ltex.py"


@pytest.fixture
def fake_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "fake-ltex.log"
    monkeypatch.setenv("FAKE_LTEX_LOG", str(log))
    return log


def make_checker(
    tmp_path: Path,
    statuses: list[CheckerStatus] | None = None,
    check_timeout: float = 10,
) -> LtexChecker:
    return LtexChecker(
        [sys.executable, str(FAKE_LTEX)],
        tmp_path,
        max_message_bytes=1_000_000,
        startup_timeout_s=check_timeout,
        check_timeout_s=check_timeout,
        on_status=statuses.append if statuses is not None else None,
    )


async def test_findings_with_fixes_and_utf16_offsets(tmp_path: Path, fake_log: Path) -> None:
    statuses: list[CheckerStatus] = []
    checker = make_checker(tmp_path, statuses)
    source = "😀 Ein Fehlr, das das ist durchgefürt."
    try:
        found = await checker.check("kapitel/a.typ", source, "de-DE", [])
    finally:
        await checker.close()
    by_rule = {s.original: s for s in found}
    assert set(by_rule) == {"Fehlr", "das das", "durchgefürt"}
    fehlr = by_rule["Fehlr"]
    assert fehlr.source == "rule"
    assert fehlr.category == "spelling"
    assert fehlr.rule == "GERMAN_SPELLER_RULE"
    assert fehlr.fixes == ["Fehler"]
    assert fehlr.replacement == "Fehler"
    # UTF-16 offsets: the emoji counts twice, like in the browser.
    assert (fehlr.start, fehlr.end) == (7, 12)
    assert by_rule["durchgefürt"].fixes == ["durchgeführt", "durchgefüht"]
    assert by_rule["das das"].category == "grammar"
    assert [s.state for s in statuses] == ["starting", "ready"]
    assert checker.status().state == "ready"


async def test_second_check_sends_a_change_and_close_forgets(
    tmp_path: Path, fake_log: Path
) -> None:
    checker = make_checker(tmp_path)
    try:
        assert len(await checker.check("a.typ", "Ein Fehlr.", "de-DE", [])) == 1
        assert await checker.check("a.typ", "Ein Fehler.", "de-DE", []) == []
        await checker.forget("a.typ")
    finally:
        await checker.close()
    methods = fake_log.read_text().split()
    assert methods.count("textDocument/didOpen") == 1
    assert methods.count("textDocument/didChange") == 1
    assert "textDocument/didClose" in methods


async def test_language_and_dictionary_reach_ltex(tmp_path: Path, fake_log: Path) -> None:
    checker = make_checker(tmp_path)
    try:
        english = await checker.check("a.typ", "I recieve teh Fehlr.", "en-US", [])
        accepted = await checker.check("a.typ", "I recieve teh Fehlr.", "en-US", ["teh"])
    finally:
        await checker.close()
    assert [s.original for s in english] == ["recieve", "teh"]
    assert english[0].rule == "MORFOLOGIK_RULE_EN_US"
    assert [s.original for s in accepted] == ["recieve"]


async def test_findings_inside_markup_are_dropped(tmp_path: Path, fake_log: Path) -> None:
    checker = make_checker(tmp_path)
    source = "Siehe @fig:Fehlr und <tab:Fehlr> und $Fehlr$ und `Fehlr`, aber Fehlr."
    try:
        found = await checker.check("a.typ", source, "de-DE", [])
    finally:
        await checker.close()
    assert [source[s.start : s.end] for s in found] == ["Fehlr"]
    assert found[0].start == source.rindex("Fehlr")


async def test_crashing_server_is_restarted_then_given_up(
    tmp_path: Path, fake_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_LTEX_MODE", "crash_on_check")
    checker = make_checker(tmp_path)
    try:
        for _ in range(5):
            with pytest.raises(CheckerUnavailableError):
                await checker.check("a.typ", "Text.", "de-DE", [])
    finally:
        await checker.close()
    assert checker.status().state == "failed"
    assert fake_log.read_text().split().count("initialize") == 4  # first start + 3 restarts


async def test_timeout_restarts_the_server(
    tmp_path: Path, fake_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_LTEX_MODE", "slow_check")
    checker = make_checker(tmp_path, check_timeout=0.5)
    try:
        with pytest.raises(CheckerUnavailableError, match="did not answer in time"):
            await checker.check("a.typ", "Text.", "de-DE", [])
        monkeypatch.setenv("FAKE_LTEX_MODE", "ok")
        assert len(await checker.check("a.typ", "Ein Fehlr.", "de-DE", [])) == 1
    finally:
        await checker.close()
    assert fake_log.read_text().split().count("initialize") == 2


async def test_missing_java_fails_with_a_reason(tmp_path: Path) -> None:
    checker = LtexChecker(
        [str(tmp_path / "jdk" / "bin" / "java")],
        tmp_path,
        max_message_bytes=1000,
        startup_timeout_s=5,
        check_timeout_s=5,
    )
    await checker.start()
    assert checker.status().state == "failed"
    assert "could not be started" in checker.status().reason


def test_spelling_rule_families() -> None:
    assert is_spelling_rule("GERMAN_SPELLER_RULE")
    assert is_spelling_rule("MORFOLOGIK_RULE_EN_US")
    assert not is_spelling_rule("DE_CASE")
    assert not is_spelling_rule("GERMAN_WORD_REPEAT_RULE")
