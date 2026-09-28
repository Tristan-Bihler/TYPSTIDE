"""The Format controls: options (fonts Typst can use, sizes, line spacings) and the edits
for a selection, the whole document, and the values at the cursor.

Values from the page are checked against these options before any code is generated;
edits are returned in UTF-16 offsets like the editor uses.
"""

import threading
import tomllib
from pathlib import Path
from typing import Literal

import typst
from pydantic import BaseModel, ConfigDict, Field

from typst_writer.domain import formatting
from typst_writer.domain.formatting import CannotFormatError, Current, Edit
from typst_writer.domain.positions import TextPositions
from typst_writer.domain.typst_text import escape_string

MAX_CONTENT = 2_000_000


class FontOption(BaseModel):
    family: str
    builtin: bool  # ships with Typst: the document looks the same on every computer


class LineSpacing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    leading: str = Field(pattern=r"^\d+(\.\d+)?em$")
    default: bool = False


class FormatConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_font: str
    default_size: float
    sizes: list[float]
    line_spacing: list[LineSpacing]


class FormatOptions(BaseModel):
    fonts: list[FontOption]
    sizes: list[float]
    default_size: float
    default_font: str
    line_spacing: list[LineSpacing]


class FormatChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["font", "size", "line_spacing"]
    value: str = Field(min_length=1, max_length=200)


class FormatRequest(BaseModel):
    """Format the selection [start, end) (UTF-16) of `content`."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=MAX_CONTENT)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    change: FormatChange


class DocumentFormatRequest(BaseModel):
    """Set the default for the whole document in `content`, the main file."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=MAX_CONTENT)
    change: FormatChange


class CurrentFormatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=MAX_CONTENT)
    offset: int = Field(ge=0)
    main_content: str | None = Field(default=None, max_length=MAX_CONTENT)


class TextEdit(BaseModel):
    start: int  # UTF-16
    end: int
    insert: str


class CurrentFormat(BaseModel):
    font: str | None
    size: str | None
    leading: str | None


class FormattingService:
    def __init__(self, snippets_path: Path) -> None:
        with snippets_path.open("rb") as f:
            self._config = FormatConfig.model_validate(tomllib.load(f)["format"])
        self._fonts: list[FontOption] | None = None
        self._lock = threading.Lock()

    def fonts(self, refresh: bool = False) -> list[FontOption]:
        """Every font family the compiler can use; Typst's own first (slow the first time:
        the system fonts are read)."""
        with self._lock:
            if self._fonts is None or refresh:
                builtin = set(typst.Fonts(include_system_fonts=False).families())
                every = set(typst.Fonts().families()) | builtin
                ordered = sorted(every, key=lambda f: (f not in builtin, f.casefold()))
                self._fonts = [FontOption(family=f, builtin=f in builtin) for f in ordered]
            return self._fonts

    def options(self, refresh: bool = False) -> FormatOptions:
        return FormatOptions(
            fonts=self.fonts(refresh),
            sizes=self._config.sizes,
            default_size=self._config.default_size,
            default_font=self._config.default_font,
            line_spacing=self._config.line_spacing,
        )

    def _typst_value(self, change: FormatChange) -> str:
        """The checked Typst value for the change, or CannotFormatError."""
        match change.kind:
            case "font":
                if change.value not in {f.family for f in self.fonts()}:
                    raise CannotFormatError(f"Typst does not know the font '{change.value}'.")
                return f'"{escape_string(change.value)}"'
            case "size":
                try:
                    size = round(float(change.value), 1)
                except ValueError:
                    raise CannotFormatError("The size must be a number.") from None
                if not 4 <= size <= 96:
                    raise CannotFormatError("Choose a size between 4 and 96 pt.")
                return f"{size:g}pt"
            case _:
                for option in self._config.line_spacing:
                    if option.label == change.value:
                        return option.leading
                raise CannotFormatError(f"Unknown line spacing '{change.value}'.")

    @staticmethod
    def _to_utf16(content: str, edit: Edit) -> TextEdit:
        positions = TextPositions(content)
        return TextEdit(
            start=positions.utf16_offset(edit.start),
            end=positions.utf16_offset(edit.end),
            insert=edit.insert,
        )

    def apply(self, req: FormatRequest) -> TextEdit:
        value = self._typst_value(req.change)
        positions = TextPositions(req.content)
        start = positions.index_of_utf16(min(req.start, req.end))
        end = positions.index_of_utf16(max(req.start, req.end))
        if req.change.kind == "line_spacing":
            edit = formatting.space_paragraphs(req.content, start, end, value)
        else:
            name: formatting.TextAttribute = "font" if req.change.kind == "font" else "size"
            edit = formatting.format_selection(req.content, start, end, name, value)
        return self._to_utf16(req.content, edit)

    def document(self, req: DocumentFormatRequest) -> TextEdit:
        value = self._typst_value(req.change)
        if req.change.kind == "line_spacing":
            edit = formatting.set_document(req.content, "par", "leading", value)
        else:
            edit = formatting.set_document(req.content, "text", req.change.kind, value)
        return self._to_utf16(req.content, edit)

    def current(self, req: CurrentFormatRequest) -> CurrentFormat:
        index = TextPositions(req.content).index_of_utf16(req.offset)
        found: Current = formatting.current(req.content, index, req.main_content)
        return CurrentFormat(font=found.font, size=found.size, leading=found.leading)
