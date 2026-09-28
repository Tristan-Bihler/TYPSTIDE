"""Word counts for the status bar: prose words only (markup, code, math, raw text and
comments do not count), per file and for the whole document (the main file plus every
chapter it includes, recursively)."""

import re
from collections.abc import Callable
from posixpath import dirname, join, normpath

from typst_writer.domain.typst_prose import scan

_WORD = re.compile(r"\w+(?:[-'\u2019]\w+)*")  # don't, Max-Planck (also typographic apostrophe)
_INCLUDE = re.compile(r'#include\s+"([^"\\\n]+)"')
# Strings are kept (they hold the include paths); comments and raw text are blanked.
_NOT_CODE = re.compile(r'"(?:\\.|[^"\\\n])*"|//[^\n]*|/\*.*?\*/|```.*?```|`[^`\n]*`', re.DOTALL)
MAX_INCLUDE_DEPTH = 32


def count_words(source: str) -> int:
    prose = scan(source)
    text = "".join(" " if prose.markup[i] else c for i, c in enumerate(source))
    return len(_WORD.findall(text))


def includes(source: str, path: str) -> list[str]:
    """Workspace-relative paths of the files `path` includes, in order. Paths starting with
    "/" are relative to the project root, others to the including file."""
    code = _NOT_CODE.sub(lambda m: m.group() if m.group().startswith('"') else " ", source)
    found: list[str] = []
    for match in _INCLUDE.finditer(code):
        target = match.group(1)
        joined = target.lstrip("/") if target.startswith("/") else join(dirname(path), target)
        normalized = normpath(joined)
        if normalized != ".." and not normalized.startswith(("../", "/")):
            found.append(normalized)
    return found


def document_counts(main: str, read: Callable[[str], str | None]) -> dict[str, int]:
    """Words per file for the main file and everything it includes (each file once)."""
    counts: dict[str, int] = {}

    def visit(path: str, depth: int) -> None:
        if path in counts or depth > MAX_INCLUDE_DEPTH:
            return
        source = read(path)
        if source is None:
            return
        counts[path] = count_words(source)
        for child in includes(source, path):
            visit(child, depth + 1)

    visit(main, 0)
    return counts
