"""Start backend (uvicorn, auto-reload) and frontend (Vite) together.

Usage:  python scripts/dev.py      (stops both on Ctrl+C or when either exits)
"""

import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"


def require(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        sys.exit(f"'{tool}' not found on PATH. Install it first (see README.md).")
    return path


def main() -> int:
    with (ROOT / "config.toml").open("rb") as f:
        config = tomllib.load(f)
    backend_port = int(config["server"]["backend_port"])
    frontend_port = int(config["server"]["frontend_port"])
    ws_max_size = int(config["limits"]["max_ws_message_bytes"])

    uv = require("uv")
    npm = require("npm")
    node = require("node")
    frontend = ROOT / "frontend"

    if not (frontend / "node_modules").is_dir():
        subprocess.run([npm, "ci"], cwd=frontend, check=True)

    backend_cmd = [
        uv,
        "run",
        "--project",
        str(ROOT / "backend"),
        "uvicorn",
        "typst_writer.main:app_factory",
        "--factory",
        "--host",
        HOST,
        "--port",
        str(backend_port),
        "--ws-max-size",
        str(ws_max_size),
        "--reload",
        "--reload-dir",
        str(ROOT / "backend" / "src"),
    ]
    # Run Vite through node directly: stopping an `npm run` wrapper would orphan Vite.
    vite = str(frontend / "node_modules" / "vite" / "bin" / "vite.js")
    frontend_cmd = [node, vite, "--port", str(frontend_port)]

    processes = [
        subprocess.Popen(backend_cmd, cwd=ROOT),
        subprocess.Popen(frontend_cmd, cwd=frontend),
    ]
    print(f"\n  typst-writer: http://{HOST}:{frontend_port}\n", flush=True)

    exit_code = 0
    try:
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
        exit_code = next(p.returncode for p in processes if p.returncode is not None)
    except KeyboardInterrupt:
        pass
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
