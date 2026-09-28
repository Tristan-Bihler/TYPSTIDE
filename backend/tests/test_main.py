from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typst_writer.config import AppConfig, TypstConfig, load_config
from typst_writer.main import create_app

from helpers import FRONTEND_ORIGIN


def test_health_reports_pinned_typst_version(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "typst_version": "0.15.0"}


def test_cors_allows_only_local_frontend_origin(client: TestClient) -> None:
    allowed = client.get("/api/health", headers={"Origin": FRONTEND_ORIGIN})
    assert allowed.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN

    foreign = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in foreign.headers


def test_foreign_host_header_is_rejected(client: TestClient) -> None:
    """DNS rebinding: evil.example resolving to 127.0.0.1 must not reach the API."""
    response = client.get("/api/health", headers={"Host": "evil.example"})
    assert response.status_code == 400


def test_api_docs_are_disabled(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_version_mismatch_refuses_to_start() -> None:
    config = AppConfig(typst=TypstConfig(version="0.0.1"))
    with pytest.raises(RuntimeError, match=r"pins 0\.0\.1"):
        create_app(config)


def test_repo_config_file_is_valid() -> None:
    config = load_config()
    assert config.claude.models == []


def test_unknown_config_keys_are_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "config.toml"
    bad.write_text("[server]\nhost = '0.0.0.0'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="host"):
        load_config(bad)
