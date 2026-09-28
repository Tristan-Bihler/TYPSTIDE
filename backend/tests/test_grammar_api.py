"""Spelling and grammar over REST and WebSocket, with the fake LTeX+ (no Java needed)."""

import json
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from typst_writer.config import load_config
from typst_writer.infra import ltex_install, tool_download
from typst_writer.infra.ltex_install import LTEX_DIR_ENV_VAR
from typst_writer.services import grammar as grammar_service

from helpers import (
    FRONTEND_ORIGIN,
    WS_URL,
    app_client,
    make_fake_ltex_install,
    receive_suggestions,
    receive_until,
)

CHAPTER = "chapters/intro.typ"


@pytest.fixture
def fake_ltex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = make_fake_ltex_install(tmp_path / "ltex")
    monkeypatch.setenv(LTEX_DIR_ENV_VAR, str(home))
    return home


def _connect(client: TestClient) -> AbstractContextManager[WebSocketTestSession]:
    return client.websocket_connect(WS_URL, headers={"origin": FRONTEND_ORIGIN})


def _wait_ready(ws: WebSocketTestSession) -> None:
    for _ in range(40):
        message = ws.receive_json()
        if message["type"] == "checker_status" and message["status"]["state"] == "ready":
            return
    raise AssertionError("the checker did not become ready")


def _open(ws: WebSocketTestSession, content: str, version: int = 1) -> None:
    message = {"type": "doc_opened", "path": CHAPTER, "content": content, "version": version}
    ws.send_text(json.dumps(message))


def test_without_ltex_everything_works_and_install_is_offered(opened: TestClient) -> None:
    overview = opened.get("/api/grammar").json()
    assert overview["status"]["state"] == "not_installed"
    assert "Install" in overview["status"]["reason"]
    assert overview["settings"] == {"language": "de-DE", "dictionary": {}}
    with _connect(opened) as ws:
        status = receive_until(ws, "checker_status")["status"]
        assert status["state"] == "not_installed"
        _open(ws, "Ein Fehlr.")
        assert receive_suggestions(ws, CHAPTER)["suggestions"] == []


def test_opened_file_is_checked_and_changes_are_rechecked(workspace: Path, fake_ltex: Path) -> None:
    with app_client() as client:
        client.post("/api/workspace/open", json={"path": str(workspace)})
        with _connect(client) as ws:
            _wait_ready(ws)
            _open(ws, "Ein Fehlr im Text.")
            message = receive_suggestions(ws, CHAPTER)
            assert message["version"] == 1
            assert message["source"] == "rule"
            [finding] = message["suggestions"]
            assert (finding["start"], finding["end"], finding["fixes"]) == (4, 9, ["Fehler"])
            assert finding["category"] == "spelling"

            change = {
                "type": "doc_changed",
                "path": CHAPTER,
                "content": "Ein Fehler im Text.",
                "version": 2,
            }
            ws.send_text(json.dumps(change))
            message = receive_suggestions(ws, CHAPTER)
            assert (message["version"], message["suggestions"]) == (2, [])


def test_files_outside_the_workspace_and_other_types_are_not_checked(
    workspace: Path, fake_ltex: Path
) -> None:
    with app_client() as client:
        client.post("/api/workspace/open", json={"path": str(workspace)})
        with _connect(client) as ws:
            _wait_ready(ws)
            for path in ["../secret.typ", "refs.bib"]:
                message = {"type": "doc_opened", "path": path, "content": "Fehlr", "version": 1}
                ws.send_text(json.dumps(message))
            _open(ws, "Ein Fehlr.")
            # The first suggestions message is for the chapter: the others were ignored.
            assert receive_until(ws, "suggestions")["path"] == CHAPTER


def test_language_and_dictionary_trigger_a_recheck_and_persist(
    workspace: Path, fake_ltex: Path
) -> None:
    with app_client() as client:
        client.post("/api/workspace/open", json={"path": str(workspace)})
        with _connect(client) as ws:
            _wait_ready(ws)
            _open(ws, "Fehlr and teh end.")
            assert [s["original"] for s in receive_suggestions(ws, CHAPTER)["suggestions"]] == [
                "Fehlr"
            ]

            overview = client.put("/api/grammar/settings", json={"language": "en-US"}).json()
            assert overview["settings"]["language"] == "en-US"
            english = receive_suggestions(ws, CHAPTER)["suggestions"]
            assert [s["original"] for s in english] == ["teh"]

            word = {"language": "en-US", "word": "teh"}
            overview = client.post("/api/grammar/dictionary", json=word).json()
            assert overview["settings"]["dictionary"] == {"en-US": ["teh"]}
            assert receive_suggestions(ws, CHAPTER)["suggestions"] == []

    with app_client() as fresh:
        settings = fresh.get("/api/grammar").json()["settings"]
        assert settings == {"language": "en-US", "dictionary": {"en-US": ["teh"]}}


@pytest.mark.parametrize(
    "body",
    [
        {"language": "en-US", "word": "two words"},
        {"language": "en-US", "word": ""},
        {"language": "en-US", "word": "x" * 101},
        {"language": "fr-FR", "word": "mot"},
        {"language": "en-US", "word": "ok", "extra": 1},
    ],
)
def test_invalid_dictionary_words_are_rejected(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/grammar/dictionary", json=body).status_code == 422


def test_install_on_request_then_checks_run(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "ltex-installed"

    async def fake_install(
        config: object, progress: tool_download.Progress
    ) -> ltex_install.LtexInstallation:
        progress("download", 50, 100)
        progress("download", 100, 100)
        progress("unpack", 0, None)
        make_fake_ltex_install(home)
        found = ltex_install.find_installation(load_config().ltex)
        assert found is not None
        return found

    monkeypatch.setattr(grammar_service, "install", fake_install)
    with app_client() as client:
        client.post("/api/workspace/open", json={"path": str(workspace)})
        with _connect(client) as ws:
            assert receive_until(ws, "checker_status")["status"]["state"] == "not_installed"
            monkeypatch.setenv(LTEX_DIR_ENV_VAR, str(home))
            assert client.post("/api/grammar/install").json()["status"]["state"] == "installing"
            states = []
            for _ in range(40):
                message = ws.receive_json()
                if message["type"] == "checker_status":
                    states.append(message["status"])
                    if message["status"]["state"] == "ready":
                        break
            assert [s["state"] for s in states][-2:] == ["starting", "ready"]
            assert any(s["progress"] == 0.5 for s in states)
            _open(ws, "Ein Fehlr.")
            assert len(receive_suggestions(ws, CHAPTER)["suggestions"]) == 1


def test_old_settings_file_keeps_the_ai_slots(client: TestClient, isolated_app_home: Path) -> None:
    path = isolated_app_home / "config" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"local_model": None, "claude_model": "opus"}), encoding="utf-8")
    assert client.get("/api/ai/status").json()["settings"]["claude_model"] == "opus"
    client.put("/api/grammar/settings", json={"language": "en-US"})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["ai"]["claude_model"] == "opus"
    assert saved["grammar"]["language"] == "en-US"


def test_word_lists_are_per_project(client: TestClient, workspace: Path, tmp_path: Path) -> None:
    other = tmp_path / "other-thesis"
    other.mkdir()
    client.post("/api/workspace/open", json={"path": str(workspace)})
    client.post("/api/grammar/dictionary", json={"language": "de-DE", "word": "Messplatz"})
    client.post("/api/grammar/dictionary", json={"language": "de-DE", "word": "Aufbau"})
    assert client.get("/api/grammar").json()["settings"]["dictionary"] == {
        "de-DE": ["Aufbau", "Messplatz"]
    }
    client.post("/api/workspace/open", json={"path": str(other)})
    assert client.get("/api/grammar").json()["settings"]["dictionary"] == {}
    client.post("/api/grammar/dictionary", json={"language": "de-DE", "word": "Sonstiges"})
    client.post("/api/workspace/open", json={"path": str(workspace)})
    params = {"language": "de-DE", "word": "Aufbau"}
    removed = client.delete("/api/grammar/dictionary", params=params).json()
    assert removed["settings"]["dictionary"] == {"de-DE": ["Messplatz"]}


def test_words_need_an_open_folder(client: TestClient) -> None:
    response = client.post("/api/grammar/dictionary", json={"language": "de-DE", "word": "x"})
    assert response.status_code == 409
    assert response.json()["code"] == "no_workspace"


def test_global_words_from_before_move_into_the_open_project(
    client: TestClient, workspace: Path, isolated_app_home: Path
) -> None:
    path = isolated_app_home / "config" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {"grammar": {"language": "de-DE", "dictionary": {"de-DE": ["Altwort"]}}}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    client.post("/api/workspace/open", json={"path": str(workspace)})
    words = client.get("/api/grammar").json()["settings"]["dictionary"]
    assert words == {"de-DE": ["Altwort"]}
    saved = json.loads(path.read_text(encoding="utf-8"))["grammar"]
    assert saved["dictionary"] == {}
    assert saved["dictionaries"] == {str(workspace.resolve()): {"de-DE": ["Altwort"]}}


def test_checks_use_the_open_projects_words(workspace: Path, fake_ltex: Path) -> None:
    with app_client() as client:
        client.post("/api/workspace/open", json={"path": str(workspace)})
        with _connect(client) as ws:
            _wait_ready(ws)
            _open(ws, "Ein Fehlr.")
            assert len(receive_suggestions(ws, CHAPTER)["suggestions"]) == 1
            client.post("/api/grammar/dictionary", json={"language": "de-DE", "word": "Fehlr"})
            assert receive_suggestions(ws, CHAPTER)["suggestions"] == []
            client.delete("/api/grammar/dictionary", params={"language": "de-DE", "word": "Fehlr"})
            assert len(receive_suggestions(ws, CHAPTER)["suggestions"]) == 1
