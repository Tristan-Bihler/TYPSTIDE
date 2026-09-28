"""AI selector settings and the selection review over HTTP (fake claude, no real calls)."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from helpers import app_client

pytestmark = pytest.mark.skipif(os.name == "nt", reason="fake claude uses a shebang script")

SELECTION = "Ein Fehlr, sehr sehr deutlich."


def review(client: TestClient, **extra: object) -> dict[str, Any]:
    body = {"selection": SELECTION, "selection_start": 10, "mode": "check", **extra}
    response = client.post("/api/review", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_defaults_are_none_and_claude_is_offered(client: TestClient) -> None:
    status = client.get("/api/ai/status").json()
    assert status["settings"] == {"local_model": None, "claude_model": None}
    assert status["claude"] == {
        "available": True,
        "reason": "",
        "models": ["sonnet", "opus", "haiku"],
    }
    assert status["local"]["available"] is False
    assert "Ollama is not running" in status["local"]["reason"]


def test_claude_unavailable_when_logged_out(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "logged_out")
    claude = client.get("/api/ai/status", params={"refresh": True}).json()["claude"]
    assert (claude["available"], claude["models"]) == (False, [])
    assert "claude auth login" in claude["reason"]
    response = client.put("/api/ai/settings", json={"claude_model": "sonnet"})
    assert (response.status_code, response.json()["code"]) == (409, "ai_unavailable")


def test_settings_are_validated_persisted_and_restored(client: TestClient) -> None:
    assert client.put("/api/ai/settings", json={"claude_model": "gpt-4"}).status_code == 409
    assert client.put("/api/ai/settings", json={"local_model": "llama3"}).status_code == 409
    saved = client.put("/api/ai/settings", json={"claude_model": "opus"}).json()
    assert saved["settings"]["claude_model"] == "opus"
    with app_client() as fresh:
        assert fresh.get("/api/ai/status").json()["settings"]["claude_model"] == "opus"


def test_review_with_claude_none_changes_nothing(client: TestClient, fake_claude: Path) -> None:
    """Acceptance: with both slots None the review is a no-op and claude is never run."""
    result = review(client)
    assert result["changes"] == [] and result["revised_text"] == SELECTION
    assert not fake_claude.exists()


def test_review_returns_a_diff_with_document_offsets(client: TestClient) -> None:
    client.put("/api/ai/settings", json={"claude_model": "sonnet"})
    result = review(client)
    assert result["revised_text"] == "Ein Fehler, sehr deutlich."
    assert [(c["original"], c["replacement"], c["start"], c["end"]) for c in result["changes"]] == [
        ("Fehlr", "Fehler", 14, 19),
        ("sehr sehr", "sehr", 21, 30),
    ]
    assert result["dropped"] == 0


def test_changes_that_break_markup_are_dropped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put("/api/ai/settings", json={"claude_model": "sonnet"})
    output = {
        "explanation": "",
        "changes": [
            {"original": "@tab:a", "replacement": "Tabelle 1", "reason": "r", "category": "style"},
            {"original": "zeigt", "replacement": "belegt", "reason": "r", "category": "style"},
        ],
    }
    monkeypatch.setenv("FAKE_CLAUDE_OUTPUT", json.dumps(output))
    body = {"selection": "Siehe @tab:a, sie zeigt es.", "mode": "improve"}
    result = client.post("/api/review", json=body).json()
    assert result["revised_text"] == "Siehe @tab:a, sie belegt es."
    assert result["dropped"] == 1


def test_explain_mode_returns_text_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put("/api/ai/settings", json={"claude_model": "sonnet"})
    output = {
        "explanation": "Der Satz ist zu lang.",
        "changes": [
            {"original": "Fehlr", "replacement": "Fehler", "reason": "r", "category": "spelling"}
        ],
    }
    monkeypatch.setenv("FAKE_CLAUDE_OUTPUT", json.dumps(output))
    result = review(client, mode="explain")
    assert result["explanation"] == "Der Satz ist zu lang."
    assert result["changes"] == [] and result["revised_text"] == SELECTION


def test_long_context_is_trimmed_and_long_selection_refused(
    client: TestClient, fake_claude: Path
) -> None:
    client.put("/api/ai/settings", json={"claude_model": "sonnet"})
    review(client, context_before="x" * 30_000, context_after="y" * 30_000)
    stdin = json.loads(fake_claude.read_text(encoding="utf-8").splitlines()[-1])["stdin"]
    assert len(stdin) <= 20_000 + 200
    too_long = client.post("/api/review", json={"selection": "z" * 20_001, "mode": "check"})
    assert (too_long.status_code, too_long.json()["code"]) == (413, "too_long")


def test_claude_errors_are_reported(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client.put("/api/ai/settings", json={"claude_model": "sonnet"})
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "is_error")
    response = client.post("/api/review", json={"selection": SELECTION, "mode": "check"})
    assert (response.status_code, response.json()["code"]) == (502, "ai_failed")
    assert "Usage limit reached" in response.json()["detail"]


def test_review_request_is_validated(client: TestClient) -> None:
    assert client.post("/api/review", json={"selection": "", "mode": "check"}).status_code == 422
    assert client.post("/api/review", json={"selection": "x", "mode": "rewrite"}).status_code == 422
