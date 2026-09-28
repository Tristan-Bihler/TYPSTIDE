"""`Compiler` implementation backed by typst-py."""

import asyncio
import json
import re
import threading
import time
from functools import cache
from pathlib import Path

import typst

from typst_writer.domain.models import CompileResult, Problem, Severity
from typst_writer.ports.compiler import CompileFailedError

# First location line of a rendered diagnostic, e.g. "  ┌─ chapters/intro.typ:3:4".
# typst-py prints the path relative to the process working directory and a 0-based
# character column.
_LOCATION_RE = re.compile(r"┌─ (?P<path>.+):(?P<line>\d+):(?P<column>\d+)\s*$", re.MULTILINE)


@cache
def typst_version() -> str:
    """Version of the Typst compiler bundled in typst-py, as reported by Typst itself."""
    raw = typst.query(b"#metadata(str(sys.version)) <v>", "<v>", field="value", one=True)
    version = json.loads(raw)
    if not isinstance(version, str):
        raise TypeError(f"unexpected Typst version value: {version!r}")
    return version


def parse_diagnostic(
    message: str, diagnostic: str, hints: list[str], severity: Severity, root: Path
) -> Problem:
    """Turn a typst-py diagnostic into a Problem with a root-relative file and 1-based column."""
    file, line, column = "", 0, 0
    match = _LOCATION_RE.search(diagnostic)
    if match:
        path = (Path.cwd() / match["path"]).resolve()
        if path.is_relative_to(root):
            file = path.relative_to(root).as_posix()
            line = int(match["line"])
            column = int(match["column"]) + 1
    text = message if not hints else f"{message} (hint: {'; '.join(hints)})"
    return Problem(
        file=file, line=line, column=column, severity=severity, message=text, source="typst"
    )


class TypstPyCompiler:
    """Reuses one typst-py `Compiler` per (main, root) so unchanged files stay cached."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: tuple[Path, Path] | None = None
        self._compiler: typst.Compiler | None = None

    def _get(self, main: Path, root: Path) -> typst.Compiler:
        if self._compiler is None or self._key != (main, root):
            self._compiler = typst.Compiler(str(main), root=str(root))
            self._key = (main, root)
        return self._compiler

    def _warnings(self, warnings: list[typst.TypstWarning], root: Path) -> list[Problem]:
        return [
            parse_diagnostic(w.message, w.diagnostic, w.hints, "warning", root) for w in warnings
        ]

    def _svg_blocking(self, main: Path, root: Path) -> CompileResult:
        root = root.resolve()
        start = time.perf_counter()
        with self._lock:
            try:
                output, warnings = self._get(main, root).compile_with_warnings(format="svg")
            except typst.TypstError as e:
                problem = parse_diagnostic(e.message, e.diagnostic, e.hints, "error", root)
                return CompileResult(
                    ok=False,
                    pages=[],
                    problems=[problem],
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
        # typst-py returns bare bytes for a single page and a list for several.
        raw_pages = output if isinstance(output, list) else [output] if output else []
        return CompileResult(
            ok=True,
            pages=[page.decode("utf-8") for page in raw_pages],
            problems=self._warnings(warnings, root),
            duration_ms=(time.perf_counter() - start) * 1000,
        )

    def _pdf_blocking(self, main: Path, root: Path) -> bytes:
        root = root.resolve()
        with self._lock:
            try:
                output = self._get(main, root).compile(format="pdf")
            except typst.TypstError as e:
                problem = parse_diagnostic(e.message, e.diagnostic, e.hints, "error", root)
                raise CompileFailedError([problem]) from e
        if not isinstance(output, bytes):
            raise TypeError("typst-py returned no PDF data")
        return output

    async def to_svg_pages(self, main: Path, root: Path) -> CompileResult:
        return await asyncio.to_thread(self._svg_blocking, main, root)

    async def to_pdf(self, main: Path, root: Path) -> bytes:
        return await asyncio.to_thread(self._pdf_blocking, main, root)
