"""Drop rule-check findings that are caused by Typst markup, not by the text.

LTeX+ extracts prose from Typst with regular expressions. Around labels, captions and
block elements it glues text together that Typst keeps apart, which produces two kinds of
false alarms (found with backend/tests/fixtures/grammar_markup.typ):

- findings that touch markup, e.g. "space before the period" for `= Titel <sec:x>`;
- "capital letter mid-sentence" for the first word of a caption or of the paragraph after
  a figure, equation or code block, because the block's end is not seen as a sentence end;
- "unpaired bracket" for `(siehe @fig:a).`, because LTeX+ takes the `).` as part of the
  reference.
"""

from dataclasses import dataclass

from typst_writer.domain.typst_prose import ProseMap

# Rules that complain about capitalisation in the middle of a sentence. At a block start
# there is no sentence before the word, so they are always wrong there.
MID_SENTENCE_CASE_RULES = frozenset({"DE_CASE", "EN_UPPER_CASE_MS", "UPPERCASE_AFTER_COMMA"})


_CLOSING = {"(": ")", "[": "]", "{": "}"}


@dataclass(frozen=True)
class Finding:
    start: int  # Python string indices
    end: int
    rule: str


def is_false_alarm(finding: Finding, prose: ProseMap) -> bool:
    if prose.is_markup(finding.start, finding.end):
        return True
    if finding.rule in MID_SENTENCE_CASE_RULES and finding.start in prose.block_starts:
        return True
    return "UNPAIRED" in finding.rule and _partner_swallowed(finding, prose)


def _partner_swallowed(finding: Finding, prose: ProseMap) -> bool:
    """Whether the bracket's closing partner exists but is glued to a reference."""
    text = prose.text
    opening = text[finding.start : finding.end]
    closing = _CLOSING.get(opening)
    if closing is None:
        return False
    depth = 0
    end = text.find("\n\n", finding.end)
    for j in range(finding.end, len(text) if end < 0 else end):
        if text[j] == opening:
            depth += 1
        elif text[j] == closing:
            if depth == 0:
                return bool(prose.swallowed[j])
            depth -= 1
    return False
