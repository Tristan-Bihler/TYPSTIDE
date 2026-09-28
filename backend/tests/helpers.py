"""Shared test helpers."""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.testclient import WebSocketTestSession

from typst_writer.config import DEFAULT_CONFIG_PATH

FRONTEND_ORIGIN = "http://127.0.0.1:5173"
WS_URL = "ws://127.0.0.1/ws"  # absolute: the test client would otherwise send Host: testserver


def receive_until(ws: WebSocketTestSession, message_type: str, limit: int = 20) -> dict[str, Any]:
    """Read WebSocket messages until one of `message_type` arrives."""
    for _ in range(limit):
        message: dict[str, Any] = ws.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"no {message_type} message within {limit} messages")


def receive_compile(ws: WebSocketTestSession) -> dict[str, dict[str, Any]]:
    """Collect messages of one compile cycle up to its final compile_status."""
    collected: dict[str, Any] = {}
    for _ in range(20):
        message = ws.receive_json()
        if message["type"] == "compile_status" and message["state"] == "compiling":
            continue
        collected[message["type"]] = message
        if message["type"] == "compile_status":
            return collected
    raise AssertionError("compile did not finish")


def receive_compile_until(
    ws: WebSocketTestSession,
    done: Callable[[dict[str, dict[str, Any]]], bool],
    limit: int = 10,
) -> dict[str, dict[str, Any]]:
    """Skip compile cycles queued by earlier changes until one satisfies `done`."""
    for _ in range(limit):
        cycle = receive_compile(ws)
        if done(cycle):
            return cycle
    raise AssertionError(f"no matching compile cycle within {limit} cycles")


FAKE_LTEX = Path(__file__).parent / "fakes" / "ltex.py"


def make_fake_ltex_install(home: Path) -> Path:
    """An LTeX+ folder whose `java` starts the fake language server (it ignores the Java
    arguments), so the app's real start-up path is exercised without Java."""
    (home / "lib").mkdir(parents=True)
    java = home / "jdk-21" / "bin" / "java"
    java.parent.mkdir(parents=True)
    run = f"runpy.run_path({str(FAKE_LTEX)!r}, run_name='__main__')"
    java.write_text(f"#!{sys.executable}\nimport runpy\n{run}\n", encoding="utf-8")
    java.chmod(0o755)
    return home


FAKE_TINYMIST = Path(__file__).parent / "fakes" / "tinymist.py"


def make_fake_tinymist(directory: Path) -> Path:
    """A `tinymist` program that runs the fake language server (ignores `lsp`)."""
    directory.mkdir(parents=True, exist_ok=True)
    program = directory / "tinymist"
    run = f"runpy.run_path({str(FAKE_TINYMIST)!r}, run_name='__main__')"
    program.write_text(f"#!{sys.executable}\nimport runpy\n{run}\n", encoding="utf-8")
    program.chmod(0o755)
    return program


def receive_suggestions(
    ws: WebSocketTestSession, path: str, source: str = "rule", limit: int = 40
) -> dict[str, Any]:
    """The next `suggestions` message for `path` from `source`."""
    for _ in range(limit):
        message: dict[str, Any] = ws.receive_json()
        if message["type"] == "suggestions" and (message["path"], message["source"]) == (
            path,
            source,
        ):
            return message
    raise AssertionError(f"no suggestions for {path} within {limit} messages")


def write_config(directory: Path, ollama_url: str) -> Path:
    """A copy of config.toml with the local AI pointed at `ollama_url`."""
    text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").replace(
        'base_url = "http://127.0.0.1:11434"', f'base_url = "{ollama_url}"'
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path
