"""Phase 5 acceptance over REST + WebSocket with the fake Ollama (no real model):
suggestions after a pause, unchanged paragraphs never re-sent, offline → graceful None."""

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from typst_writer.config import CONFIG_ENV_VAR
from typst_writer.infra.ltex_install import LTEX_DIR_ENV_VAR

from fakes.ollama import MODEL, FakeOllama
from helpers import (
    FRONTEND_ORIGIN,
    WS_URL,
    app_client,
    make_fake_ltex_install,
    write_config,
)

CHAPTER = "chapters/intro.typ"
UNTOUCHED = "Dieser Absatz bleibt unverändert, weil er hat keine Zeit für Änderungen."
EDITABLE = "Der zweite Absatz ist ausreichend lang und wird gleich bearbeitet."
ORIGINAL = f"= Einleitung\n\n{UNTOUCHED}\n\n{EDITABLE}\n"


@pytest.fixture
def ollama(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeOllama]:
    fake = FakeOllama().start()
    monkeypatch.setenv(CONFIG_ENV_VAR, str(write_config(tmp_path / "cfg", fake.url)))
    yield fake
    fake.stop()


@pytest.fixture
def app(workspace: Path, ollama: FakeOllama) -> Iterator[TestClient]:
    (workspace / CHAPTER).write_text(ORIGINAL, encoding="utf-8")
    with app_client() as client:
        client.post("/api/workspace/open", json={"path": str(workspace)})
        assert client.put("/api/ai/settings", json={"local_model": MODEL}).status_code == 200
        yield client


def _connect(client: TestClient) -> AbstractContextManager[WebSocketTestSession]:
    return client.websocket_connect(WS_URL, headers={"origin": FRONTEND_ORIGIN})


def _send(ws: WebSocketTestSession, **message: object) -> None:
    ws.send_text(json.dumps(message))


def _local(ws: WebSocketTestSession, version: int, limit: int = 60) -> list[dict[str, Any]]:
    """The next local_ai suggestions for `version` that are not empty-before-checking."""
    for _ in range(limit):
        message: dict[str, Any] = ws.receive_json()
        if (
            message["type"] == "suggestions"
            and message["source"] == "local_ai"
            and message["version"] == version
            and message["suggestions"]
        ):
            return list(message["suggestions"])
    raise AssertionError(f"no local_ai suggestions for version {version}")


def _idle(ws: WebSocketTestSession, limit: int = 60) -> list[dict[str, Any]]:
    """Messages up to the local check becoming idle (pending 0)."""
    seen: list[dict[str, Any]] = []
    for _ in range(limit):
        message: dict[str, Any] = ws.receive_json()
        seen.append(message)
        if message["type"] == "local_check_status" and message["pending"] == 0:
            return seen
    raise AssertionError("the local check did not become idle")


def _edit(ws: WebSocketTestSession, content: str, version: int) -> None:
    _send(ws, type="doc_changed", path=CHAPTER, content=content, version=version)
    cursor = content.index(EDITABLE[:10]) if EDITABLE[:10] in content else 0
    _send(ws, type="typing_paused", path=CHAPTER, version=version, cursor=cursor)


def test_edited_paragraph_is_checked_after_a_pause_and_never_resent(
    app: TestClient, ollama: FakeOllama
) -> None:
    edited = EDITABLE.replace("gleich bearbeitet", "bearbeitet, weil er hat keine Zeit")
    with _connect(app) as ws:
        _send(ws, type="doc_opened", path=CHAPTER, content=ORIGINAL, version=1)
        content = ORIGINAL.replace(EDITABLE, edited)
        _edit(ws, content, 2)
        [found] = _local(ws, 2)
        assert found["source"] == "local_ai"
        assert found["original"] == "weil er hat keine Zeit"
        assert found["fixes"] == ["weil er keine Zeit hat"]
        assert found["start"] == content.index("weil er hat keine Zeit", content.index(edited))
        _idle(ws)
        # Only the edited paragraph went to the model; the untouched one (which contains
        # the same mistake) was never sent.
        assert ollama.paragraphs == [edited]

        # Same text again, then the paragraph moves down: cached, nothing re-sent, and
        # the finding follows the text.
        _send(ws, type="typing_paused", path=CHAPTER, version=2, cursor=0)
        _idle(ws)
        moved = content.replace("= Einleitung", "= Einleitung und Motivation")
        _edit(ws, moved, 3)
        [found] = _local(ws, 3)
        assert found["start"] == moved.index("weil er hat keine Zeit", moved.index(edited))
        _idle(ws)
        assert ollama.paragraphs == [edited]


def test_changes_to_typst_markup_are_dropped(app: TestClient, ollama: FakeOllama) -> None:
    edited = "MARKUP: Die Messung wurde wie in @fig:aufbau gezeigt, die Ergebnis stimmt."
    with _connect(app) as ws:
        _send(ws, type="doc_opened", path=CHAPTER, content=ORIGINAL, version=1)
        content = ORIGINAL.replace(EDITABLE, edited)
        _edit(ws, content, 2)
        found = _local(ws, 2)
        # The fake proposed two changes; the one deleting "@fig:aufbau" was dropped.
        assert [f["original"] for f in found] == ["die Ergebnis"]


def test_typing_cancels_the_running_request(app: TestClient, ollama: FakeOllama) -> None:
    ollama.delay = 1.0
    first = EDITABLE + " Die Ergebnis ist klar."
    with _connect(app) as ws:
        _send(ws, type="doc_opened", path=CHAPTER, content=ORIGINAL, version=1)
        _edit(ws, ORIGINAL.replace(EDITABLE, first), 2)
        _send(ws, type="doc_changed", path=CHAPTER, content=ORIGINAL, version=3)  # undone
        seen = _idle(ws)
        stale = [
            m
            for m in seen
            if m["type"] == "suggestions" and m["source"] == "local_ai" and m["suggestions"]
        ]
        assert stale == []  # the cancelled check delivered nothing


def test_local_slot_none_sends_nothing(app: TestClient, ollama: FakeOllama) -> None:
    app.put("/api/ai/settings", json={"local_model": None})
    with _connect(app) as ws:
        _send(ws, type="doc_opened", path=CHAPTER, content=ORIGINAL, version=1)
        _edit(ws, ORIGINAL.replace(EDITABLE, EDITABLE + " Die Ergebnis."), 2)
        _idle(ws)
    assert ollama.paragraphs == []


def test_local_findings_on_spelling_findings_are_dropped(
    app: TestClient, workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LTEX_DIR_ENV_VAR, str(make_fake_ltex_install(tmp_path / "ltex")))
    edited = EDITABLE + " Das ist ein Fehlr, und die Ergebnis stimmt."
    with app_client() as client:
        client.post("/api/workspace/open", json={"path": str(workspace)})
        client.put("/api/ai/settings", json={"local_model": MODEL})
        with _connect(client) as ws:
            _send(ws, type="doc_opened", path=CHAPTER, content=ORIGINAL, version=1)
            content = ORIGINAL.replace(EDITABLE, edited)
            _send(ws, type="doc_changed", path=CHAPTER, content=content, version=2)
            for _ in range(60):  # wait for the spelling check of version 2
                message = ws.receive_json()
                if (
                    message["type"] == "suggestions"
                    and message["source"] == "rule"
                    and message["version"] == 2
                ):
                    break
            _send(ws, type="typing_paused", path=CHAPTER, version=2, cursor=len(content) - 2)
            found = _local(ws, 2)
    # "ein Fehlr" overlaps LTeX+'s finding "Fehlr" and is dropped; the rest stays.
    assert [f["original"] for f in found] == ["die Ergebnis"]


def test_ollama_offline_means_none(client: TestClient) -> None:
    status = client.get("/api/ai/status").json()["local"]
    assert status["available"] is False
    assert "Ollama is not running" in status["reason"]
    response = client.put("/api/ai/settings", json={"local_model": MODEL})
    assert response.status_code == 409
    assert "not running" in response.json()["detail"]


def test_unknown_local_model_is_refused(app: TestClient) -> None:
    response = app.put("/api/ai/settings", json={"local_model": "gpt-4"})
    assert response.status_code == 409
    assert app.get("/api/ai/status").json()["local"]["models"] == [MODEL]
