"""Core data model shared by services, adapters and the API."""

from typing import Literal

from pydantic import BaseModel

Severity = Literal["error", "warning", "grammar", "ai"]


class Problem(BaseModel):
    file: str  # workspace-relative POSIX path; "" if the problem has no location in the workspace
    line: int  # 1-based; 0 if unknown
    column: int  # 1-based; 0 if unknown
    severity: Severity
    message: str
    source: str  # e.g. "typst", "ltex"


class CompileResult(BaseModel):
    ok: bool
    pages: list[str]  # one SVG document per page; empty if compilation failed
    problems: list[Problem]
    duration_ms: float
