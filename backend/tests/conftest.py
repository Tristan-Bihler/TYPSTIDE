import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typst_writer.config import load_config
from typst_writer.infra.app_dirs import HOME_ENV_VAR
from typst_writer.main import create_app


@pytest.fixture(autouse=True)
def isolated_app_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep state and caches of every test out of the real user directories."""
    home = tmp_path / "app-home"
    monkeypatch.setenv(HOME_ENV_VAR, str(home))
    return home


FAKE_CLAUDE = Path(__file__).parent / "fakes" / "claude.py"


@pytest.fixture(autouse=True)
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a fake `claude` first on PATH in every test, so no test can reach a real model.

    Returns the log file the fake appends one JSON record per invocation to.
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "claude"
    run = f"runpy.run_path({str(FAKE_CLAUDE)!r}, run_name='__main__')"
    wrapper.write_text(f"#!{sys.executable}\nimport runpy\n{run}\n", encoding="utf-8")
    wrapper.chmod(0o755)
    log = tmp_path / "fake-claude.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    return log


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "thesis"
    (root / "chapters").mkdir(parents=True)
    (root / "images").mkdir()
    (root / ".git").mkdir()
    (root / "main.typ").write_text('= Thesis\n#include "chapters/intro.typ"\n', encoding="utf-8")
    (root / "chapters" / "intro.typ").write_text("== Einleitung\nText.\n", encoding="utf-8")
    (root / "refs.bib").write_text("", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    return root


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(load_config()), base_url="http://127.0.0.1") as c:
        yield c


@pytest.fixture
def opened(client: TestClient, workspace: Path) -> TestClient:
    response = client.post("/api/workspace/open", json={"path": str(workspace)})
    assert response.status_code == 200, response.text
    return client
