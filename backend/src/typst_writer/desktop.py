"""The Windows app: the backend on 127.0.0.1 plus a native window (pywebview, Edge WebView2).

The backend serves the built frontend itself on a fixed port (`[desktop] port`), so the
window's origin, and the layout it keeps in local storage, stay the same between starts.
Only one instance runs at a time. The page reaches Python only through `DesktopApi`
(native folder and save dialogs, and whether closing needs a confirmation).

`--self-test` starts the server without a window, exercises the main API paths (on a
sample project in a temporary app home) and reports the result; the Windows build runs it.
"""

import argparse
import base64
import binascii
import json
import logging
import logging.handlers
import os
import re
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import httpx
import uvicorn
from fastapi import FastAPI

from typst_writer.config import FRONTEND_DIST, RESOURCE_ROOT, AppConfig, load_config
from typst_writer.infra.app_dirs import HOME_ENV_VAR, cache_dir, config_dir

APP_NAME = "typst-writer"
MAX_PDF_BYTES = 200_000_000
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
ICON = RESOURCE_ROOT / "packaging" / "typst-writer.ico"
START_TIMEOUT_S = 20.0

log = logging.getLogger(__name__)

AskFolder = Callable[[str], str | None]
AskSave = Callable[[str], str | None]


# --- the page's bridge to Python -------------------------------------------------------


class DesktopApi:
    """Exposed to the page as `window.pywebview.api` (public methods only). Arguments come
    from the page and are checked; files are only written where the user chose in the
    native Save dialog."""

    def __init__(
        self, ask_folder: AskFolder, ask_save: AskSave, confirm_close: Callable[[bool], None]
    ) -> None:
        self._ask_folder = ask_folder
        self._ask_save = ask_save
        self._confirm_close = confirm_close

    def pick_folder(self, start: object = None) -> str | None:
        """The native folder dialog; the chosen folder, or None if cancelled."""
        return self._ask_folder(start if isinstance(start, str) else "")

    def save_pdf(self, filename: object, data: object) -> str | None:
        """Ask where to save the exported PDF (base64 `data`) and write it there."""
        if not isinstance(filename, str) or not isinstance(data, str):
            raise ValueError("expected a file name and base64 data")
        if len(data) > MAX_PDF_BYTES * 4 // 3 + 4:
            raise ValueError("the PDF is too large")
        try:
            pdf = base64.b64decode(data, validate=True)
        except binascii.Error as exc:
            raise ValueError("the PDF data is not base64") from exc
        if not pdf.startswith(b"%PDF-"):
            raise ValueError("the data is not a PDF")
        name = Path(filename.replace("\\", "/")).name or "document.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        chosen = self._ask_save(name)
        if not chosen:
            return None
        target = Path(chosen)
        if target.suffix.lower() != ".pdf":
            target = target.with_name(target.name + ".pdf")
        target.write_bytes(pdf)
        return str(target)

    def set_unsaved(self, unsaved: object) -> None:
        """Whether closing the window should ask first (open files have unsaved changes)."""
        self._confirm_close(unsaved is True)


# --- server ------------------------------------------------------------------------------


class BackgroundServer:
    """uvicorn in a background thread; the window runs on the main thread."""

    def __init__(self, app: FastAPI, port: int, max_ws_bytes: int) -> None:
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            ws_max_size=max_ws_bytes,
            log_config=None,  # logging goes to the app's log file (no console)
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="server", daemon=True)

    def start(self, timeout: float = START_TIMEOUT_S) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the server did not start")
            time.sleep(0.05)

    def stop(self, timeout: float = 15.0) -> None:
        """Stop and wait; the app's shutdown also stops LTeX+ and Tinymist."""
        self._server.should_exit = True
        self._thread.join(timeout)


def create_desktop_app(config: AppConfig, port: int, static_dir: Path) -> FastAPI:
    from typst_writer.main import HOST, create_app

    return create_app(config, static_dir=static_dir, origin=f"http://{HOST}:{port}")


PortOwner = Literal["free", "typst-writer", "other"]


def port_owner(port: int) -> PortOwner:
    """Who holds `port` on 127.0.0.1: nobody, another typst-writer, or another program."""
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            pass
        else:
            return "free"
    try:
        answer = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2.0, trust_env=False)
        body = answer.json()
    except (httpx.HTTPError, ValueError):
        return "other"
    ours = isinstance(body, dict) and body.get("status") == "ok" and "typst_version" in body
    return "typst-writer" if ours else "other"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
    return port


# --- messages and logging --------------------------------------------------------------


def log_file() -> Path:
    return cache_dir() / "logs" / "typst-writer.log"


def setup_logging() -> None:
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def show_message(title: str, text: str) -> None:
    """A message box on Windows (the app has no console), stderr elsewhere."""
    log.info("%s: %s", title, text)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)  # MB_ICONINFORMATION
    else:
        print(f"{title}: {text}", file=sys.stderr)


# --- the window --------------------------------------------------------------------------


def _first(result: object) -> str | None:
    if isinstance(result, str):
        return result or None
    if isinstance(result, (list, tuple)) and result and isinstance(result[0], str):
        return result[0]
    return None


def open_window(url: str) -> None:
    """Show the app in a native window; returns when the window is closed."""
    import webview  # type: ignore[import-not-found,unused-ignore]

    webview.settings["ALLOW_DOWNLOADS"] = False  # PDFs are saved through DesktopApi
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    windows: list[Any] = []

    def ask_folder(start: str) -> str | None:
        return _first(windows[0].create_file_dialog(webview.FileDialog.FOLDER, directory=start))

    def ask_save(name: str) -> str | None:
        dialog = windows[0].create_file_dialog(
            webview.FileDialog.SAVE, save_filename=name, file_types=("PDF (*.pdf)",)
        )
        return _first(dialog)

    def confirm_close(unsaved: bool) -> None:
        windows[0].confirm_close = unsaved  # pywebview asks before closing while this is set

    window = webview.create_window(
        APP_NAME,
        url,
        js_api=DesktopApi(ask_folder, ask_save, confirm_close),
        width=1440,
        height=900,
        min_size=(1000, 640),
        confirm_close=False,
    )
    windows.append(window)
    webview.start(
        gui="edgechromium",
        private_mode=False,  # keep the layout the page remembers in local storage
        storage_path=str(config_dir() / "webview"),
        icon=str(ICON) if ICON.is_file() else None,
        localization={
            "global.quitConfirmation": "Some files have unsaved changes. Close without saving?"
        },
    )


def run_app(config: AppConfig, static_dir: Path = FRONTEND_DIST) -> int:
    port = config.desktop.port
    owner = port_owner(port)
    if owner == "typst-writer":
        show_message(APP_NAME, "typst-writer is already running.")
        return 0
    if owner == "other":
        show_message(
            APP_NAME,
            f"Another program uses port {port}. Close it, or change [desktop] port in "
            f"{RESOURCE_ROOT / 'config.toml'}.",
        )
        return 1
    if not (static_dir / "index.html").is_file():
        show_message(APP_NAME, f"The user interface is missing ({static_dir}).")
        return 1
    server = BackgroundServer(
        create_desktop_app(config, port, static_dir), port, config.limits.max_ws_message_bytes
    )
    server.start()
    try:
        open_window(f"http://127.0.0.1:{port}/")
    except Exception:
        log.exception("the window could not be opened")
        show_message(
            APP_NAME,
            "The window could not be opened. typst-writer needs the Microsoft Edge WebView2 "
            f"runtime: {WEBVIEW2_URL}\n\nDetails: {log_file()}",
        )
        return 1
    finally:
        server.stop()
    return 0


# --- self-test (CI) ----------------------------------------------------------------------

SAMPLE_MAIN = (
    '#set page(numbering: "1")\n#set heading(numbering: "1.")\n'
    "= Übersicht <sec:start>\n\nSiehe @sec:kapitel.\n\n"
    '#include "kapitel/eins.typ"\n'
)
SAMPLE_CHAPTER = "== Kapitel <sec:kapitel>\n\nÄußerst kurzer Text.\n"


class SelfTestError(Exception):
    pass


def _expect(condition: object, detail: object = "") -> None:
    if not condition:
        raise SelfTestError(str(detail))


def _check_live(origin: str) -> str:
    from websockets.sync.client import connect
    from websockets.typing import Origin

    url = origin.replace("http://", "ws://") + "/ws"
    seen: set[str] = set()
    with connect(url, origin=Origin(origin), open_timeout=10) as ws:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            message = json.loads(ws.recv(timeout=30))
            seen.add(message["type"])
            status = message.get("state") if message["type"] == "compile_status" else None
            if status == "ok" and "preview_pages" in seen:
                return "compiled and previewed"
            _expect(status != "error", "the sample did not compile")
    raise SelfTestError(f"no preview; saw {sorted(seen)}")


def _checks(
    http: httpx.Client, origin: str, project: Path, config: AppConfig
) -> list[tuple[str, Callable[[], str]]]:
    def health() -> str:
        body = http.get("/api/health").json()
        _expect(body["typst_version"] == config.typst.version, body)
        return f"Typst {body['typst_version']}"

    def frontend() -> str:
        page = http.get("/").text
        scripts = re.findall(r'src="(/assets/[^"]+\.js)"', page)
        _expect(scripts, "index.html references no script")
        _expect(http.get(scripts[0]).status_code == 200)
        return f"{len(page)} bytes, {scripts[0]}"

    def header_required() -> str:
        refused = http.post("/api/completion/install", headers={"X-Typst-Writer": "0"})
        _expect(refused.status_code == 403, refused.status_code)
        return "changes without the header are refused"

    def workspace() -> str:
        info = http.post("/api/workspace/open", json={"path": str(project)}).json()
        _expect(info.get("main") == "main.typ", info)
        tree = json.dumps(http.get("/api/workspace/tree").json())
        _expect("eins.typ" in tree, tree)
        text = http.get("/api/workspace/file", params={"path": "kapitel/eins.typ"}).json()
        _expect(text["content"] == SAMPLE_CHAPTER)
        saved = SAMPLE_CHAPTER + "\nNoch ein Satz.\n"
        body = {"path": "kapitel/eins.typ", "content": saved}
        _expect(http.put("/api/workspace/file", json=body).status_code == 200)
        on_disk = (project / "kapitel" / "eins.typ").read_text("utf-8")
        _expect(on_disk == saved)
        return str(project)

    def export() -> str:
        pdf = http.post("/api/export/pdf", json={"overlays": {}})
        _expect(pdf.status_code == 200 and pdf.content.startswith(b"%PDF-"), pdf.status_code)
        return f"{len(pdf.content)} bytes"

    def statuses() -> str:
        snippets = http.get("/api/snippets").json()
        grammar = http.get("/api/grammar").json()["status"]["state"]
        completion = http.get("/api/completion").json()["state"]
        claude = http.get("/api/ai/status").json()  # starts `claude` (a child process)
        _expect(snippets and grammar and completion and "claude" in json.dumps(claude))
        return f"{len(snippets)} snippets, LTeX+ {grammar}, Tinymist {completion}"

    def fonts() -> str:
        options = http.get("/api/format/options").json()  # reads the installed fonts
        families = {f["family"]: f["builtin"] for f in options["fonts"]}
        _expect(families.get("Libertinus Serif") is True, "built-in fonts missing")
        installed = sum(1 for builtin in families.values() if not builtin)
        body = {
            "content": "Ein Wort.",
            "start": 4,
            "end": 8,
            "change": {"kind": "size", "value": "14"},
        }
        edit = http.post("/api/format/apply", json=body).json()
        _expect(edit.get("insert") == "#text(size: 14pt)[Wort]", edit)
        return f"{len(families) - installed} built-in, {installed} installed fonts"

    return [
        ("health", health),
        ("frontend", frontend),
        ("header required", header_required),
        ("workspace", workspace),
        ("live preview", lambda: _check_live(origin)),
        ("pdf export", export),
        ("statuses", statuses),
        ("fonts", fonts),
    ]


def self_test(config: AppConfig, report: Path | None, static_dir: Path = FRONTEND_DIST) -> int:
    results: list[dict[str, str | bool]] = []
    with tempfile.TemporaryDirectory(prefix="typst-writer-self-test-") as tmp:
        os.environ[HOME_ENV_VAR] = str(Path(tmp) / "home")  # never touch the user's settings
        project = Path(tmp) / "Projekt Ü"  # spaces and umlauts in the path
        (project / "kapitel").mkdir(parents=True)
        (project / "main.typ").write_text(SAMPLE_MAIN, encoding="utf-8")
        (project / "kapitel" / "eins.typ").write_text(SAMPLE_CHAPTER, encoding="utf-8")
        port = free_port()
        origin = f"http://127.0.0.1:{port}"
        server = BackgroundServer(
            create_desktop_app(config, port, static_dir), port, config.limits.max_ws_message_bytes
        )
        server.start()
        try:
            headers = {"X-Typst-Writer": "1", "Origin": origin}
            with httpx.Client(
                base_url=origin, headers=headers, timeout=60.0, trust_env=False
            ) as http:
                for name, check in _checks(http, origin, project, config):
                    try:
                        results.append({"check": name, "ok": True, "detail": check()})
                    except Exception as exc:  # report every failing check, not just the first
                        log.exception("self-test %s failed", name)
                        results.append({"check": name, "ok": False, "detail": repr(exc)})
        finally:
            server.stop()
    passed = all(r["ok"] for r in results)
    text = json.dumps({"passed": passed, "results": results}, indent=2, ensure_ascii=False)
    if report is not None:
        report.write_text(text, encoding="utf-8")
    if sys.stdout is not None:
        print(text)
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--self-test", action="store_true", help="check the app without a window")
    parser.add_argument("--report", type=Path, help="write the self-test result (JSON) here")
    args = parser.parse_args(argv)
    setup_logging()
    config = load_config()
    if args.self_test:
        return self_test(config, args.report)
    return run_app(config)


if __name__ == "__main__":
    sys.exit(main())
