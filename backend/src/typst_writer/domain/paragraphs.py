"""Split a Typst document into prose paragraphs for the local AI check.

Paragraphs are separated by blank lines; heading lines count as separators too. Blocks
with little prose (code, math, figures without a long caption, very short lines) are
skipped, so the model only sees text it can improve. Offsets are Python string indices.
"""

import re
from dataclasses import dataclass

from typst_writer.domain.typst_prose import ProseMap, scan

MIN_PROSE_CHARS = 30
_SEPARATOR = re.compile(r"\n[ \t\r]*\n|^[ \t]*=+[ \t].*$", re.MULTILINE)


@dataclass(frozen=True)
class Paragraph:
    start: int
    end: int
    text: str


def split_paragraphs(text: str, min_prose_chars: int = MIN_PROSE_CHARS) -> list[Paragraph]:
    prose = scan(text)
    paragraphs: list[Paragraph] = []
    position = 0
    for separator in [*_SEPARATOR.finditer(text), None]:
        end = len(text) if separator is None else separator.start()
        _add(paragraphs, text, prose, position, end, min_prose_chars)
        if separator is not None:
            position = separator.end()
    return paragraphs


def _add(
    paragraphs: list[Paragraph], text: str, prose: ProseMap, start: int, end: int, minimum: int
) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end <= start:
        return
    prose_chars = sum(1 for i in range(start, end) if not prose.markup[i] and not text[i].isspace())
    if prose_chars >= minimum:
        paragraphs.append(Paragraph(start, end, text[start:end]))


def paragraph_at(paragraphs: list[Paragraph], index: int) -> Paragraph | None:
    """The paragraph containing (or ending at) the Python index."""
    return next((p for p in paragraphs if p.start <= index <= p.end), None)
