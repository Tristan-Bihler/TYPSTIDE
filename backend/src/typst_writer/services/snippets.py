"""Insert-toolbar snippets: loaded from snippets.toml; dialog snippets rendered here.

All generated Typst follows .claude/skills/typst-syntax (verified for Typst 0.15.0).
"""

import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from typst_writer.domain.errors import (
    InvalidSnippetParamsError,
    PathOutsideWorkspaceError,
    UnknownSnippetError,
)
from typst_writer.domain.models import Snippet
from typst_writer.domain.typst_text import escape_markup, escape_string, is_label
from typst_writer.infra.paths import WorkspaceGuard
from typst_writer.services.references import IMAGE_EXTENSIONS, WorkspaceIndex

# Existing heading/list marker at the start of a line (replaced by line_prefix snippets).
_LINE_MARKER = re.compile(r"^(\s*)(=+|[-+]|\d+\.)\s+")


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Labelled(_Params):
    label: str = Field("", max_length=120)

    @field_validator("label")
    @classmethod
    def _label_syntax(cls, value: str) -> str:
        if value and not is_label(value):
            raise ValueError("Labels may contain letters, digits and _ - . : only.")
        return value


class TableParams(_Labelled):
    rows: int = Field(3, ge=1, le=200)
    columns: int = Field(3, ge=1, le=50)
    header_row: bool = True
    caption: str = Field("", max_length=500)
    language: Literal["de-DE", "en-US"] = "de-DE"


class FigureParams(_Labelled):
    image: str = Field(min_length=1, max_length=500)
    caption: str = Field("", max_length=500)
    width_percent: int = Field(80, ge=10, le=100)


class EquationParams(_Labelled):
    math: str = Field(min_length=1, max_length=2000)
    block: bool = True

    @field_validator("math")
    @classmethod
    def _no_dollar(cls, value: str) -> str:
        if "$" in value:
            raise ValueError("Leave out the $ signs; they are added for you.")
        return value


class ReferenceParams(_Params):
    target: str = Field(min_length=1, max_length=200)


class BibliographyParams(_Params):
    file: str = Field(min_length=1, max_length=500)


def _label_suffix(label: str, index: WorkspaceIndex | None) -> str:
    if not label:
        return ""
    if index is not None and label in index.labels():
        raise InvalidSnippetParamsError(f"The label <{label}> is already used. Choose another.")
    return f" <{label}>"


def _workspace_file(guard: WorkspaceGuard, rel: str, extensions: set[str], what: str) -> str:
    """Validate a workspace file and return it as a root-relative Typst path ("/…")."""
    normalized = PurePosixPath(rel.replace("\\", "/")).as_posix().lstrip("/")
    try:
        path = guard.resolve(normalized)
    except PathOutsideWorkspaceError as e:
        raise InvalidSnippetParamsError(str(e)) from e
    if not path.is_file() or path.suffix.lower() not in extensions:
        raise InvalidSnippetParamsError(f"'{rel}' is not {what} in the open folder.")
    return "/" + normalized


def render_table(p: TableParams, index: WorkspaceIndex | None) -> str:
    word = "Spalte" if p.language == "de-DE" else "Column"
    lines = ["#figure(", "  table(", f"    columns: {p.columns},"]
    if p.header_row:
        header = "".join(f"[*{word} {i}*]" for i in range(1, p.columns + 1))
        lines.append(f"    table.header{header},")
    row = ", ".join(["[ ]"] * p.columns)
    lines.extend(f"    {row}," for _ in range(p.rows))
    lines.append("  ),")
    if p.caption:
        lines.append(f"  caption: [{escape_markup(p.caption)}],")
    lines.append(")" + _label_suffix(p.label, index))
    return "\n".join(lines)


def render_figure(p: FigureParams, guard: WorkspaceGuard, index: WorkspaceIndex | None) -> str:
    path = _workspace_file(guard, p.image, IMAGE_EXTENSIONS, "an image")
    lines = ["#figure(", f'  image("{escape_string(path)}", width: {p.width_percent}%),']
    if p.caption:
        lines.append(f"  caption: [{escape_markup(p.caption)}],")
    lines.append(")" + _label_suffix(p.label, index))
    return "\n".join(lines)


def render_equation(p: EquationParams, index: WorkspaceIndex | None) -> str:
    math = " ".join(p.math.split()) if not p.block else p.math.strip()
    if not p.block:
        if p.label:
            raise InvalidSnippetParamsError("Only block equations can have a label.")
        return f"${math}$"
    if not p.label:
        return f"$ {math} $"
    # A labelled equation needs numbering, or referencing it fails (see typst-syntax skill).
    return (
        f'#math.equation(block: true, numbering: "(1)", $ {math} $){_label_suffix(p.label, index)}'
    )


def render_reference(p: ReferenceParams) -> str:
    if is_label(p.target):
        return f"@{p.target}"
    return f'#ref(label("{escape_string(p.target)}"))'


def render_bibliography(p: BibliographyParams, guard: WorkspaceGuard) -> str:
    path = _workspace_file(guard, p.file, {".bib"}, "a .bib file")
    return f'#bibliography("{escape_string(path)}")'


def apply_simple(snippet: Snippet, selection: str = "", line: str = "") -> str:
    """Python mirror of the editor's snippet application (used to compile-test snippets).

    wrap: returns the replacement for `selection`; line_prefix: the new `line`;
    block: the block's own line.
    """
    match snippet.kind:
        case "wrap":
            return snippet.template.replace("{selection}", selection or snippet.placeholder)
        case "line_prefix":
            marker = _LINE_MARKER.match(line)
            rest = line[marker.end() :] if marker else line.lstrip()
            if marker and marker.group(0).strip() == snippet.template.strip():
                return rest  # applying the same prefix again removes it
            return snippet.template + rest
        case "block":
            return snippet.template
        case "dialog":
            raise InvalidSnippetParamsError(f"'{snippet.id}' is rendered through its dialog.")


class SnippetService:
    def __init__(self, path: Path) -> None:
        with path.open("rb") as f:
            data = tomllib.load(f)
        snippets = [Snippet.model_validate(item) for item in data.get("snippet", [])]
        ids = [s.id for s in snippets]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate snippet ids in {path}: {sorted(duplicates)}")
        self._snippets = {s.id: s for s in snippets}

    def list(self) -> list[Snippet]:
        return list(self._snippets.values())

    def get(self, snippet_id: str) -> Snippet:
        snippet = self._snippets.get(snippet_id)
        if snippet is None:
            raise UnknownSnippetError(snippet_id)
        return snippet

    def render(
        self,
        snippet_id: str,
        params: dict[str, Any],
        guard: WorkspaceGuard,
        index: WorkspaceIndex | None = None,
    ) -> str:
        """Typst code for a dialog snippet. Raises InvalidSnippetParamsError on bad input."""
        snippet = self.get(snippet_id)
        try:
            match snippet.dialog:
                case "table":
                    return render_table(TableParams.model_validate(params), index)
                case "figure":
                    return render_figure(FigureParams.model_validate(params), guard, index)
                case "equation":
                    return render_equation(EquationParams.model_validate(params), index)
                case "reference":
                    return render_reference(ReferenceParams.model_validate(params))
                case "bibliography":
                    return render_bibliography(BibliographyParams.model_validate(params), guard)
                case _:
                    raise InvalidSnippetParamsError(f"'{snippet_id}' has no dialog renderer yet.")
        except ValidationError as e:
            messages = "; ".join(
                str(err["msg"]).removeprefix("Value error, ") for err in e.errors()
            )
            raise InvalidSnippetParamsError(messages) from e
