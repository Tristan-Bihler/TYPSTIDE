"""Fake Tinymist language server for tests: answers completion requests over stdio.

Message shapes copy Tinymist 0.15.8: a `client/registerCapability` request after
`initialized`, `tinymist.pinMain` via workspace/executeCommand, `tinymist/compileStatus`
after every change, completion items with a `textEdit` over the typed word, snippets with
insertTextFormat 2, labels listed after `@` (all of them; the editor filters). Labels come
from the pinned main file and the files it includes, read from disk, with open documents
taking precedence.

Environment:
  FAKE_TINYMIST_MODE  ok (default) | crash_on_complete
  FAKE_TINYMIST_LOG   file that gets one JSON line per received message (method, params)
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

MODE = os.environ.get("FAKE_TINYMIST_MODE", "ok")
LOG = os.environ.get("FAKE_TINYMIST_LOG")
FUNCTIONS = {
    "figure": "figure(${1:body})",
    "footnote": "footnote[${1:}]",
    "table": "table(${1:})",
    "text": "text",
}
LABEL = re.compile(r"<([\w:.-]+)>")
INCLUDE = re.compile(r'#include\s+"([^"]+)"')

stdin = sys.stdin.buffer
stdout = sys.stdout.buffer
documents: dict[str, str] = {}
main_file: Path | None = None


def log(message: dict[str, Any]) -> None:
    if LOG:
        with Path(LOG).open("a", encoding="utf-8") as f:
            entry = {"method": message.get("method"), "params": message.get("params")}
            f.write(json.dumps(entry) + "\n")


def send(message: dict[str, Any]) -> None:
    body = json.dumps(message).encode("utf-8")
    stdout.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    stdout.flush()


def receive() -> dict[str, Any] | None:
    length = 0
    while True:
        line = stdin.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1])
    message: dict[str, Any] = json.loads(stdin.read(length))
    return message


def compiled() -> None:
    """Like Tinymist with compileStatus enabled: report a compile of the main file."""
    for status in ("compiling", "compileSuccess"):
        params = {"path": "/main.typ", "status": status, "pageCount": 1}
        send({"jsonrpc": "2.0", "method": "tinymist/compileStatus", "params": params})


def path_of(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


def read(path: Path) -> str:
    return documents.get(path.as_uri()) or (path.read_text("utf-8") if path.is_file() else "")


def labels() -> list[str]:
    found: list[str] = []
    todo = [main_file] if main_file is not None else []
    seen: set[Path] = set()
    while todo:
        path = todo.pop(0)
        if path in seen:
            continue
        seen.add(path)
        text = read(path)
        found.extend(m.group(1) for m in LABEL.finditer(text))
        todo.extend((path.parent / m.group(1)) for m in INCLUDE.finditer(text))
    return found


def offset_of(text: str, position: dict[str, int]) -> int:
    lines = text.split("\n")
    start = sum(len(line) + 1 for line in lines[: position["line"]])
    return start + position["character"]  # tests use ASCII only


def position_of(text: str, offset: int) -> dict[str, int]:
    line = text.count("\n", 0, offset)
    return {"line": line, "character": offset - (text.rfind("\n", 0, offset) + 1)}


def complete(params: dict[str, Any]) -> dict[str, Any]:
    if MODE == "crash_on_complete":
        sys.exit(3)
    text = documents.get(params["textDocument"]["uri"], "")
    cursor = offset_of(text, params["position"])
    before = text[:cursor]
    items: list[dict[str, Any]] = []
    if m := re.search(r"#(\w*)$", before):
        edit_range = {"start": position_of(text, m.start(1)), "end": params["position"]}
        for i, (name, snippet) in enumerate(FUNCTIONS.items()):
            if not name.startswith(m.group(1)):
                continue
            items.append(
                {
                    "label": name,
                    "kind": 3,
                    "labelDetails": {"description": f"(..) => {name}"},
                    "detail": f"The {name} function.\n\nLong documentation.",
                    "insertTextFormat": 2,
                    "sortText": f"{i:03}",
                    "textEdit": {"newText": snippet, "range": edit_range},
                }
            )
    elif m := re.search(r"@([\w:.-]*)$", before):
        edit_range = {"start": position_of(text, m.start(1)), "end": params["position"]}
        for i, label in enumerate(labels()):
            items.append(
                {
                    "label": label,
                    "kind": 18,
                    "sortText": f"{i:03}",
                    "textEdit": {"newText": label, "range": edit_range},
                }
            )
    return {"isIncomplete": False, "items": items}


def main() -> None:
    global main_file
    next_id = 5000
    while True:
        message = receive()
        if message is None:
            return
        log(message)
        method = message.get("method", "")
        params = message.get("params") or {}
        if method == "initialize":
            result = {"capabilities": {"completionProvider": {"triggerCharacters": ["#", "@"]}}}
            send({"jsonrpc": "2.0", "id": message["id"], "result": result})
        elif method == "initialized":
            next_id += 1
            registration = {
                "registrations": [{"id": "x", "method": "workspace/didChangeConfiguration"}]
            }
            send(
                {
                    "jsonrpc": "2.0",
                    "id": next_id,
                    "method": "client/registerCapability",
                    "params": registration,
                }
            )
        elif method == "workspace/executeCommand":
            if params.get("command") == "tinymist.pinMain":
                target = params.get("arguments", [None])[0]
                main_file = Path(target) if target else None
            send({"jsonrpc": "2.0", "id": message["id"], "result": None})
            compiled()
        elif method == "textDocument/didOpen":
            document = params["textDocument"]
            documents[document["uri"]] = document["text"]
            compiled()
        elif method == "textDocument/didChange":
            documents[params["textDocument"]["uri"]] = params["contentChanges"][-1]["text"]
            compiled()
        elif method == "textDocument/completion":
            send({"jsonrpc": "2.0", "id": message["id"], "result": complete(params)})
        elif method == "shutdown":
            send({"jsonrpc": "2.0", "id": message["id"], "result": None})
        elif method == "exit":
            return
        elif "id" in message and "method" in message:
            send({"jsonrpc": "2.0", "id": message["id"], "result": None})


if __name__ == "__main__":
    main()
