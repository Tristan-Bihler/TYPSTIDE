"""Download and install LTeX+ (spelling and grammar checks) ahead of time.

Usage:  python scripts/install_ltex.py

The app offers the same download from its status bar; running this beforehand is useful
before going offline. The version and checksums come from [ltex] in config.toml.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("'uv' not found on PATH. Install it first (see README.md).")
    module = "typst_writer.infra.ltex_install"
    command = [uv, "run", "--project", str(ROOT / "backend"), "python", "-m", module]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
