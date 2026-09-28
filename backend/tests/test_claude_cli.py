"""ClaudeCliProvider against a fake `claude` (see tests/fakes/claude.py): no real calls."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from typst_writer.adapters.claude_cli import ClaudeCliProvider, system_prompt
from typst_writer.domain.errors import AIFailedError, AIUnavailableError
from typst_writer.domain.models import ReviewRequest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="fake claude uses a shebang script")

REQUEST = ReviewRequest(
    selection="Ein Fehlr, sehr sehr deutlich.",
    context_before="Vorher.",
    context_after="Nachher.",
    mode="check",
    language="de-DE",
)


def calls(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def provider(timeout_s: float = 30) -> ClaudeCliProvider:
    return ClaudeCliProvider(["sonnet", "haiku"], timeout_s)


@pytest.mark.anyio
async def test_status_when_logged_in() -> None:
    status = await provider().status()
    assert (status.available, status.models) == (True, ["sonnet", "haiku"])


@pytest.mark.anyio
async def test_status_when_logged_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "logged_out")
    status = await provider().status()
    assert not status.available
    assert "claude auth login" in status.reason
    assert status.models == []


@pytest.mark.anyio
async def test_status_when_not_installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    status = await provider().status()
    assert not status.available
    assert "was not found" in status.reason


@pytest.mark.anyio
async def test_review_runs_claude_safely(
    fake_claude: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-be-passed")
    draft = await provider().review_selection(REQUEST, "sonnet")
    assert [c.replacement for c in draft.changes] == ["Fehler", "sehr"]

    [call] = calls(fake_claude)
    argv = call["argv"]
    assert argv[0] == "-p"
    assert argv[argv.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert json.loads(argv[argv.index("--json-schema") + 1])["required"] == [
        "explanation",
        "changes",
    ]
    assert argv[argv.index("--output-format") + 1] == "json"
    # The text goes on stdin only; the working directory is an empty temp dir.
    assert "Fehlr" in call["stdin"] and "Vorher." in call["stdin"]
    assert not any("Fehlr" in a for a in argv)
    assert "typst-writer-claude-" in call["cwd"] and not Path(call["cwd"]).exists()
    assert "ANTHROPIC_API_KEY" not in call["env_keys"]


@pytest.mark.anyio
async def test_unknown_model_is_refused(fake_claude: Path) -> None:
    with pytest.raises(AIUnavailableError, match="not one of the Claude models"):
        await provider().review_selection(REQUEST, "gpt-4")
    assert not fake_claude.exists()  # claude was never started


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("is_error", "Usage limit reached"),
        ("garbage", "exit code 0"),
        ("exit", "something broke"),
        ("bad_schema", "unexpected format"),
    ],
)
async def test_failures_become_readable_errors(
    monkeypatch: pytest.MonkeyPatch, mode: str, message: str
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(AIFailedError, match=message):
        await provider().review_selection(REQUEST, "sonnet")


@pytest.mark.anyio
async def test_timeout_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    with pytest.raises(AIFailedError, match="within 1 seconds"):
        await provider(timeout_s=1).review_selection(REQUEST, "sonnet")


def test_system_prompt_mentions_language_mode_and_markup_rule() -> None:
    prompt = system_prompt("shorten", "en-US", ["Typst", "LTeX+"])
    assert "English" in prompt and "concise" in prompt
    assert "Never change Typst markup" in prompt
    assert "Typst, LTeX+" in prompt
