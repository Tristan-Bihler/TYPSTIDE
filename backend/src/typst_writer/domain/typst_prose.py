"""Where the prose is in a Typst document.

A small scanner, deliberately simpler than the Typst parser: it marks every character that
is markup rather than prose (labels, references, math, raw text, comments, `#code` outside
its `[content]` blocks, heading and list markers) and records **block starts**, the
offsets where a new paragraph, heading, list item or content block (e.g. a caption)
begins. The grammar filter uses both to drop false alarms that LTeX+'s regex-based Typst
support produces around markup. Offsets are Python string indices.
"""

import re
from array import array
from dataclasses import dataclass

_LABEL = re.compile(r"<[\w\-.:]+>")
_REF = re.compile(r"@[\w\-.:]*[\w\-]")
_IDENT = re.compile(r"[A-Za-z_][\w-]*")
_LINE_MARKER = re.compile(r"[ \t]*(=+[ \t]+|[-+][ \t]+|\d+\.[ \t]+|/[ \t]+)")
_CODE_LINE_KEYWORDS = {"let", "set", "show", "import", "include", "if", "for", "while"}


@dataclass(frozen=True)
class Frame:
    """A stretch of markup: the document itself, or one `[...]` content block."""

    parent: int  # index into ProseMap.frames; -1 for the document
    opener: int  # index of the "[" (-1 for the document)
    expr_start: int  # index of the "#" of `#name(...)[...]` or `#[...]`; -1 otherwise
    callee: str | None  # "text" for `#text(...)[...]`; None for `#[...]` and others


@dataclass(frozen=True)
class ProseMap:
    text: str
    markup: bytearray  # 1 where the character is markup, not prose
    block_starts: frozenset[int]
    # 1 for punctuation glued to a reference ("@fig:a)." -> ")."): LTeX+ takes it as part
    # of the reference and never sees it.
    swallowed: bytearray
    # For every index 0..len(text): the frame whose markup the position lies *between
    # tokens* of (a place where content could be cut and wrapped), or -1 inside a token
    # (code, math, raw text, a comment, an escape, a label or reference).
    owner: array[int]
    frames: tuple[Frame, ...]

    def is_markup(self, start: int, end: int) -> bool:
        """Whether any character in [start, end) is markup."""
        return any(self.markup[max(start, 0) : max(end, start + 1)])


def scan(text: str) -> ProseMap:
    scanner = _Scanner(text)
    scanner.markup_mode(0, closing=False)
    return ProseMap(
        text,
        scanner.marks,
        frozenset(scanner.starts),
        scanner.swallowed,
        scanner.owner,
        tuple(scanner.frames),
    )


class _Scanner:
    def __init__(self, text: str) -> None:
        self.text = text
        self.n = len(text)
        self.marks = bytearray(self.n)
        self.swallowed = bytearray(self.n)
        self.starts: set[int] = set()
        self.owner = array("i", [-1]) * (self.n + 1)
        self.frames: list[Frame] = []
        self.frame_stack: list[int] = []

    def mark(self, start: int, end: int) -> None:
        self.marks[start:end] = b"\x01" * (min(end, self.n) - start)

    # --- markup (prose) mode ------------------------------------------------------

    def markup_mode(
        self, i: int, closing: bool, expr_start: int = -1, callee: str | None = None
    ) -> int:
        """Scan prose from i; with `closing`, stop after the `]` that ends this block."""
        parent = self.frame_stack[-1] if self.frame_stack else -1
        frame = len(self.frames)
        self.frames.append(Frame(parent, i - 1 if closing else -1, expr_start, callee))
        self.frame_stack.append(frame)
        try:
            return self._markup(i, closing, frame)
        finally:
            self.frame_stack.pop()

    def _markup(self, i: int, closing: bool, frame: int) -> int:
        text, n = self.text, self.n
        pending = True  # the next prose character starts a block
        prose_on_line = False
        pending_after_line = False  # the line ended with "@ref." (see below)
        line_start = True
        while i < n:
            self.owner[i] = frame
            if line_start:
                line_start = False
                marker = _LINE_MARKER.match(text, i)
                if marker is not None:
                    self.mark(i, marker.end())
                    pending = True
                    i = marker.end()
                    continue
            c = text[i]
            if c == "\n":
                blank = text[text.rfind("\n", 0, i) + 1 : i].strip() == ""
                if blank or not prose_on_line or pending_after_line:
                    pending = True
                prose_on_line = pending_after_line = False
                line_start = True
                i += 1
            elif c in " \t\r":
                i += 1
            elif closing and c == "]":
                self.mark(i, i + 1)
                return i + 1
            elif c == "\\":
                self._prose(i, pending)
                pending, prose_on_line = False, True
                i += 2
            elif text.startswith("//", i):
                i = self._line_comment(i)
            elif text.startswith("/*", i):
                i = self._block_comment(i)
            elif text.startswith("```", i):
                i = self._delimited(i, "```")
            elif c == "`":
                i = self._delimited(i, "`")
            elif c == "$":
                i = self._math(i)
            elif c == "<" and (label := _LABEL.match(text, i)) is not None:
                start = i
                while start > 0 and text[start - 1] in " \t":
                    start -= 1
                self.mark(start, label.end())
                i = label.end()
            elif (
                c == "@" and (i == 0 or not text[i - 1].isalnum()) and (ref := _REF.match(text, i))
            ):
                self.mark(i, ref.end())
                prose_on_line = True  # a reference reads as a word in the sentence
                pending = False
                i = ref.end()
                glued = i
                while glued < n and not text[glued].isspace():
                    glued += 1
                self.swallowed[i:glued] = b"\x01" * (glued - i)
                if any(ch in ".!?" for ch in text[i:glued]):
                    # LTeX+ swallows the period with the reference ("@a." or "@a)."), so
                    # it misses that a new sentence starts after it.
                    j = glued
                    while j < n and text[j] in " \t":
                        j += 1
                    if j < n and text[j] != "\n":
                        self.starts.add(j)
                    else:
                        pending_after_line = True
            elif c == "#":
                i = self._hash_expression(i)
            elif c in "*_":
                self.mark(i, i + 1)  # emphasis markers
                i += 1
            else:
                self._prose(i, pending)
                pending, prose_on_line = False, True
                i += 1
        self.owner[min(i, n)] = frame
        return i

    def _prose(self, i: int, pending: bool) -> None:
        if pending:
            self.starts.add(i)

    # --- tokens that are markup as a whole ------------------------------------------

    def _line_comment(self, i: int) -> int:
        end = self.text.find("\n", i)
        end = self.n if end < 0 else end
        self.mark(i, end)
        return end

    def _block_comment(self, i: int) -> int:
        end = self.text.find("*/", i + 2)
        end = self.n if end < 0 else end + 2
        self.mark(i, end)
        return end

    def _delimited(self, i: int, fence: str) -> int:
        end = self.text.find(fence, i + len(fence))
        end = self.n if end < 0 else end + len(fence)
        self.mark(i, end)
        return end

    def _math(self, i: int) -> int:
        j = i + 1
        while j < self.n and self.text[j] != "$":
            j += 2 if self.text[j] == "\\" else 1
        end = min(j + 1, self.n)
        self.mark(i, end)
        return end

    # --- code ---------------------------------------------------------------------

    def _hash_expression(self, i: int) -> int:
        """`#ident.path(args)[content]…`, `#(…)`, `#{…}` or a `#let`/`#set`/… line."""
        text = self.text
        j = i + 1
        ident = _IDENT.match(text, j)
        if ident is not None and ident.group() in _CODE_LINE_KEYWORDS:
            return self._code_line(i)
        if ident is None and (j >= self.n or text[j] not in "({["):
            self.mark(i, j)  # a lone "#"
            return j
        self.mark(i, j)
        callee = ident.group() if ident is not None else None
        while j < self.n:
            ident = _IDENT.match(text, j)
            if ident is not None and (j == i + 1 or text[j - 1] == "."):
                self.mark(j, ident.end())
                j = ident.end()
            elif text[j] == "." and j + 1 < self.n and _IDENT.match(text, j + 1):
                self.mark(j, j + 1)
                j += 1
            elif text[j] in "({":
                j = self._code_group(j)
            elif text[j] == "[":
                self.mark(j, j + 1)
                j = self.markup_mode(j + 1, closing=True, expr_start=i, callee=callee)
            else:
                break
        return j

    def _code_line(self, i: int) -> int:
        """`#let x = …`, `#set …`, `#import …` etc.: code until the end of the line,
        continuing across lines while brackets are open."""
        j = i
        while j < self.n and self.text[j] != "\n":
            c = self.text[j]
            if c in "({":
                j = self._code_group(j)
            elif c == "[":
                self.mark(j, j + 1)
                j = self.markup_mode(j + 1, closing=True)
            elif c == '"':
                j = self._string(j)
            else:
                self.mark(j, j + 1)
                j += 1
        return j

    def _code_group(self, i: int) -> int:
        """Balanced `(…)` or `{…}` in code mode; `[…]` inside is content (prose)."""
        closing = {"(": ")", "{": "}"}[self.text[i]]
        self.mark(i, i + 1)
        j = i + 1
        while j < self.n:
            c = self.text[j]
            if c == closing:
                self.mark(j, j + 1)
                return j + 1
            if c in "({":
                j = self._code_group(j)
            elif c == "[":
                self.mark(j, j + 1)
                j = self.markup_mode(j + 1, closing=True)
            elif c == '"':
                j = self._string(j)
            elif c == "$":
                j = self._math(j)
            elif self.text.startswith("//", j):
                j = self._line_comment(j)
            elif self.text.startswith("/*", j):
                j = self._block_comment(j)
            else:
                self.mark(j, j + 1)
                j += 1
        return j

    def _string(self, i: int) -> int:
        j = i + 1
        while j < self.n and self.text[j] != '"':
            j += 2 if self.text[j] == "\\" else 1
        end = min(j + 1, self.n)
        self.mark(i, end)
        return end
