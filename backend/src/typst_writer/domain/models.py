"""Core data model shared by services, adapters and the API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


SnippetKind = Literal["wrap", "line_prefix", "block", "dialog"]
DialogKind = Literal["table", "figure", "equation", "reference", "bibliography", "chart"]


class Snippet(BaseModel):
    """One insert-toolbar entry, defined in snippets.toml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    label: str = Field(min_length=1)
    group: str = Field(min_length=1)
    kind: SnippetKind
    template: str = ""
    placeholder: str = ""
    dialog: DialogKind | None = None
    shortcut: str | None = None
    title: str = ""
    in_toolbar: bool = True
    required_packages: list[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> "Snippet":
        if (self.kind == "dialog") != (self.dialog is not None):
            raise ValueError(f"{self.id}: 'dialog' is required exactly for kind = 'dialog'")
        if self.kind != "dialog" and not self.template:
            raise ValueError(f"{self.id}: kind '{self.kind}' needs a template")
        if self.kind == "wrap" and "{selection}" not in self.template:
            raise ValueError(f"{self.id}: wrap templates must contain {{selection}}")
        return self
