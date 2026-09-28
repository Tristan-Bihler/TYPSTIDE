"""Build the Windows app and its installer (Windows only).

Usage:  python scripts/build_windows.py

Needs uv, Node.js 22+ with npm, and Inno Setup 6 (https://jrsoftware.org/isinfo.php).
Steps: build the frontend, bundle the backend with PyInstaller (one folder, no console),
pack it with Inno Setup. Result: dist/typst-writer-setup.exe. GitHub Actions runs the same
script (.github/workflows/windows.yml).
"""

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "pyinstaller"
DIST = ROOT / "dist"
ISCC_DEFAULT = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
ISCC_DEFAULT = ISCC_DEFAULT / "Inno Setup 6" / "ISCC.exe"


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        sys.exit(f"'{name}' not found on PATH.")
    return found


def main() -> int:
    if sys.platform != "win32":
        sys.exit("The Windows app can only be built on Windows.")
    uv, npm = tool("uv"), tool("npm")
    iscc = shutil.which("iscc") or (str(ISCC_DEFAULT) if ISCC_DEFAULT.is_file() else None)
    if iscc is None:
        sys.exit("Inno Setup 6 (ISCC.exe) not found; install it from jrsoftware.org.")
    project = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text("utf-8"))
    version = project["project"]["version"]

    frontend = ROOT / "frontend"
    run([npm, "ci"], cwd=frontend)
    run([npm, "run", "build"], cwd=frontend)

    backend = ["--project", str(ROOT / "backend")]
    run([uv, "sync", *backend, "--locked", "--no-dev", "--group", "build"])
    run(
        [
            uv, "run", *backend, "--no-sync", "pyinstaller", "--noconfirm", "--clean",
            "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"),
            str(ROOT / "packaging" / "typst-writer.spec"),
        ]
    )  # fmt: skip
    DIST.mkdir(exist_ok=True)
    run(
        [
            iscc, f"/DAppVersion={version}", f"/DSourceDir={BUILD / 'dist' / 'typst-writer'}",
            f"/O{DIST}", str(ROOT / "packaging" / "installer.iss"),
        ]
    )  # fmt: skip
    print(f"Built {DIST / 'typst-writer-setup.exe'} (typst-writer {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
