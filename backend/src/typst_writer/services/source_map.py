"""Click-to-jump between the preview and the source.

typst-py's SVG output carries no source positions, so a small wrapper file in the compile
mirror (never in the workspace) sets show rules for paragraphs and headings that place an
invisible `metadata` marker with the element's page, y position and text, then includes
the main file. `query` returns the markers; the compiled pages are identical to the
normal ones (checked by the tests). Markers are matched to source blocks (paragraphs,
headings) in document order, following `#include`, by their leading words.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, TypeAdapter, ValidationError

from typst_writer.domain.paragraphs import split_paragraphs
from typst_writer.domain.typst_prose import scan
from typst_writer.domain.word_count import include_positions

WRAPPER_NAME = ".typst-writer-positions.typ"  # hidden: never mirrored from the workspace
SELECTOR = "<tw-pos>"
_WORD = re.compile(r"\w+")
_HEADING = re.compile(r"^[ \t]*=+[ \t]+.*$", re.MULTILINE)
_LEADING_WORDS = 4
_MAX_MARKERS = 20_000


def wrapper_source(main: str) -> str:
    """Typst code that marks every paragraph and heading of `main` (root-relative)."""
    return f"""// Written by typst-writer for click-to-jump; not part of your project.
#let tw-text(it) = {{
  if type(it) == str {{ it }}
  else if type(it) != content {{ "" }}
  else if it.func() in (ref, cite, math.equation, raw, footnote, metadata) {{ "" }}
  else if it.func() == [ ].func() or it.func() == linebreak {{ " " }}
  else if it.has("text") {{ tw-text(it.text) }}
  else if it.has("children") {{ it.children.map(tw-text).join("") }}
  else if it.has("body") {{ tw-text(it.body) }}
  else if it.has("child") {{ tw-text(it.child) }}
  else {{ "" }}
}}
#let tw-mark(kind, body) = context [#metadata((
  kind: kind, page: here().page(), y: here().position().y.pt(), text: tw-text(body),
))<tw-pos>]
#show heading: it => {{ tw-mark("heading", it.body); it }}
#show par: it => {{ tw-mark("par", it.body); it }}
#include {json.dumps("/" + main)}
"""


class Marker(BaseModel):
    kind: str
    page: int
    y: float  # pt from the top of the page
    text: str


_markers: TypeAdapter[list[Marker]] = TypeAdapter(list[Marker])


def parse_markers(raw: str) -> list[Marker]:
    try:
        markers = _markers.validate_json(raw)
    except ValidationError:
        return []
    return markers[:_MAX_MARKERS]


def words(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(text)]


def prose_words(source: str, start: int, end: int, markup: bytearray) -> list[str]:
    text = "".join(" " if markup[i] else source[i] for i in range(start, end))
    return words(text)


@dataclass(frozen=True)
class Block:
    path: str
    start: int  # Python indices in the file
    end: int
    words: tuple[str, ...]


def file_blocks(path: str, source: str) -> list[tuple[int, Block | str]]:
    """Paragraphs and headings of one file, plus its includes, by offset."""
    prose = scan(source)
    items: list[tuple[int, Block | str]] = []
    for match in _HEADING.finditer(source):
        found = prose_words(source, match.start(), match.end(), prose.markup)
        if found:
            items.append((match.start(), Block(path, match.start(), match.end(), tuple(found))))
    for paragraph in split_paragraphs(source, min_prose_chars=1):
        found = prose_words(source, paragraph.start, paragraph.end, prose.markup)
        if found:
            block = Block(path, paragraph.start, paragraph.end, tuple(found))
            items.append((paragraph.start, block))
    items.extend(include_positions(source, path))
    return sorted(items, key=lambda item: item[0])


def document_blocks(main: str, read: Callable[[str], str | None]) -> list[Block]:
    """Every block of the document in reading order (includes expanded in place)."""
    blocks: list[Block] = []
    visiting: set[str] = set()

    def visit(path: str) -> None:
        if path in visiting or len(visiting) > 64:
            return
        source = read(path)
        if source is None:
            return
        visiting.add(path)
        for _, item in file_blocks(path, source):
            if isinstance(item, Block):
                blocks.append(item)
            else:
                visit(item)
        visiting.discard(path)

    visit(main)
    return blocks


def _matches(marker: tuple[str, ...], block: tuple[str, ...]) -> bool:
    n = min(_LEADING_WORDS, len(marker), len(block))
    if n and marker[:n] == block[:n]:
        return True
    head_m, head_b = set(marker[:12]), set(block[:12])
    return len(head_m & head_b) >= 0.6 * max(len(head_m), 1) and len(head_m) >= 3


@dataclass(frozen=True)
class Pair:
    marker: Marker
    block: Block


def align(markers: list[Marker], blocks: list[Block]) -> list[Pair]:
    """Match markers to blocks in order; unmatched markers (outline, bibliography) are
    skipped without losing the position in the source."""
    pairs: list[Pair] = []
    next_block = 0
    for marker in markers:
        marker_words = tuple(words(marker.text))
        if not marker_words:
            continue
        for j in range(next_block, len(blocks)):
            if _matches(marker_words, blocks[j].words):
                pairs.append(Pair(marker, blocks[j]))
                next_block = j + 1
                break
    return pairs


class SourceMap:
    def __init__(self, pairs: list[Pair], read: Callable[[str], str | None]) -> None:
        self.pairs = pairs
        self._read = read

    def _next_on_page(self, i: int) -> Marker | None:
        if i + 1 < len(self.pairs) and self.pairs[i + 1].marker.page == self.pairs[i].marker.page:
            return self.pairs[i + 1].marker
        return None

    def to_source(self, page: int, y: float) -> tuple[str, int] | None:
        """(path, Python index) for a click at `y` pt on `page` (1-based)."""
        on_page = [i for i, p in enumerate(self.pairs) if p.marker.page == page]
        if not on_page:
            before = [i for i, p in enumerate(self.pairs) if p.marker.page < page]
            if not before:
                return None
            on_page = [before[-1]]
        above = [i for i in on_page if self.pairs[i].marker.y <= y + 2] or [on_page[0]]
        i = above[-1]
        pair = self.pairs[i]
        following = self._next_on_page(i)
        fraction = 0.0
        if following is not None and following.y > pair.marker.y:
            fraction = min(max((y - pair.marker.y) / (following.y - pair.marker.y), 0.0), 1.0)
        block = pair.block
        index = block.start + round(fraction * (block.end - block.start))
        source = self._read(block.path) or ""
        while index > block.start and not source[index - 1].isspace():
            index -= 1  # start of the word
        return block.path, index

    def to_preview(self, path: str, index: int) -> tuple[int, float] | None:
        """(page, y pt) of the Python index `index` in `path`."""
        candidates = [
            i for i, p in enumerate(self.pairs) if p.block.path == path and p.block.start <= index
        ]
        if not candidates:
            return None
        i = candidates[-1]
        pair = self.pairs[i]
        block = pair.block
        following = self._next_on_page(i)
        y = pair.marker.y
        if following is not None and block.end > block.start and index <= block.end:
            fraction = (index - block.start) / (block.end - block.start)
            y += fraction * (following.y - pair.marker.y)
        return pair.marker.page, y


def build(raw_markers: str, main: str, read: Callable[[str], str | None]) -> SourceMap:
    markers = parse_markers(raw_markers)
    return SourceMap(align(markers, document_blocks(main, read)), read)
