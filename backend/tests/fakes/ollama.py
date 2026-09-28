"""Fake Ollama HTTP server for tests: GET /api/tags and POST /api/chat.

Deterministic "model" (fake-model:1b): it proposes
- "weil er hat keine Zeit" -> "weil er keine Zeit hat" (grammar),
- "die Ergebnis" -> "das Ergebnis",
- for a paragraph containing "MARKUP", a change that would delete a reference (must be
  dropped by the app's markup check).
Every checked paragraph is recorded, so tests can count what was (not) sent.

Run standalone (e2e): python ollama.py PORT [LOG_FILE]; FAKE_OLLAMA_DELAY adds seconds per chat.
"""

import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MODEL = "fake-model:1b"
_RULES = [
    ("weil er hat keine Zeit", "weil er keine Zeit hat", "Im Nebensatz steht das Verb am Ende."),
    ("die Ergebnis", "das Ergebnis", "„Ergebnis“ ist sächlich."),
    ("ein Fehlr", "ein Fehler", "Tippfehler."),  # overlaps the fake LTeX+ finding
]


def propose(paragraph: str) -> list[dict[str, str]]:
    changes = [
        {"original": o, "replacement": r, "reason": why, "category": "grammar"}
        for o, r, why in _RULES
        if o in paragraph
    ]
    if "MARKUP" in paragraph and (ref := re.search(r"in @[\w:]+", paragraph)):
        changes.append(
            {"original": ref.group(), "replacement": "hier", "reason": "x", "category": "style"}
        )
    return changes


class FakeOllama:
    def __init__(self, port: int = 0, log: Path | None = None) -> None:
        self.paragraphs: list[str] = []
        self.delay = float(os.environ.get("FAKE_OLLAMA_DELAY", "0"))
        self.log = log
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # noqa: ANN401 - quiet
                pass

            def _json(self, status: int, body: object) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path == "/api/tags":
                    self._json(200, {"models": [{"name": MODEL}]})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path != "/api/chat" or body.get("model") != MODEL:
                    self._json(404, {"error": "model not found"})
                    return
                user = body["messages"][-1]["content"]
                match = re.search(r"<paragraph>\n(.*)\n</paragraph>", user, re.DOTALL)
                paragraph = match.group(1) if match else ""
                fake.paragraphs.append(paragraph)
                if fake.log is not None:
                    with fake.log.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(paragraph) + "\n")
                time.sleep(fake.delay)
                answer = {"explanation": "", "changes": propose(paragraph)}
                message = {"role": "assistant", "content": json.dumps(answer)}
                self._json(200, {"model": MODEL, "message": message, "done": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> "FakeOllama":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


if __name__ == "__main__":
    log_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    FakeOllama(int(sys.argv[1]), log_file).server.serve_forever()
