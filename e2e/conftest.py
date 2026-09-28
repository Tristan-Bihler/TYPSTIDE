"""Start backend + Vite for UI tests, with an isolated app home. Uses the ports from
config.toml, so stop `scripts/dev.py` before running these tests."""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:5173"
# Optional: a Chromium binary to use instead of Playwright's download.
CHROMIUM_ENV_VAR = "PLAYWRIGHT_CHROMIUM_EXECUTABLE"


def _port_busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def app_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    for port in (8000, 5173):
        if _port_busy(port):
            pytest.fail(f"Port {port} is in use. Stop `python scripts/dev.py` first.")
    node = shutil.which("node")
    if node is None:
        pytest.fail("node is not on PATH")
    # A fake `claude` first on PATH: UI tests never reach a real model.
    fake_bin = tmp_path_factory.mktemp("fake-bin")
    fake = ROOT / "backend" / "tests" / "fakes" / "claude.py"
    (fake_bin / "claude").write_text(
        f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(fake)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    (fake_bin / "claude").chmod(0o755)
    env = {
        **os.environ,
        "TYPST_WRITER_HOME": str(tmp_path_factory.mktemp("app-home")),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "typst_writer.main:app_factory", "--factory",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT / "backend", env=env,
    )  # fmt: skip
    vite = str(ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js")
    frontend = subprocess.Popen([node, vite, "--port", "5173"], cwd=ROOT / "frontend", env=env)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=1) as r:  # noqa: S310
                    if r.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("servers did not start within 30 s")
            time.sleep(0.2)
        yield BASE_URL
    finally:
        for process in (frontend, backend):
            process.terminate()
            process.wait(timeout=10)


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Iterator[Browser]:
    executable = os.environ.get(CHROMIUM_ENV_VAR)
    browser = playwright.chromium.launch(headless=True, executable_path=executable or None)
    yield browser
    browser.close()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "Bachelorarbeit"
    (root / "kapitel").mkdir(parents=True)
    (root / "main.typ").write_text(
        '#set page(numbering: "1")\n= Bachelorarbeit\n#include "kapitel/01-einleitung.typ"\n',
        encoding="utf-8",
    )
    (root / "kapitel" / "01-einleitung.typ").write_text(
        "== Einleitung\n\nDieses Kapitel beschreibt die Arbeit.\n", encoding="utf-8"
    )
    (root / "bilder").mkdir()
    (root / "bilder" / "aufbau.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
        '<rect width="40" height="20" fill="teal"/></svg>',
        encoding="utf-8",
    )
    (root / "quellen.bib").write_text(
        "@article{knuth1984,\n  title = {Literate Programming},\n  year = {1984},\n}\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def page(browser: Browser, app_url: str, workspace: Path) -> Iterator[Page]:
    """A fresh page with `workspace` opened through the Open folder dialog."""
    context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # Every test starts with both AI slots set to None (settings persist in the session).
    context.request.put(
        f"{app_url}/api/ai/settings", data={"local_model": None, "claude_model": None}
    )
    page.goto(app_url)
    page.get_by_role("button", name="Open folder", exact=True).first.click()
    picker = page.locator(".folder-picker")
    path_input = picker.get_by_label("Folder path")
    expect(path_input).not_to_have_value("")  # wait for the initial listing, like a user would
    path_input.fill(str(workspace))
    picker.get_by_role("button", name="Go").click()
    picker.get_by_role("option", name="kapitel").wait_for()
    picker.get_by_role("button", name="Open this folder").click()
    page.locator(".page img").first.wait_for()
    yield page
    context.close()
    assert errors == [], f"uncaught errors in the page: {errors}"
