"""Phase 7 in the browser: the backend serving the built frontend like the Windows app does,
with pywebview's bridge simulated (native folder and Save dialogs, close confirmation)."""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from e2e.conftest import ROOT, _free_port
from e2e.ui_helpers import expand_folder

SERVE = """
import sys, uvicorn
from pathlib import Path
from typst_writer.config import FRONTEND_DIST, load_config
from typst_writer.desktop import create_desktop_app
port = int(sys.argv[1])
uvicorn.run(create_desktop_app(load_config(), port, FRONTEND_DIST), host="127.0.0.1", port=port)
"""


@pytest.fixture(scope="module")
def desktop_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    npm = shutil.which("npm")
    if npm is None:
        pytest.fail("npm is not on PATH")
    subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True, capture_output=True)
    port = _free_port()
    env = {**os.environ, "TYPST_WRITER_HOME": str(tmp_path_factory.mktemp("desktop-home"))}
    env.pop("TYPST_WRITER_TINYMIST", None)
    server = subprocess.Popen(
        [sys.executable, "-c", SERVE, str(port)], cwd=ROOT / "backend", env=env
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(f"{url}/api/health", timeout=1) as r:  # noqa: S310
                    if r.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("the desktop-mode server did not start")
            time.sleep(0.2)
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)


def fake_pywebview(folder: Path) -> str:
    """What pywebview injects into the page, with dialogs that answer at once."""
    chosen = json.dumps(str(folder))
    return f"""
    window.__calls = [];
    window.pywebview = {{ api: {{
      pick_folder: async (start) => (window.__calls.push(["pick_folder", start]), {chosen}),
      save_pdf: async (name, data) => (window.__calls.push(["save_pdf", name, data.slice(0, 8)]),
        "C:\\\\Users\\\\me\\\\Documents\\\\" + name),
      set_unsaved: async (value) => (window.__calls.push(["set_unsaved", value]), undefined),
    }} }};
    window.addEventListener("DOMContentLoaded", () =>
      setTimeout(() => window.dispatchEvent(new Event("pywebviewready")), 50));
    """


@pytest.fixture
def app_page(browser: Browser, desktop_url: str, workspace: Path) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_init_script(fake_pywebview(workspace))
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(desktop_url)
    yield page
    context.close()
    assert errors == [], f"uncaught errors in the page: {errors}"


def calls(page: Page, name: str) -> list[list[object]]:
    found: list[list[object]] = page.evaluate(f"window.__calls.filter(c => c[0] === '{name}')")
    return found


def test_the_app_works_from_the_built_frontend_with_native_dialogs(app_page: Page) -> None:
    page = app_page
    page.wait_for_function("window.__calls !== undefined")
    page.wait_for_timeout(200)  # the bridge is found after pywebviewready
    page.get_by_role("button", name="Open folder", exact=True).first.click()
    expect(page.locator(".folder-picker")).to_have_count(0)  # the native dialog answered
    page.locator(".page img").first.wait_for()
    assert calls(page, "pick_folder") == [["pick_folder", ""]]

    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" Neu.")
    expect(page.locator(".tab.dirty")).to_have_count(1)
    page.keyboard.press("Control+s")
    expect(page.locator(".tab.dirty")).to_have_count(0)
    assert [c[1] for c in calls(page, "set_unsaved")] == [False, True, False]

    page.get_by_role("button", name="Export PDF").first.click()
    expect(page.locator(".save-notice")).to_have_text("Exported to main.pdf")
    [[_, name, head]] = calls(page, "save_pdf")
    assert name == "main.pdf"
    assert head == "JVBERi0x"  # base64 of "%PDF-1"


def test_changes_without_the_app_header_are_refused(desktop_url: str) -> None:
    url = f"{desktop_url}/api/completion/install"
    request = urllib.request.Request(url, method="POST")  # noqa: S310 - http on 127.0.0.1
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)  # noqa: S310
    assert refused.value.code == 403
