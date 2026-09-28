"""Compile Typst code with the pinned typst-py and report errors and warnings.

Usage (from the repo root; uses the backend's pinned Typst):
  CHECK=.claude/skills/typst-syntax/scripts/compile_check.py
  uv run --project backend python $CHECK FILE.typ [--root DIR]
  echo '#figure(...)' | uv run --project backend python $CHECK -

A snippet read from stdin is compiled inside the bundled example project
(`examples/`), so it can reference `/bilder/logo.svg`, `@tab:messwerte`, `@knuth1984`, ….
Exit code 0 = compiles without errors (warnings are printed but allowed).
"""

import argparse
import importlib.metadata
import sys
import tempfile
from pathlib import Path

import typst

SKILL_DIR = Path(__file__).resolve().parent.parent
EXAMPLES = SKILL_DIR / "examples"


def compile_file(main: Path, root: Path) -> int:
    try:
        _, warnings = typst.Compiler(str(main), root=str(root)).compile_with_warnings(format="svg")
    except typst.TypstError as error:
        print(error.diagnostic, file=sys.stderr)
        return 1
    for warning in warnings:
        print(warning.diagnostic, file=sys.stderr)
    version = importlib.metadata.version("typst")
    print(f"OK: compiles with typst-py {version}, {len(warnings)} warning(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("file", help="a .typ file, or - to read a snippet from stdin")
    parser.add_argument("--root", help="project root (default: the file's folder)")
    args = parser.parse_args()

    if args.file != "-":
        main_file = Path(args.file).resolve()
        return compile_file(main_file, Path(args.root).resolve() if args.root else main_file.parent)

    snippet = sys.stdin.read()
    with tempfile.NamedTemporaryFile(
        "w", suffix=".typ", dir=EXAMPLES, encoding="utf-8", delete=False
    ) as f:
        # The example project's main file first, so labels and the bibliography exist.
        f.write((EXAMPLES / "main.typ").read_text(encoding="utf-8"))
        f.write("\n\n// --- snippet under test ---\n")
        f.write(snippet)
        tmp = Path(f.name)
    try:
        return compile_file(tmp, EXAMPLES)
    finally:
        tmp.unlink()


if __name__ == "__main__":
    sys.exit(main())
