"""Phase 6d: autocomplete with Tinymist (fake server; the real one in test_tinymist_real)."""

import hashlib
import json
import stat
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from typst_writer.adapters.tinymist import lsp_position, to_items
from typst_writer.config import TinymistConfig, load_config
from typst_writer.infra import tool_download
from typst_writer.infra.tinymist_install import (
    TINYMIST_ENV_VAR,
    download_url,
    find_installation,
    install,
    platform_key,
)
from typst_writer.infra.tool_download import InstallError
from typst_writer.main import create_app

from helpers import FRONTEND_ORIGIN, WS_URL, make_fake_tinymist, receive_until

CHAPTER = "== Einleitung <sec:intro>\n\nSiehe \n"


# --- mapping ---------------------------------------------------------------------------


def _edit(line: int, start: int, end: int, text: str) -> dict[str, object]:
    return {
        "newText": text,
        "range": {
            "start": {"line": line, "character": start},
            "end": {"line": line, "character": end},
        },
    }


def test_items_are_validated_mapped_and_deduplicated() -> None:
    content = "😀 #fi"  # the emoji is 2 UTF-16 units
    result = {
        "items": [
            {
                "label": "figure",
                "kind": 3,
                "insertTextFormat": 2,
                "sortText": "001",
                "labelDetails": {"description": "(content) => figure"},
                "textEdit": _edit(0, 4, 6, "figure(${1:body})"),
            },
            {
                "label": "figure",
                "kind": 3,
                "sortText": "002",
                "textEdit": _edit(0, 4, 6, "figure(${1:body})"),
            },
            {
                "label": "fill",
                "kind": 3,
                "sortText": "000",
                "detail": "Line one.\nMore.",
                "textEdit": _edit(0, 4, 6, "fill"),
            },
            {"kind": 3},  # no label: dropped
            {"label": "far", "textEdit": _edit(0, 0, 1, "far")},  # does not touch the cursor
            {"label": "plain", "insertText": "plain()"},
            {"label": "table", "textEdit": _edit(0, 4, 6, "table")},  # "fi" typed: not shown
        ]
    }
    items = to_items(content, len(content), result)
    assert [i.label for i in items] == ["fill", "figure", "plain"]
    fill, figure, plain = items
    assert (figure.start, figure.end, figure.snippet, figure.kind) == (4, 6, True, "function")
    assert figure.detail == "(content) => figure"
    assert fill.detail == "Line one."
    assert (plain.insert, plain.start, plain.end, plain.snippet) == ("plain()", 6, 6, False)


def test_unexpected_answers_give_no_items() -> None:
    assert to_items("x", 1, None) == []
    assert to_items("x", 1, {"items": "nope"}) == []
    assert to_items("x", 1, [{"label": "a" * 500, "insertText": "a"}]) == []


def test_lsp_position_counts_utf16() -> None:
    text = "ab\n😀c"
    assert lsp_position(text, len(text)) == {"line": 1, "character": 3}
    assert lsp_position(text, 2) == {"line": 0, "character": 2}


# --- install -----------------------------------------------------------------------------


def test_platform_keys_and_urls() -> None:
    assert platform_key("win32", "AMD64") == "win32-x64"
    assert platform_key("darwin", "arm64") == "darwin-arm64"
    assert platform_key("linux", "aarch64") == "linux-arm64"
    assert platform_key("sunos5", "x86_64") is None
    config = load_config().tinymist
    assert download_url(config, "win32-x64").endswith("/v0.15.8/tinymist-win32-x64.exe")
    assert download_url(config, "linux-x64").endswith("/v0.15.8/tinymist-linux-x64")
    assert set(config.sha256) >= {"win32-x64", "linux-x64", "darwin-arm64", "darwin-x64"}


def _config(program: bytes) -> TinymistConfig:
    key = platform_key()
    assert key is not None
    return TinymistConfig(
        version="9.9.9",
        url="https://example.invalid/v{version}/tinymist-{platform}",
        sha256={key: hashlib.sha256(program).hexdigest()},
    )


@pytest.mark.anyio
async def test_install_verifies_and_makes_the_program_executable(isolated_app_home: Path) -> None:
    program = b"#!/bin/sh\necho tinymist\n"
    config = _config(program)
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, content=program)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        installed = await install(config, lambda *_: None, client)
        assert await install(config, lambda *_: None, client) == installed
    assert len(requests) == 1
    assert installed.parent == isolated_app_home / "cache" / "tinymist-9.9.9"
    assert installed.read_bytes() == program
    assert installed.stat().st_mode & stat.S_IXUSR
    assert find_installation(config) == installed
    assert [p.name for p in installed.parent.iterdir()] == [installed.name]


@pytest.mark.anyio
async def test_checksum_mismatch_installs_nothing(isolated_app_home: Path) -> None:
    config = _config(b"expected")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"tampered")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(InstallError, match="checksum"):
            await install(config, lambda *_: None, client)
    assert find_installation(config) is None
    assert list((isolated_app_home / "cache" / "tinymist-9.9.9").iterdir()) == []


# --- API with the fake Tinymist -----------------------------------------------------------


@pytest.fixture
def tinymist_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(TINYMIST_ENV_VAR, str(make_fake_tinymist(tmp_path / "tinymist-bin")))
    log = tmp_path / "tinymist.jsonl"
    monkeypatch.setenv("FAKE_TINYMIST_LOG", str(log))
    return log


@pytest.fixture
def completing(tinymist_log: Path, workspace: Path) -> Iterator[TestClient]:
    (workspace / "main.typ").write_text(
        '= Thesis <sec:thesis>\n#include "chapters/intro.typ"\n', encoding="utf-8"
    )
    (workspace / "chapters" / "intro.typ").write_text(CHAPTER, encoding="utf-8")
    with TestClient(create_app(load_config()), base_url="http://127.0.0.1") as client:
        assert client.post("/api/workspace/open", json={"path": str(workspace)}).status_code == 200
        yield client


def _complete(
    client: TestClient, path: str, content: str, offset: int | None = None
) -> list[dict[str, object]]:
    body = {"path": path, "content": content, "offset": len(content) if offset is None else offset}
    response = client.post("/api/complete", json=body)
    assert response.status_code == 200, response.text
    items: list[dict[str, object]] = response.json()
    return items


def test_not_installed_offers_nothing_and_says_why(opened: TestClient) -> None:
    status = opened.get("/api/completion").json()
    assert status["state"] == "not_installed"
    assert "Tinymist" in status["reason"]
    assert _complete(opened, "main.typ", "#fi") == []


def test_functions_and_labels_from_other_chapters(
    completing: TestClient, tinymist_log: Path
) -> None:
    assert completing.get("/api/completion").json()["state"] == "ready"
    text = CHAPTER.replace("Siehe ", "Siehe #fi")
    items = _complete(completing, "chapters/intro.typ", text, text.index("#fi") + 3)
    assert items[0] == {
        "label": "figure",
        "detail": "(..) => figure",
        "kind": "function",
        "insert": "figure(${1:body})",
        "snippet": True,
        "start": text.index("fi"),
        "end": text.index("fi") + 2,
    }
    # The unsaved text is what counts; labels come from the pinned main file and its chapters.
    text = CHAPTER.replace("Siehe ", "Siehe @")
    labels = [
        i["label"] for i in _complete(completing, "chapters/intro.typ", text, text.index("@") + 1)
    ]
    assert labels == ["sec:thesis", "sec:intro"]
    messages = [json.loads(line) for line in tinymist_log.read_text().splitlines()]
    methods = [m["method"] for m in messages]
    assert methods.count("initialize") == 1  # one process for the folder
    pins = [m["params"] for m in messages if m["method"] == "workspace/executeCommand"]
    assert len(pins) == 1 and pins[0]["arguments"][0].endswith("/thesis/main.typ")
    assert methods.count("textDocument/didOpen") == 1
    assert methods.count("textDocument/didChange") == 2  # once with the didOpen, see adapter
    init = next(m["params"] for m in messages if m["method"] == "initialize")
    assert init["initializationOptions"]["exportPdf"] == "never"


@pytest.mark.parametrize(
    "path", ["../secret.typ", "/etc/x.typ", "refs.bib", "chapters/../../x.typ"]
)
def test_only_typ_files_inside_the_folder(
    completing: TestClient, tinymist_log: Path, path: str
) -> None:
    assert _complete(completing, path, "#fi") == []
    assert not tinymist_log.exists() or "didOpen" not in tinymist_log.read_text()


def test_no_folder_offers_nothing(tinymist_log: Path, client: TestClient) -> None:
    assert _complete(client, "main.typ", "#fi") == []


def test_a_crash_gives_no_items_and_the_next_request_restarts(
    completing: TestClient, monkeypatch: pytest.MonkeyPatch, tinymist_log: Path
) -> None:
    monkeypatch.setenv("FAKE_TINYMIST_MODE", "crash_on_complete")
    assert _complete(completing, "main.typ", "#fi") == []
    monkeypatch.setenv("FAKE_TINYMIST_MODE", "ok")
    assert [i["label"] for i in _complete(completing, "main.typ", "#fi")] == ["figure"]
    methods = [json.loads(line)["method"] for line in tinymist_log.read_text().splitlines()]
    assert methods.count("initialize") == 2


def test_limits_on_the_request(completing: TestClient) -> None:
    too_long = {"path": "main.typ", "content": "x" * 2_000_001, "offset": 0}
    assert completing.post("/api/complete", json=too_long).status_code == 422
    negative = {"path": "main.typ", "content": "x", "offset": -1}
    assert completing.post("/api/complete", json=negative).status_code == 422


def test_install_endpoint_reports_progress(
    opened: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    program = make_fake_tinymist(tmp_path / "downloaded")

    async def fake_install(config: TinymistConfig, progress: tool_download.Progress) -> Path:
        progress("download", 50, 100)
        return program

    monkeypatch.setattr("typst_writer.services.completion.install", fake_install)
    with opened.websocket_connect(WS_URL, headers={"origin": FRONTEND_ORIGIN}) as ws:
        assert receive_until(ws, "completer_status")["status"]["state"] == "not_installed"
        assert opened.post("/api/completion/install").json()["state"] == "installing"
        states = []
        for _ in range(4):
            status = receive_until(ws, "completer_status")["status"]
            states.append(status["state"])
            if status["state"] == "ready":
                break
        assert states[-1] == "ready"
    assert opened.get("/api/completion").json()["state"] == "ready"
