"""REST workspace operations, including path traversal attempts over HTTP."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typst_writer.config import load_config
from typst_writer.main import create_app


def test_no_workspace_initially(client: TestClient) -> None:
    assert client.get("/api/workspace").json() is None
    response = client.get("/api/workspace/tree")
    assert response.status_code == 409
    assert response.json()["code"] == "no_workspace"


def test_open_detects_main_file(opened: TestClient, workspace: Path) -> None:
    info = opened.get("/api/workspace").json()
    assert info == {"root": str(workspace.resolve()), "name": "thesis", "main": "main.typ"}


def test_open_rejects_missing_or_relative_folder(client: TestClient, tmp_path: Path) -> None:
    assert client.post("/api/workspace/open", json={"path": str(tmp_path / "x")}).status_code == 404
    assert client.post("/api/workspace/open", json={"path": "relative"}).status_code == 404


def test_tree_sorted_folders_first_hidden_skipped(opened: TestClient) -> None:
    tree = opened.get("/api/workspace/tree").json()
    names = [(c["name"], c["kind"]) for c in tree["root"]["children"]]
    assert names == [
        ("chapters", "folder"),
        ("images", "folder"),
        ("main.typ", "file"),
        ("refs.bib", "file"),
    ]
    assert tree["root"]["children"][0]["children"][0]["path"] == "chapters/intro.typ"
    assert tree["truncated"] is False


def test_read_and_save(opened: TestClient, workspace: Path) -> None:
    response = opened.get("/api/workspace/file", params={"path": "chapters/intro.typ"})
    assert response.json()["content"] == "== Einleitung\nText.\n"
    saved = opened.put(
        "/api/workspace/file", json={"path": "chapters/intro.typ", "content": "Neu\r\näöü"}
    )
    assert saved.status_code == 200
    assert (workspace / "chapters" / "intro.typ").read_bytes() == "Neu\r\näöü".encode()
    assert not list(workspace.rglob("*.saving"))


def test_save_does_not_create_files(opened: TestClient) -> None:
    response = opened.put("/api/workspace/file", json={"path": "new.typ", "content": "x"})
    assert response.status_code == 404


def test_binary_files_cannot_be_opened(opened: TestClient, workspace: Path) -> None:
    (workspace / "images" / "a.png").write_bytes(b"\x89PNG")
    response = opened.get("/api/workspace/file", params={"path": "images/a.png"})
    assert response.status_code == 415


def test_create_file_validation_and_overwrite(opened: TestClient, workspace: Path) -> None:
    ok = opened.post("/api/workspace/file", json={"parent": "chapters", "name": "02-teil.typ"})
    assert ok.json() == {"path": "chapters/02-teil.typ"}

    bad = opened.post("/api/workspace/file", json={"parent": "", "name": "notes.txt"})
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_name")

    (workspace / "chapters" / "02-teil.typ").write_text("keep", encoding="utf-8")
    exists = opened.post("/api/workspace/file", json={"parent": "chapters", "name": "02-teil.typ"})
    assert (exists.status_code, exists.json()["code"]) == (409, "exists")
    assert (workspace / "chapters" / "02-teil.typ").read_text(encoding="utf-8") == "keep"

    confirmed = opened.post(
        "/api/workspace/file",
        json={"parent": "chapters", "name": "02-teil.typ", "overwrite": True},
    )
    assert confirmed.status_code == 200
    assert (workspace / "chapters" / "02-teil.typ").read_text(encoding="utf-8") == ""


def test_create_folder(opened: TestClient, workspace: Path) -> None:
    assert opened.post("/api/workspace/folder", json={"name": "appendix"}).status_code == 200
    assert (workspace / "appendix").is_dir()
    again = opened.post("/api/workspace/folder", json={"name": "appendix"})
    assert again.status_code == 409


def test_rename_updates_main(opened: TestClient, workspace: Path) -> None:
    response = opened.post(
        "/api/workspace/rename", json={"path": "main.typ", "new_name": "thesis.typ"}
    )
    assert response.json() == {"path": "thesis.typ"}
    assert (workspace / "thesis.typ").is_file()
    assert opened.get("/api/workspace").json()["main"] == "thesis.typ"


def test_rename_refuses_to_overwrite_without_confirmation(
    opened: TestClient, workspace: Path
) -> None:
    (workspace / "other.typ").write_text("other", encoding="utf-8")
    body = {"path": "other.typ", "new_name": "main.typ"}
    assert opened.post("/api/workspace/rename", json=body).status_code == 409
    confirmed = opened.post("/api/workspace/rename", json={**body, "overwrite": True})
    assert confirmed.status_code == 200
    assert (workspace / "main.typ").read_text(encoding="utf-8") == "other"


def test_delete_file_and_folder(opened: TestClient, workspace: Path) -> None:
    assert opened.delete("/api/workspace/entry", params={"path": "chapters"}).status_code == 200
    assert not (workspace / "chapters").exists()
    assert opened.delete("/api/workspace/entry", params={"path": "main.typ"}).status_code == 200
    assert opened.get("/api/workspace").json()["main"] is None
    assert opened.delete("/api/workspace/entry", params={"path": ""}).status_code == 422


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra privileges on Windows")
def test_delete_symlink_removes_link_not_target(opened: TestClient, workspace: Path) -> None:
    (workspace / "alias.typ").symlink_to(workspace / "main.typ")
    assert opened.delete("/api/workspace/entry", params={"path": "alias.typ"}).status_code == 200
    assert (workspace / "main.typ").is_file()


@pytest.mark.parametrize("path", ["../secret.txt", "..\\secret.txt", "/etc/passwd", "C:x.txt"])
def test_path_traversal_is_rejected_everywhere(
    opened: TestClient, workspace: Path, path: str
) -> None:
    secret = workspace.parent / "secret.txt"
    checks = [
        opened.get("/api/workspace/file", params={"path": path}),
        opened.put("/api/workspace/file", json={"path": path, "content": "pwned"}),
        opened.delete("/api/workspace/entry", params={"path": path}),
        opened.post("/api/workspace/rename", json={"path": path, "new_name": "x.txt"}),
        opened.post("/api/workspace/file", json={"parent": path, "name": "x.typ"}),
        opened.post("/api/workspace/folder", json={"parent": path, "name": "x"}),
        opened.put("/api/workspace/main", json={"path": path}),
        opened.post("/api/export/pdf", json={"overlays": {path: "x"}}),
    ]
    for response in checks:
        assert response.status_code in (403, 404, 422), response.text
    assert secret.read_text(encoding="utf-8") == "secret"


def test_rename_cannot_move_out_of_folder(opened: TestClient) -> None:
    response = opened.post(
        "/api/workspace/rename", json={"path": "main.typ", "new_name": "../main.typ"}
    )
    assert response.status_code == 422


def test_set_main(opened: TestClient) -> None:
    info = opened.put("/api/workspace/main", json={"path": "chapters/intro.typ"}).json()
    assert info["main"] == "chapters/intro.typ"
    assert opened.put("/api/workspace/main", json={"path": "refs.bib"}).status_code == 422


def test_state_is_restored_on_restart(opened: TestClient, workspace: Path) -> None:
    opened.put("/api/workspace/main", json={"path": "chapters/intro.typ"})
    with TestClient(create_app(load_config()), base_url="http://127.0.0.1") as fresh:
        info = fresh.get("/api/workspace").json()
    assert info["root"] == str(workspace.resolve())
    assert info["main"] == "chapters/intro.typ"


def test_browse_lists_folders_only(client: TestClient, workspace: Path) -> None:
    listing = client.get("/api/workspace/browse", params={"path": str(workspace)}).json()
    assert listing["dirs"] == ["chapters", "images"]
    assert listing["parent"] == str(workspace.parent.resolve())


def test_export_pdf_includes_unsaved_edits(opened: TestClient) -> None:
    response = opened.post(
        "/api/export/pdf", json={"overlays": {"chapters/intro.typ": "== Neu\nUnsaved text."}}
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert "main.pdf" in response.headers["content-disposition"]


def test_export_pdf_reports_errors(opened: TestClient) -> None:
    response = opened.post(
        "/api/export/pdf", json={"overlays": {"chapters/intro.typ": "#broken-call("}}
    )
    body = response.json()
    assert (response.status_code, body["code"]) == (422, "compile_failed")
    assert body["problems"][0]["file"] == "chapters/intro.typ"
