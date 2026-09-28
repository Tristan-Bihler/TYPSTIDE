"""Stand-in for the `claude` CLI in tests (never calls a model).

Behaviour via environment variables:
  FAKE_CLAUDE_LOG      file to append {"argv", "stdin", "cwd", "env_keys"} records to
  FAKE_CLAUDE_MODE     ok (default) | logged_out | is_error | garbage | exit | slow | bad_schema
  FAKE_CLAUDE_OUTPUT   JSON for structured_output in "ok" mode
"""

import json
import os
import sys
import time
from pathlib import Path

argv = sys.argv[1:]
stdin = "" if argv[:2] == ["auth", "status"] else sys.stdin.read()
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")

log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with Path(log).open("a", encoding="utf-8") as f:
        record = {
            "argv": argv,
            "stdin": stdin,
            "cwd": str(Path.cwd()),
            "env_keys": sorted(os.environ),
        }
        f.write(json.dumps(record) + "\n")

if argv[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": mode != "logged_out", "authMethod": "oauth_token"}))
    sys.exit(0)

if mode == "slow":
    time.sleep(30)
if mode == "garbage":
    print("this is not json")
    sys.exit(0)
if mode == "exit":
    print("Error: something broke", file=sys.stderr)
    sys.exit(3)

default_output = {
    "explanation": "",
    "changes": [
        {
            "original": "Fehlr",
            "replacement": "Fehler",
            "reason": "Rechtschreibung",
            "category": "spelling",
        },
        {
            "original": "sehr sehr",
            "replacement": "sehr",
            "reason": "Doppelung",
            "category": "style",
        },
    ],
}
structured = json.loads(os.environ.get("FAKE_CLAUDE_OUTPUT", "null")) or default_output
if mode == "bad_schema":
    structured = {"changes": "not a list"}
envelope = {
    "type": "result",
    "subtype": "success",
    "is_error": mode == "is_error",
    "result": "Usage limit reached" if mode == "is_error" else json.dumps(structured),
    "structured_output": structured,
}
print(json.dumps(envelope))
