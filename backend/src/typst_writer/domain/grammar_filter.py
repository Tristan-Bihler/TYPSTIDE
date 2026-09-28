"""Drop rule-check findings that are caused by Typst markup, not by the text.

LTeX+ extracts prose from Typst with regular expressions. Around labels, captions and
block elements it glues text together that Typst keeps apart, which produces two kinds of
false alarms (found with backend/tests/fixtures/grammar_markup.typ):

- findings that touch markup, e.g. "space before the period" for `= Titel <sec:x>`;
- "capital letter mid-sentence" for the first word of a caption or of the paragraph after
  a figure, equation or code block, because the block's end is not seen as a sentence end.
"""

from dataclasses import dataclass

from typst_writer.domain.typst_prose import ProseMap

# Rules that complain about capitalisation in the middle of a sentence. At a block start
# there is no sentence before the word, so they are always wrong there.
MID_SENTENCE_CASE_RULES = frozenset({"DE_CASE", "EN_UPPER_CASE_MS", "UPPERCASE_AFTER_COMMA"})


@dataclass(frozen=True)
class Finding:
    start: int  # Python string indices
    end: int
    rule: str


def is_false_alarm(finding: Finding, prose: ProseMap) -> bool:
    if prose.is_markup(finding.start, finding.end):
        return True
    return finding.rule in MID_SENTENCE_CASE_RULES and finding.start in prose.block_starts
