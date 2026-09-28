"""Phase 7: the backend serving the built frontend (Windows app) and the request header."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from typst_writer import config as config_module
from typst_writer.config import load_config
from typst_writer.main import create_app

from helpers import APP_HEADERS, FRONTEND_ORIGIN, WS_URL, receive_until

DESKTOP_ORIGIN = "http://127.0.0.1:47813"


def test_resources_come_from_the_bundle_when_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (config_module.resource_root() / "config.toml").is_file()  # the repository
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert config_module.resource_root() == tmp_path


def test_the_desktop_config_has_a_fixed_port() -> None:
    assert load_config().desktop.port == 47813


@pytest.fixture
def frontend(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>typst-writer</title>", "utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", "utf-8")
    return dist


@pytest.fixture
def desktop(frontend: Path) -> TestClient:
    app = create_app(load_config(), static_dir=frontend, origin=DESKTOP_ORIGIN)
    return TestClient(app, base_url="http://127.0.0.1", headers=APP_HEADERS)


def test_serves_the_built_frontend_next_to_the_api(desktop: TestClient) -> None:
    with desktop:
        page = desktop.get("/")
        assert page.status_code == 200
        assert "<title>typst-writer</title>" in page.text
        assert desktop.get("/assets/app.js").text == "console.log(1)"
        assert desktop.get("/api/health").json()["status"] == "ok"
        assert desktop.get("/api/nope").status_code == 404
        assert desktop.get("/../config.toml").status_code == 404


def test_the_window_origin_replaces_the_dev_server_origin(desktop: TestClient) -> None:
    with desktop:
        with desktop.websocket_connect(WS_URL, headers={"origin": DESKTOP_ORIGIN}) as ws:
            assert receive_until(ws, "workspace_changed")["type"] == "workspace_changed"
        foreign = desktop.websocket_connect(WS_URL, headers={"origin": FRONTEND_ORIGIN})
        with pytest.raises(WebSocketDisconnect), foreign as ws:
            ws.receive_json()


def test_changing_requests_need_the_app_header() -> None:
    with TestClient(create_app(load_config()), base_url="http://127.0.0.1") as bare:
        refused = bare.post("/api/completion/install")
        assert refused.status_code == 403
        assert refused.json()["code"] == "missing_header"
        assert bare.put("/api/settings/ui", json={"theme": "dark"}).status_code == 403
        assert bare.delete("/api/workspace/entry?path=x").status_code == 403
        assert bare.get("/api/settings/ui").status_code == 200  # reading needs nothing
        wrong = bare.post("/api/completion/install", headers={"X-Typst-Writer": "0"})
        assert wrong.status_code == 403
        allowed = bare.put("/api/settings/ui", json={"theme": "dark"}, headers=APP_HEADERS)
        assert allowed.status_code == 200


def test_only_the_app_origin_may_send_the_header() -> None:
    preflight = {"access-control-request-method": "POST"}
    preflight["access-control-request-headers"] = "x-typst-writer,content-type"
    with TestClient(create_app(load_config()), base_url="http://127.0.0.1") as bare:
        ours = bare.options(
            "/api/grammar/install", headers={**preflight, "origin": FRONTEND_ORIGIN}
        )
        assert ours.status_code == 200
        assert "x-typst-writer" in ours.headers["access-control-allow-headers"].lower()
        foreign = bare.options(
            "/api/grammar/install", headers={**preflight, "origin": "https://evil.example"}
        )
        assert foreign.status_code == 400
        assert "access-control-allow-origin" not in foreign.headers
