"""Typst code for the Format controls (font, size, line spacing).

- Font or size on a selection: `#text(size: 14pt)[selection]`; if the selection already is
  one `#text(...)[...]`, its argument is replaced or added instead of nesting.
- Line spacing on a selection: the selection grows to whole paragraphs, which are put in a
  scoped block `#[` `#set par(leading: …)` … `]` (or that block's value is updated).
- Nothing selected: a `#set text(…)` / `#set par(…)` rule at the top of the main file is
  added or updated.

A selection is only wrapped if both ends lie between tokens of the same markup (see
`ProseMap.owner`) and bold/italic markers inside it are balanced, so generated code never
cuts through a function call, maths, raw text or a comment. Offsets are Python indices.
"""

import re
from dataclasses import dataclass
from typing import Literal

from typst_writer.domain.errors import WorkspaceError
from typst_writer.domain.typst_prose import Frame, ProseMap, scan

TextAttribute = Literal["font", "size"]

_BLANK_LINE = re.compile(r"\n[ \t\r]*\n")
_SPACING_HEAD = re.compile(r"[ \t]*\n?[ \t]*#set par\(leading: ([^()\n,]+)\)")
_ARG_NAME = re.compile(r"\s*([A-Za-z_][\w-]*)\s*:")
_STRING = re.compile(r'"((?:\\.|[^"\\])*)"')
_PREAMBLE = re.compile(r"#(set|show|import|let)\b")


class CannotFormatError(WorkspaceError):
    """The selection cannot be formatted (the message says why and what to select)."""


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    insert: str


@dataclass(frozen=True)
class Current:
    font: str | None  # None: not set anywhere (Typst's default)
    size: str | None  # e.g. "14pt"
    leading: str | None  # e.g. "1.05em"


# --- helpers ---------------------------------------------------------------------------


def split_args(args: str) -> list[str]:
    """Top-level comma-separated arguments (strings and brackets respected), trimmed."""
    parts: list[str] = []
    depth, start, i = 0, 0, 0
    while i < len(args):
        c = args[i]
        if c == '"':
            match = _STRING.match(args, i)
            i = match.end() if match else len(args)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(args[start:i].strip())
            start = i + 1
        i += 1
    parts.append(args[start:].strip())
    return [p for p in parts if p]


def with_arg(args: list[str], name: str, value: str) -> list[str]:
    """`args` with `name: value` replacing an argument of that name, or appended."""
    result, replaced = [], False
    for arg in args:
        match = _ARG_NAME.match(arg)
        if match is not None and match.group(1) == name:
            if not replaced:
                result.append(f"{name}: {value}")
                replaced = True
            continue
        result.append(arg)
    return result if replaced else [*result, f"{name}: {value}"]


def arg_value(args: list[str], name: str) -> str | None:
    for arg in args:
        match = _ARG_NAME.match(arg)
        if match is not None and match.group(1) == name:
            return arg[match.end() :].strip()
    return None


def first_string(value: str | None) -> str | None:
    """`"Arial"` or `("Arial", "Noto")` -> Arial."""
    if value is None:
        return None
    match = _STRING.search(value)
    if match is None:
        return value
    return re.sub(r"\\(.)", r"\1", match.group(1))


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def frame_at(prose: ProseMap, index: int) -> int:
    """The markup frame at `index` (inside a token: the frame the token is in)."""
    i = min(max(index, 0), len(prose.owner) - 1)
    while i > 0 and prose.owner[i] < 0:
        i -= 1
    return max(prose.owner[i], 0)


def frame_end(prose: ProseMap, frame: int) -> int:
    """Index of the frame's closing "]" (end of text for the document)."""
    if frame == 0:
        return len(prose.text)
    return max(i for i, owner in enumerate(prose.owner) if owner == frame)


def frame_args(text: str, frame: Frame) -> list[str] | None:
    """The arguments of `#name(args)[` for a content block frame, if it has that shape."""
    if frame.expr_start < 0 or frame.opener < 1 or text[frame.opener - 1] != ")":
        return None
    head = text[frame.expr_start : frame.opener]
    open_paren = head.find("(")
    if open_paren < 0:
        return None
    return split_args(head[open_paren + 1 : -1])


def spacing_value(text: str, frame: Frame) -> re.Match[str] | None:
    """For a line-spacing block `#[ #set par(leading: X) …]`: the match of X."""
    if frame.callee is not None or frame.expr_start < 0 or frame.opener != frame.expr_start + 1:
        return None
    return _SPACING_HEAD.match(text, frame.opener + 1)


def check_wrappable(prose: ProseMap, start: int, end: int, what: str) -> int:
    """The frame both ends are in, or CannotFormatError."""
    frame = prose.owner[start]
    if frame < 0 or prose.owner[end] != frame:
        raise CannotFormatError(
            f"The selection cuts through code, maths or a comment. Select {what}."
        )
    for marker, name in (("*", "bold"), ("_", "italic")):
        count = sum(
            1 for i in range(start, end) if prose.text[i] == marker and prose.owner[i] == frame
        )
        if count % 2:
            raise CannotFormatError(f"Select the whole {name} part, including both {marker}.")
    return frame


# --- font and size on a selection --------------------------------------------------------


def _single_text_call(selection: str) -> tuple[int, list[str]] | None:
    """If `selection` is exactly one `#text(args)[...]`: (index of its "[", args)."""
    if not selection.startswith("#text(") or not selection.endswith("]"):
        return None
    inner = scan(selection)
    if any(inner.owner[i] == 0 for i in range(1, len(selection))):
        return None  # more than one element
    blocks = [f for f in inner.frames[1:] if f.parent == 0]
    if len(blocks) != 1 or blocks[0].callee != "text":
        return None
    args = frame_args(selection, blocks[0])
    return None if args is None else (blocks[0].opener, args)


def format_selection(text: str, start: int, end: int, name: TextAttribute, value: str) -> Edit:
    """Set `name` (font or size) to the Typst `value` on the selection."""
    start, end = _trim(text, start, end)
    if start >= end:
        raise CannotFormatError("Select some text first.")
    check_wrappable(scan(text), start, end, "whole words or whole elements")
    selection = text[start:end]
    existing = _single_text_call(selection)
    if existing is not None:
        opener, args = existing
        return Edit(start, start + opener, f"#text({', '.join(with_arg(args, name, value))})")
    return Edit(start, end, f"#text({name}: {value})[{selection}]")


# --- line spacing ------------------------------------------------------------------------


def space_paragraphs(text: str, start: int, end: int, leading: str) -> Edit:
    """Line spacing `leading` for the paragraphs the selection touches."""
    prose = scan(text)
    frame = frame_at(prose, start)
    info = prose.frames[frame]
    existing = spacing_value(text, info)
    if existing is not None and frame_at(prose, end) == frame:
        return Edit(existing.start(1), existing.end(1), leading)
    lower = info.opener + 1 if frame else 0
    upper = frame_end(prose, frame)
    blanks = [m for m in _BLANK_LINE.finditer(text, lower, upper)]
    para_start = max([m.end() for m in blanks if m.end() <= start], default=lower)
    para_end = min([m.start() for m in blanks if m.start() >= end], default=upper)
    para_start, para_end = _trim(text, para_start, para_end)
    if para_start >= para_end:
        raise CannotFormatError("Put the cursor in a paragraph or select paragraphs.")
    check_wrappable(prose, para_start, para_end, "paragraphs outside of figures and code")
    body = text[para_start:para_end]
    if body.startswith("#[") and body.endswith("]"):
        inner = scan(body)
        block = next((f for f in inner.frames[1:] if f.parent == 0), None)
        whole = not any(inner.owner[i] == 0 for i in range(1, len(body)))
        value = spacing_value(body, block) if block is not None and whole else None
        if value is not None:
            return Edit(para_start + value.start(1), para_start + value.end(1), leading)
    return Edit(para_start, para_end, f"#[\n#set par(leading: {leading})\n{body}\n]")


# --- whole document ------------------------------------------------------------------


def _set_rules(prose: ProseMap, function: str) -> list[re.Match[str]]:
    """Single-line `#set function(...)` rules of the document itself (not in blocks)."""
    pattern = re.compile(rf"^#set {function}\((.*)\)[ \t]*$", re.MULTILINE)
    return [m for m in pattern.finditer(prose.text) if prose.owner[m.start()] == 0]


def _preamble_end(prose: ProseMap) -> int:
    """Where a new set rule goes: after the leading #set/#show/#import/#let statements."""
    text, position, after = prose.text, 0, 0
    while position < len(text):
        line_end = text.find("\n", position)
        line_end = len(text) if line_end < 0 else line_end
        line = text[position:line_end].strip()
        if _PREAMBLE.match(line):
            end = line_end  # a statement may span lines while its brackets are open
            while end < len(text) and prose.owner[min(end + 1, len(text))] != 0:
                next_end = text.find("\n", end + 1)
                end = len(text) if next_end < 0 else next_end
            after = min(end + 1, len(text))
            position = after
        elif line == "" or line.startswith("//"):
            position = line_end + 1
        else:
            break
    return after


def set_document(text: str, function: Literal["text", "par"], name: str, value: str) -> Edit:
    """Add or update `#set function(name: value)` at the top of the (main) file."""
    prose = scan(text)
    rules = _set_rules(prose, function)
    with_name = [m for m in rules if arg_value(split_args(m.group(1)), name) is not None]
    candidates = with_name or rules
    if candidates:
        rule = candidates[-1]
        args = with_arg(split_args(rule.group(1)), name, value)
        return Edit(rule.start(1), rule.end(1), ", ".join(args))
    at = _preamble_end(prose)
    line = f"#set {function}({name}: {value})\n"
    if at == len(text) and text and not text.endswith("\n"):
        line = "\n" + line
    return Edit(at, at, line)


# --- what is in effect at the cursor ------------------------------------------------------


def _file_defaults(text: str, before: int | None) -> Current:
    prose = scan(text)
    font = size = leading = None
    for m in _set_rules(prose, "text"):
        if before is None or m.start() < before:
            args = split_args(m.group(1))
            font = first_string(arg_value(args, "font")) or font
            size = arg_value(args, "size") or size
    for m in _set_rules(prose, "par"):
        if before is None or m.start() < before:
            leading = arg_value(split_args(m.group(1)), "leading") or leading
    return Current(font, size, leading)


def current(text: str, offset: int, main_text: str | None, end: int | None = None) -> Current:
    """Font, size and leading in effect at `offset`: the innermost `#text(...)` and
    spacing blocks around it, then the file's own set rules before it, then the main
    file's (`main_text`, when this is a chapter). For a selection [offset, end) that is
    exactly one `#text(...)[...]`, its own arguments count."""
    if end is not None and end > offset:
        start, stop = _trim(text, offset, end)
        call = _single_text_call(text[start:stop])
        if call is not None:
            offset = start + call[0] + 1  # inside its content block
    prose = scan(text)
    font = size = leading = None
    frame = frame_at(prose, offset)
    while frame > 0:
        info = prose.frames[frame]
        if info.callee == "text" and (args := frame_args(text, info)) is not None:
            font = font or first_string(arg_value(args, "font"))
            size = size or arg_value(args, "size")
        elif (match := spacing_value(text, info)) is not None:
            leading = leading or match.group(1).strip()
        frame = info.parent
    for defaults in (_file_defaults(text, offset), *([] if main_text is None else [
        _file_defaults(main_text, None)
    ])):  # fmt: skip
        font, size = font or defaults.font, size or defaults.size
        leading = leading or defaults.leading
    return Current(font, size, leading)
