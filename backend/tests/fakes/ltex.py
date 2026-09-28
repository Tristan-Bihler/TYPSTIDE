"""Fake LTeX+ language server for tests: speaks LSP over stdio like the real one.

Deterministic "rules": a few known misspellings per language and repeated words. Words in
the `ltex.dictionary` setting are accepted. Message shapes (no `version` in
publishDiagnostics, a `workspace/configuration` request before every check, one
"acceptSuggestions" code action per replacement) copy LTeX+ 18.7.0.

Environment:
  FAKE_LTEX_MODE  ok (default) | crash_on_check | garbage | huge | slow_check
  FAKE_LTEX_LOG   file that gets one line per received method
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

MODE = os.environ.get("FAKE_LTEX_MODE", "ok")
LOG = os.environ.get("FAKE_LTEX_LOG")

MISSPELLED = {
    "de-DE": {"Fehlr": ["Fehler"], "durchgefürt": ["durchgeführt", "durchgefüht"]},
    "en-US": {"teh": ["the"], "recieve": ["receive"]},
}
SPELLER = {"de-DE": "GERMAN_SPELLER_RULE", "en-US": "MORFOLOGIK_RULE_EN_US"}
REPEAT = re.compile(r"\b(\w+) \1\b")

stdin = sys.stdin.buffer
stdout = sys.stdout.buffer
documents: dict[str, str] = {}
settings: dict[str, Any] = {}
next_id = 1000
pending: list[dict[str, Any]] = []


def log(method: str) -> None:
    if LOG:
        with Path(LOG).open("a", encoding="utf-8") as f:
            f.write(method + "\n")


def send(message: dict[str, Any]) -> None:
    body = json.dumps(message).encode("utf-8")
    stdout.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    stdout.flush()


def receive() -> dict[str, Any] | None:
    if pending:
        return pending.pop(0)
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


def request_configuration(uri: str) -> None:
    """Like LTeX+: ask the client for the `ltex` settings before each check."""
    global next_id, settings
    next_id += 1
    request_id = next_id
    params = {"items": [{"scopeUri": uri, "section": "ltex"}]}
    send(
        {"jsonrpc": "2.0", "id": request_id, "method": "workspace/configuration", "params": params}
    )
    while True:
        message = receive()
        if message is None:
            sys.exit(0)
        if message.get("id") == request_id and "method" not in message:
            settings = message["result"][0] or {}
            return
        pending.append(message)


def position(text: str, offset: int) -> dict[str, int]:
    line = text.count("\n", 0, offset)
    start = text.rfind("\n", 0, offset) + 1
    return {"line": line, "character": len(text[start:offset].encode("utf-16-le")) // 2}


def matches(text: str) -> list[tuple[int, int, str, str, list[str]]]:
    language = settings.get("language", "de-DE")
    accepted = set(settings.get("dictionary", {}).get(language, []))
    found = []
    for word, replacements in MISSPELLED.get(language, {}).items():
        if word in accepted:
            continue
        for m in re.finditer(rf"\b{re.escape(word)}\b", text):
            message = f"'{word}': Possible spelling mistake."
            found.append((m.start(), m.end(), SPELLER[language], message, replacements))
    for m in REPEAT.finditer(text):
        rule = "GERMAN_WORD_REPEAT_RULE" if language == "de-DE" else "ENGLISH_WORD_REPEAT_RULE"
        message = "Possible typo: you repeated a word"
        found.append((m.start(), m.end(), rule, message, [m.group(1)]))
    return sorted(found)


def diagnostic(text: str, match: tuple[int, int, str, str, list[str]]) -> dict[str, Any]:
    start, end, rule, message, _ = match
    return {
        "range": {"start": position(text, start), "end": position(text, end)},
        "severity": 3,
        "code": rule,
        "source": "LTeX",
        "message": message,
    }


def check(uri: str) -> None:
    if MODE == "crash_on_check":
        sys.exit(3)
    request_configuration(uri)
    if MODE == "slow_check":
        time.sleep(5)
    if MODE == "garbage":
        stdout.write(b"Content-Length: 5\r\n\r\nnope!")
        stdout.flush()
        return
    if MODE == "huge":
        stdout.write(b"Content-Length: 999999999\r\n\r\n")
        stdout.flush()
        return
    text = documents[uri]
    diagnostics = [diagnostic(text, m) for m in matches(text)]
    params = {"uri": uri, "diagnostics": diagnostics}
    send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": params})


def code_actions(params: dict[str, Any]) -> list[dict[str, Any]]:
    uri = params["textDocument"]["uri"]
    text = documents[uri]
    wanted = params["range"]
    actions = []
    for m in matches(text):
        d = diagnostic(text, m)
        if d["range"] != wanted:
            continue
        for word in m[4]:
            edit = {"range": d["range"], "newText": word}
            actions.append(
                {
                    "title": f"Use '{word}'",
                    "kind": "quickfix.ltex.acceptSuggestions",
                    "diagnostics": [d],
                    "edit": {"documentChanges": [{"textDocument": {"uri": uri}, "edits": [edit]}]},
                }
            )
        actions.append(
            {
                "title": "Disable rule",
                "kind": "quickfix.ltex.disableRules",
                "diagnostics": [d],
                "command": {"title": "Disable rule", "command": "_ltex.disableRules"},
            }
        )
    return actions


def main() -> None:
    while True:
        message = receive()
        if message is None:
            return
        method = message.get("method", "")
        if method:
            log(method)
        params = message.get("params") or {}
        if method == "initialize":
            capabilities = {"textDocumentSync": 1, "codeActionProvider": True}
            send({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": capabilities}})
        elif method == "textDocument/didOpen":
            document = params["textDocument"]
            documents[document["uri"]] = document["text"]
            check(document["uri"])
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            documents[uri] = params["contentChanges"][-1]["text"]
            check(uri)
        elif method == "textDocument/didClose":
            documents.pop(params["textDocument"]["uri"], None)
        elif method == "textDocument/codeAction":
            send({"jsonrpc": "2.0", "id": message["id"], "result": code_actions(params)})
        elif method == "shutdown":
            send({"jsonrpc": "2.0", "id": message["id"], "result": None})
        elif method == "exit":
            return
        elif "id" in message and method:
            send({"jsonrpc": "2.0", "id": message["id"], "result": None})


if __name__ == "__main__":
    main()
