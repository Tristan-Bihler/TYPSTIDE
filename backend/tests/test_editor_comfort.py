"""Phase 6a backend: UI settings, remembered tabs, word counts."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typst_writer.domain.word_count import count_words, document_counts, includes

from helpers import FRONTEND_ORIGIN, WS_URL, app_client, receive_until


def test_word_count_ignores_markup() -> None:
    source = (
        "= Einleitung <sec:a>\n\n"
        "Das ist *wichtig* und _klar_, siehe @fig:a und $E = m c^2$.\n"
        "// ein Kommentar zählt nicht\n"
        '#figure(image("/b.svg"), caption: [Drei Wörter hier]) <fig:a>\n'
        "```python\nprint('code zählt nicht')\n```\n"
        "Max-Planck-Institut don't\n"
    )
    # Einleitung | Das ist wichtig und klar siehe und | Drei Wörter hier | Max-Planck-Institut don't
    assert count_words(source) == 1 + 7 + 3 + 2


def test_includes_are_resolved_relative_and_root_relative() -> None:
    source = (
        '#include "kapitel/01.typ"\n'
        '#include "/anhang/a.typ"\n'
        '// #include "kommentar.typ"\n'
        '`#include "raw.typ"`\n'
        '#include "../../outside.typ"\n'
    )
    assert includes(source, "main.typ") == ["kapitel/01.typ", "anhang/a.typ"]
    assert includes('#include "02.typ"', "kapitel/01.typ") == ["kapitel/02.typ"]


def test_document_counts_follow_includes_once() -> None:
    files = {
        "main.typ": '= Titel\n#include "kapitel/a.typ"\n#include "kapitel/a.typ"\n',
        "kapitel/a.typ": 'Eins zwei drei.\n#include "b.typ"\n',
        "kapitel/b.typ": 'Vier fünf.\n#include "/main.typ"\n',
    }
    assert document_counts("main.typ", files.get) == {
        "main.typ": 1,
        "kapitel/a.typ": 3,
        "kapitel/b.typ": 2,
    }


def test_word_count_is_sent_after_each_compile(opened: TestClient) -> None:
    with opened.websocket_connect(WS_URL, headers={"origin": FRONTEND_ORIGIN}) as ws:
        first = receive_until(ws, "word_count")
        assert first["files"] == {"main.typ": 1, "chapters/intro.typ": 2}
        assert first["total"] == 3
        change = {
            "type": "doc_changed",
            "path": "chapters/intro.typ",
            "content": "== Einleitung\nText mit fünf Wörtern hier.\n",
        }
        ws.send_text(json.dumps(change))
        for _ in range(5):
            count = receive_until(ws, "word_count")
            if count["files"]["chapters/intro.typ"] == 6:
                break
        assert count["total"] == 7


def test_ui_settings_default_validate_and_persist(client: TestClient) -> None:
    assert client.get("/api/settings/ui").json() == {
        "theme": "system",
        "autosave": True,
        "autosave_delay_ms": 2000,
        "preview_follows_cursor": True,
    }
    new = {
        "theme": "dark",
        "autosave": False,
        "autosave_delay_ms": 5000,
        "preview_follows_cursor": False,
    }
    assert client.put("/api/settings/ui", json=new).json() == new
    for bad in [{**new, "theme": "neon"}, {**new, "autosave_delay_ms": 10}, {**new, "x": 1}]:
        assert client.put("/api/settings/ui", json=bad).status_code == 422
    with app_client() as fresh:
        assert fresh.get("/api/settings/ui").json() == new


def test_open_tabs_are_remembered_per_workspace(opened: TestClient, workspace: Path) -> None:
    tabs = {
        "tabs": [{"path": "main.typ", "cursor": 3}, {"path": "chapters/intro.typ", "cursor": 10}],
        "active": "chapters/intro.typ",
    }
    assert opened.put("/api/workspace/tabs", json=tabs).status_code == 200
    # Changing the main file keeps the tabs (and vice versa).
    opened.put("/api/workspace/main", json={"path": "chapters/intro.typ"})
    assert opened.get("/api/workspace/tabs").json() == tabs
    assert opened.get("/api/workspace").json()["main"] == "chapters/intro.typ"
    # A file deleted meanwhile is left out; so is the active tab if it was that file.
    (workspace / "chapters" / "intro.typ").unlink()
    assert opened.get("/api/workspace/tabs").json() == {
        "tabs": [{"path": "main.typ", "cursor": 3}],
        "active": None,
    }


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd"])
def test_tabs_outside_the_workspace_are_refused(opened: TestClient, path: str) -> None:
    body = {"tabs": [{"path": path, "cursor": 0}], "active": None}
    assert opened.put("/api/workspace/tabs", json=body).status_code == 403


def test_too_many_tabs_are_refused(opened: TestClient) -> None:
    body = {"tabs": [{"path": "main.typ", "cursor": 0}] * 51, "active": None}
    assert opened.put("/api/workspace/tabs", json=body).status_code == 422
