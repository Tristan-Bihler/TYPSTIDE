"""Phase 7: the Windows app's runtime, tested without a window (a fake `webview` module)."""

import base64
import json
import socket
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from typst_writer import desktop
from typst_writer.config import AppConfig, DesktopConfig, load_config
from typst_writer.desktop import BackgroundServer, DesktopApi, create_desktop_app, port_owner
from typst_writer.infra.app_dirs import HOME_ENV_VAR

PDF = b"%PDF-1.7\n%fake\n"


class Dialogs:
    def __init__(self, folder: str | None = None, save: str | None = None) -> None:
        self.folder, self.save = folder, save
        self.asked: list[tuple[str, str]] = []
        self.confirm: list[bool] = []

    def api(self) -> DesktopApi:
        def ask_folder(start: str) -> str | None:
            self.asked.append(("folder", start))
            return self.folder

        def ask_save(name: str) -> str | None:
            self.asked.append(("save", name))
            return self.save

        return DesktopApi(ask_folder, ask_save, self.confirm.append)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_pick_folder_returns_the_choice_or_none() -> None:
    dialogs = Dialogs(folder="C:/Arbeit")
    assert dialogs.api().pick_folder("C:/Start") == "C:/Arbeit"
    assert dialogs.api().pick_folder(42) == "C:/Arbeit"  # junk from the page: no start folder
    assert dialogs.asked == [("folder", "C:/Start"), ("folder", "")]
    assert Dialogs().api().pick_folder() is None


def test_save_pdf_writes_only_where_the_user_chose(tmp_path: Path) -> None:
    target = tmp_path / "Arbeit.pdf"
    dialogs = Dialogs(save=str(target))
    assert dialogs.api().save_pdf("../../evil/Arbeit.pdf", b64(PDF)) == str(target)
    assert target.read_bytes() == PDF
    assert dialogs.asked == [("save", "Arbeit.pdf")]  # only the name is suggested
    no_suffix = Dialogs(save=str(tmp_path / "ohne"))
    assert no_suffix.api().save_pdf("main", b64(PDF)) == str(tmp_path / "ohne.pdf")
    assert no_suffix.asked == [("save", "main.pdf")]
    assert Dialogs(save=None).api().save_pdf("x.pdf", b64(PDF)) is None


@pytest.mark.parametrize(
    ("filename", "data"),
    [
        ("x.pdf", "not base64!"),
        ("x.pdf", b64(b"MZ\x90\x00 an exe")),
        (None, b64(PDF)),
        ("x.pdf", 12),
        ("x.pdf", b64(PDF + b"x" * 100)),  # over the limit patched below
    ],
    ids=["not base64", "not a pdf", "no name", "no data", "too large"],
)
def test_save_pdf_refuses_anything_but_a_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: object, data: object
) -> None:
    monkeypatch.setattr(desktop, "MAX_PDF_BYTES", 64)
    dialogs = Dialogs(save=str(tmp_path / "x.pdf"))
    with pytest.raises(ValueError):
        dialogs.api().save_pdf(filename, data)
    assert dialogs.asked == []
    assert not (tmp_path / "x.pdf").exists()


def test_unsaved_changes_turn_the_close_confirmation_on_and_off() -> None:
    dialogs = Dialogs()
    api = dialogs.api()
    api.set_unsaved(True)
    api.set_unsaved(False)
    api.set_unsaved("yes")  # only a real true counts
    assert dialogs.confirm == [True, False, False]


def test_page_sees_only_the_three_methods() -> None:
    public = [name for name in dir(Dialogs().api()) if not name.startswith("_")]
    assert public == ["pick_folder", "save_pdf", "set_unsaved"]


# --- server and window ---------------------------------------------------------------


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    page = '<!doctype html><title>typst-writer</title><script src="/assets/app.js"></script>'
    (folder / "index.html").write_text(page, "utf-8")
    (folder / "assets" / "app.js").write_text("1", "utf-8")
    return folder


@pytest.fixture
def config() -> AppConfig:
    return load_config().model_copy(update={"desktop": DesktopConfig(port=desktop.free_port())})


def test_port_owner(config: AppConfig, dist: Path) -> None:
    port = config.desktop.port
    assert port_owner(port) == "free"
    with socket.socket() as other:
        other.bind(("127.0.0.1", port))
        other.listen()
        assert port_owner(port) == "other"
    server = BackgroundServer(create_desktop_app(config, port, dist), port, 1_000_000)
    server.start()
    try:
        assert port_owner(port) == "typst-writer"
    finally:
        server.stop()
    assert port_owner(port) == "free"


@pytest.fixture
def fake_webview(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """A `webview` module that records the window and, while "open", calls `on_open`."""
    seen: dict[str, Any] = {"settings": {}}
    module = types.ModuleType("webview")
    module.settings = seen["settings"]  # type: ignore[attr-defined]
    module.FileDialog = types.SimpleNamespace(FOLDER=20, SAVE=30)  # type: ignore[attr-defined]

    class Window:
        confirm_close = False

        def create_file_dialog(self, kind: int, **kwargs: object) -> tuple[str, ...]:
            seen.setdefault("dialogs", []).append((kind, kwargs))
            return ("C:/Arbeit",)

    def create_window(title: str, url: str, **kwargs: object) -> Window:
        seen["window"] = {"title": title, "url": url, **kwargs}
        window = Window()
        seen["handle"] = window
        return window

    def start(**kwargs: object) -> None:
        seen["start"] = kwargs
        seen["on_open"](seen)

    module.create_window = create_window  # type: ignore[attr-defined]
    module.start = start  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "webview", module)
    yield seen


def test_run_app_serves_the_frontend_in_a_window_and_stops_after(
    config: AppConfig, dist: Path, fake_webview: dict[str, Any]
) -> None:
    port = config.desktop.port

    def while_open(seen: dict[str, Any]) -> None:
        url = seen["window"]["url"]
        assert httpx.get(url, trust_env=False).text.startswith("<!doctype html>")
        api: DesktopApi = seen["window"]["js_api"]
        assert api.pick_folder("") == "C:/Arbeit"
        api.set_unsaved(True)
        seen["confirm_while_unsaved"] = seen["handle"].confirm_close

    fake_webview["on_open"] = while_open
    assert desktop.run_app(config, dist) == 0
    window, start = fake_webview["window"], fake_webview["start"]
    assert window["url"] == f"http://127.0.0.1:{port}/"
    assert window["confirm_close"] is False
    assert fake_webview["confirm_while_unsaved"] is True
    assert fake_webview["dialogs"][0][0] == 20
    assert start["gui"] == "edgechromium"
    assert start["private_mode"] is False
    assert fake_webview["settings"]["ALLOW_DOWNLOADS"] is False
    assert port_owner(port) == "free"  # the server stopped with the window


def test_a_second_start_only_says_it_is_running(
    config: AppConfig, dist: Path, fake_webview: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(desktop, "show_message", lambda _title, text: messages.append(text))
    port = config.desktop.port
    server = BackgroundServer(create_desktop_app(config, port, dist), port, 1_000_000)
    server.start()
    try:
        assert desktop.run_app(config, dist) == 0
    finally:
        server.stop()
    assert messages == ["typst-writer is already running."]
    assert "window" not in fake_webview
    with socket.socket() as other:
        other.bind(("127.0.0.1", port))
        other.listen()
        assert desktop.run_app(config, dist) == 1
    assert f"port {port}" in messages[-1]


def test_self_test_passes_and_leaves_the_users_settings_alone(
    dist: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "users-home"
    monkeypatch.setenv(HOME_ENV_VAR, str(home))
    report = tmp_path / "report.json"
    assert desktop.self_test(load_config(), report, dist) == 0
    result = json.loads(report.read_text("utf-8"))
    assert result["passed"] is True
    assert [r["check"] for r in result["results"]][:3] == ["health", "frontend", "header required"]
    assert not home.exists()
