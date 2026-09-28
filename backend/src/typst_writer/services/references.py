"""Workspace index for the insert dialogs: labels to reference, bibliography keys to cite,
images to place, and whether the document already prints a bibliography."""

import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from typst_writer.infra.paths import WorkspaceGuard

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf"}
MAX_FILES = 5_000
MAX_FILE_BYTES = 5_000_000

TargetKind = Literal["heading", "figure", "table", "equation", "label", "citation"]
_PREFIX_KIND: dict[str, TargetKind] = {
    "tab": "table",
    "fig": "figure",
    "eq": "equation",
    "sec": "heading",
    "ch": "heading",
}

# Things that look like labels but are not: comments, raw text and strings. Replaced by
# spaces (newlines kept) so line numbers stay correct.
_NOT_MARKUP = re.compile(
    r'```.*?```|`[^`\n]*`|/\*.*?\*/|(?<!:)//[^\n]*|"(?:[^"\\\n]|\\.)*"', re.DOTALL
)
_LABEL = re.compile(r"<([^\W_][\w.:-]*)>")
_IMAGE = re.compile(r'image\(\s*"([^"]+)"')
_CAPTION = re.compile(r"caption:\s*\[((?:\\.|[^\]\\])*)\]")
_BIB_ENTRY = re.compile(r"@(\w+)\s*[{(]\s*([^,\s{}()]+)\s*,")
_BIB_TITLE = re.compile(r"\btitle\s*=\s*[{\"](.+?)[}\"]\s*,?\s*$", re.IGNORECASE | re.MULTILINE)


class ReferenceTarget(BaseModel):
    key: str
    kind: TargetKind
    file: str
    line: int
    description: str


class WorkspaceIndex(BaseModel):
    targets: list[ReferenceTarget]
    images: list[str]
    bibliographies: list[str]  # .bib files in the workspace
    has_bibliography_call: bool  # some .typ file calls #bibliography(...)

    def labels(self) -> set[str]:
        return {t.key for t in self.targets if t.kind != "citation"}


def _blank(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def _short(text: str, limit: int = 80) -> str:
    clean = " ".join(text.replace("\\", "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def _figure_description(source: str, label_start: int) -> str | None:
    """Caption (or image file name) of the #figure(...) directly before a label."""
    figure_start = source.rfind("#figure(", max(0, label_start - 5000), label_start)
    if figure_start < 0:
        return None
    span = source[figure_start:label_start]
    captions = list(_CAPTION.finditer(span))
    if captions:
        return captions[-1].group(1)
    image = _IMAGE.search(span)
    return image.group(1).rsplit("/", 1)[-1] if image else None


def scan_typst(source: str, file: str) -> tuple[list[ReferenceTarget], bool]:
    """Labels defined in one .typ file, and whether it calls #bibliography."""
    code = _NOT_MARKUP.sub(_blank, source)
    targets: list[ReferenceTarget] = []
    for match in _LABEL.finditer(code):
        key = match.group(1)
        line_start = code.rfind("\n", 0, match.start()) + 1
        line_end = source.find("\n", match.end())
        line_text = source[line_start : line_end if line_end >= 0 else len(source)]
        kind = _PREFIX_KIND.get(key.split(":", 1)[0]) if ":" in key else None
        if kind is None:
            kind = "heading" if line_text.lstrip().startswith("=") else "label"
        if kind == "heading":
            description = line_text.split("<", 1)[0].lstrip("= \t")
        elif kind in ("figure", "table"):
            description = _figure_description(source, match.start()) or line_text.strip()
        else:
            description = line_text.strip()
        targets.append(
            ReferenceTarget(
                key=key,
                kind=kind,
                file=file,
                line=code.count("\n", 0, match.start()) + 1,
                description=_short(description),
            )
        )
    return targets, "#bibliography(" in code


def scan_bib(source: str, file: str) -> list[ReferenceTarget]:
    targets: list[ReferenceTarget] = []
    starts = [m for m in _BIB_ENTRY.finditer(source)]
    for i, match in enumerate(starts):
        if match.group(1).lower() in ("comment", "string", "preamble"):
            continue
        end = starts[i + 1].start() if i + 1 < len(starts) else len(source)
        title = _BIB_TITLE.search(source, match.end(), end)
        targets.append(
            ReferenceTarget(
                key=match.group(2),
                kind="citation",
                file=file,
                line=source.count("\n", 0, match.start()) + 1,
                description=_short(title.group(1) if title else match.group(1)),
            )
        )
    return targets


def _files(guard: WorkspaceGuard) -> Iterator[tuple[str, Path]]:
    count = 0
    for dirpath, dirnames, filenames in os.walk(guard.root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if name.startswith(".") or not path.resolve().is_relative_to(guard.root):
                continue
            count += 1
            if count > MAX_FILES:
                return
            yield path.relative_to(guard.root).as_posix(), path


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def build_index(guard: WorkspaceGuard, overlays: Mapping[str, str]) -> WorkspaceIndex:
    """Index the workspace; `overlays` (unsaved editor buffers) replace files on disk."""
    targets: list[ReferenceTarget] = []
    images: list[str] = []
    bibliographies: list[str] = []
    has_call = False
    for rel, path in _files(guard):
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            images.append(rel)
        elif suffix == ".typ":
            source = overlays.get(rel)
            if source is None:
                source = _read(path)
            if source is not None:
                found, calls = scan_typst(source, rel)
                targets.extend(found)
                has_call = has_call or calls
        elif suffix == ".bib":
            bibliographies.append(rel)
            source = _read(path)
            if source is not None:
                targets.extend(scan_bib(source, rel))
    return WorkspaceIndex(
        targets=targets,
        images=images,
        bibliographies=bibliographies,
        has_bibliography_call=has_call,
    )
