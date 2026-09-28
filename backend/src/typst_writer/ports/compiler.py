from pathlib import Path
from typing import Protocol

from typst_writer.domain.models import CompileResult, Problem


class CompileFailedError(Exception):
    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        first = problems[0].message if problems else "unknown error"
        super().__init__(f"Compilation failed: {first}")


class Compiler(Protocol):
    """Compiles the Typst project rooted at `root`, starting from its `main` file.

    Problem file paths are relative to `root`.
    """

    async def to_svg_pages(self, main: Path, root: Path) -> CompileResult: ...

    async def to_pdf(self, main: Path, root: Path) -> bytes:
        """Raises CompileFailedError if the document has errors."""
        ...
