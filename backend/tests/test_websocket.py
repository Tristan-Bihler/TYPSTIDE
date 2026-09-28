"""Live preview over WebSocket, plus the Phase 1 acceptance flow end to end."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from helpers import (
    FRONTEND_ORIGIN,
    WS_URL,
    receive_compile,
    receive_compile_until,
    receive_until,
)


def test_initial_messages_without_workspace(client: TestClient) -> None:
    with client.websocket_connect(WS_URL) as ws:
        assert receive_until(ws, "workspace_changed")["workspace"] is None
        assert receive_compile(ws)["compile_status"]["state"] == "no_workspace"


def test_foreign_origin_is_refused(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(WS_URL, headers={"origin": "http://evil.example"}) as ws,
    ):
        ws.receive_json()


def test_initial_compile_renders_main(opened: TestClient) -> None:
    with opened.websocket_connect(WS_URL, headers={"origin": FRONTEND_ORIGIN}) as ws:
        assert receive_until(ws, "workspace_changed")["workspace"]["main"] == "main.typ"
        cycle = receive_compile(ws)
        assert cycle["compile_status"]["state"] == "ok"
        [page] = cycle["preview_pages"]["pages"]
        assert page["svg"].startswith("<svg")
        assert cycle["problems"]["problems"] == []


def test_only_changed_pages_are_resent(opened: TestClient) -> None:
    two_pages = "== Einleitung\nA\n#pagebreak()\nB\n"
    with opened.websocket_connect(WS_URL) as ws:
        receive_compile(ws)
        ws.send_json({"type": "doc_changed", "path": "chapters/intro.typ", "content": two_pages})
        pages = receive_compile(ws)["preview_pages"]["pages"]
        assert [p["svg"] is None for p in pages] == [False, False]

        edited = two_pages.replace("B", "B, edited")
        ws.send_json({"type": "doc_changed", "path": "chapters/intro.typ", "content": edited})
        pages = receive_compile(ws)["preview_pages"]["pages"]
        assert [p["svg"] is None for p in pages] == [True, False]

        ws.send_json({"type": "refresh"})
        pages = receive_compile(ws)["preview_pages"]["pages"]
        assert [p["svg"] is None for p in pages] == [True, True]


def test_error_keeps_last_preview_and_reports_problem(opened: TestClient) -> None:
    with opened.websocket_connect(WS_URL) as ws:
        receive_compile(ws)
        ws.send_json({"type": "doc_changed", "path": "chapters/intro.typ", "content": "Hi\n#nope"})
        cycle = receive_compile(ws)
        assert "preview_pages" not in cycle
        assert cycle["compile_status"]["state"] == "error"
        [problem] = cycle["problems"]["problems"]
        assert (problem["file"], problem["line"], problem["severity"]) == (
            "chapters/intro.typ",
            2,
            "error",
        )

        ws.send_json({"type": "doc_closed", "path": "chapters/intro.typ"})
        assert receive_compile(ws)["compile_status"]["state"] == "ok"


def test_buffers_outside_workspace_are_ignored(opened: TestClient, workspace: Path) -> None:
    with opened.websocket_connect(WS_URL) as ws:
        receive_compile(ws)
        ws.send_json({"type": "doc_changed", "path": "../evil.typ", "content": "x"})
        ws.send_json({"type": "bogus"})
        ws.send_json({"type": "refresh"})
        assert receive_compile(ws)["compile_status"]["state"] == "ok"
    assert not (workspace.parent / "evil.typ").exists()


def test_rest_changes_notify_and_recompile(opened: TestClient) -> None:
    with opened.websocket_connect(WS_URL) as ws:
        receive_compile(ws)
        opened.put("/api/workspace/main", json={"path": "chapters/intro.typ"})
        assert receive_until(ws, "workspace_changed")["workspace"]["main"] == "chapters/intro.typ"
        assert receive_compile(ws)["compile_status"]["main"] == "chapters/intro.typ"


def test_phase1_acceptance_flow(client: TestClient, tmp_path: Path) -> None:
    """Open folder, create/edit/save .typ, preview < 1 s, errors located, PDF export."""
    folder = tmp_path / "Bachelorarbeit"
    folder.mkdir()
    assert client.post("/api/workspace/open", json={"path": str(folder)}).status_code == 200

    with client.websocket_connect(WS_URL, headers={"origin": FRONTEND_ORIGIN}) as ws:
        assert receive_compile(ws)["compile_status"]["state"] == "no_main"

        client.post("/api/workspace/folder", json={"name": "kapitel"})
        client.post("/api/workspace/file", json={"name": "main.typ"})
        client.post("/api/workspace/file", json={"parent": "kapitel", "name": "01.typ"})
        client.put("/api/workspace/main", json={"path": "main.typ"})
        main_src = '= Bachelorarbeit\n#include "kapitel/01.typ"\n'
        client.put("/api/workspace/file", json={"path": "main.typ", "content": main_src})

        # Edit a chapter without saving: preview of main updates in < 1 s.
        start = time.perf_counter()
        ws.send_json(
            {"type": "doc_changed", "path": "kapitel/01.typ", "content": "== Einleitung\nHallo."}
        )
        cycle = receive_compile_until(ws, lambda c: "preview_pages" in c)
        assert time.perf_counter() - start < 1.0
        assert cycle["compile_status"]["main"] == "main.typ"

        # An error in the chapter is reported with its location.
        ws.send_json({"type": "doc_changed", "path": "kapitel/01.typ", "content": "#fehler"})
        cycle = receive_compile_until(ws, lambda c: c["compile_status"]["state"] == "error")
        [problem] = cycle["problems"]["problems"]
        assert (problem["file"], problem["line"], problem["column"]) == ("kapitel/01.typ", 1, 2)

        # Save the fixed chapter; export the PDF.
        client.put("/api/workspace/file", json={"path": "kapitel/01.typ", "content": "Fertig."})
        ws.send_json({"type": "doc_closed", "path": "kapitel/01.typ"})
    assert (folder / "kapitel" / "01.typ").read_text(encoding="utf-8") == "Fertig."
    pdf = client.post("/api/export/pdf", json={"overlays": {}})
    assert pdf.content.startswith(b"%PDF-")
