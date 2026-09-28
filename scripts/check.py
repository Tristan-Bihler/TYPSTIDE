"""Run every lint, type check and test suite. Exits non-zero if any step fails.

Usage:  python scripts/check.py          lint, types, unit and API tests
        python scripts/check.py --e2e    also the Playwright UI tests (needs Chromium via
                                         `uv run --project backend playwright install chromium`
                                         and free ports 8000/5173, so stop dev.py first)
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    uv = shutil.which("uv")
    npm = shutil.which("npm")
    if uv is None or npm is None:
        sys.exit("Both 'uv' and 'npm' must be on PATH (see README.md).")

    backend = ["--project", str(ROOT / "backend")]
    mypy_config = str(ROOT / "backend" / "pyproject.toml")
    frontend = ROOT / "frontend"
    if not (frontend / "node_modules").is_dir():
        subprocess.run([npm, "ci"], cwd=frontend, check=True)

    steps: list[tuple[str, list[str], Path]] = [
        ("ruff check", [uv, "run", *backend, "ruff", "check", "."], ROOT),
        ("ruff format", [uv, "run", *backend, "ruff", "format", "--check", "."], ROOT),
        (
            "mypy --strict",
            [
                uv,
                "run",
                *backend,
                "mypy",
                "--config-file",
                mypy_config,
                "backend/src",
                "backend/tests",
                "scripts",
                "e2e",
            ],
            ROOT,
        ),
        ("pytest", [uv, "run", *backend, "pytest", "-q"], ROOT / "backend"),
        ("tsc", [npm, "run", "typecheck"], frontend),
        ("vitest", [npm, "test"], frontend),
    ]
    if "--e2e" in sys.argv[1:]:
        steps.append(("playwright", [uv, "run", *backend, "pytest", "-q", "e2e"], ROOT))

    failed: list[str] = []
    for name, cmd, cwd in steps:
        print(f"\n=== {name} ===", flush=True)
        if subprocess.run(cmd, cwd=cwd).returncode != 0:
            failed.append(name)

    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"All {len(steps)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
