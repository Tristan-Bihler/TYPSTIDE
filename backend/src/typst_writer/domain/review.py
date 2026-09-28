"""Rules for AI-proposed changes (CLAUDE.md, "Rules for AI adapters").

AI output is untrusted: a change is kept only if it leaves all Typst markup intact and its
`original` text occurs exactly once in the selection; overlapping changes are dropped.
The revised text is rebuilt from the kept changes, so what the user reviews is exactly what
gets applied.
"""

import re
from collections import Counter
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from typst_writer.domain.models import Suggestion

# Raw blocks, inline raw, math, code/function calls, references and labels.
_MARKUP_TOKEN = re.compile(
    r"```.*?```|`[^`\n]*`|\$[^$]*\$|#[A-Za-z_][\w.-]*|@[\w:.-]*\w|<[\w:.-]+>", re.DOTALL
)


class ProposedChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    original: str
    replacement: str
    reason: str
    category: str


@dataclass(frozen=True)
class LocatedChange:
    start: int  # code-point index in the selection
    change: ProposedChange

    @property
    def end(self) -> int:
        return self.start + len(self.change.original)


def markup_tokens(text: str) -> Counter[str]:
    return Counter(_MARKUP_TOKEN.findall(text))


def preserves_markup(original: str, replacement: str) -> bool:
    """True if the replacement keeps every markup token and adds none."""
    return markup_tokens(original) == markup_tokens(replacement)


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def locate_changes(
    selection: str, proposed: list[ProposedChange]
) -> tuple[list[LocatedChange], int]:
    """Keep safe, uniquely locatable, non-overlapping changes. Returns (kept, dropped)."""
    candidates: list[LocatedChange] = []
    dropped = 0
    for change in proposed:
        if (
            not change.original
            or change.original == change.replacement
            or not preserves_markup(change.original, change.replacement)
            or selection.count(change.original) != 1
        ):
            dropped += 1
            continue
        candidates.append(LocatedChange(selection.index(change.original), change))
    kept: list[LocatedChange] = []
    for located in sorted(candidates, key=lambda c: c.start):
        if kept and located.start < kept[-1].end:
            dropped += 1
            continue
        kept.append(located)
    return kept, dropped


def rebuild(selection: str, kept: list[LocatedChange]) -> str:
    parts: list[str] = []
    position = 0
    for located in kept:
        parts.append(selection[position : located.start])
        parts.append(located.change.replacement)
        position = located.end
    parts.append(selection[position:])
    return "".join(parts)


def to_suggestions(
    selection: str, selection_start: int, kept: list[LocatedChange]
) -> list[Suggestion]:
    """Suggestions with UTF-16 document offsets (selection_start is already UTF-16)."""
    return [
        Suggestion(
            id=f"claude-{i}",
            source="claude",
            start=selection_start + utf16_len(selection[: located.start]),
            end=selection_start + utf16_len(selection[: located.end]),
            original=located.change.original,
            replacement=located.change.replacement,
            reason=located.change.reason,
            category=located.change.category,
        )
        for i, located in enumerate(kept)
    ]
