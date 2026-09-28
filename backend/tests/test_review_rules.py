"""CLAUDE.md AI rules: markup preservation, unique location, overlaps, offsets."""

import pytest

from typst_writer.domain.review import (
    ProposedChange,
    locate_changes,
    markup_tokens,
    preserves_markup,
    rebuild,
    to_suggestions,
)

SELECTION = 'Siehe @tab:werte und $a^2$ in #figure(image("/x.svg")) <fig:x>. Das ist gut.'


def change(original: str, replacement: str) -> ProposedChange:
    return ProposedChange(original, replacement, reason="r", category="style")


def test_markup_tokens() -> None:
    assert set(markup_tokens(SELECTION)) == {"@tab:werte", "$a^2$", "#figure", "<fig:x>"}
    assert set(markup_tokens("`raw #x` und ```\n#code\n```")) == {"`raw #x`", "```\n#code\n```"}


@pytest.mark.parametrize(
    ("original", "replacement", "ok"),
    [
        ("Das ist gut.", "Das ist sehr gut.", True),
        ("Siehe @tab:werte", "Vergleiche @tab:werte", True),
        ("Siehe @tab:werte", "Siehe Tabelle 1", False),  # reference removed
        ("$a^2$", "$a^3$", False),  # math changed
        ("<fig:x>", "<fig:y>", False),  # label changed
        ("Das ist gut.", "Das ist #strong[gut].", False),  # new code added
    ],
)
def test_preserves_markup(original: str, replacement: str, ok: bool) -> None:
    assert preserves_markup(original, replacement) is ok


def test_locate_keeps_safe_unique_changes_and_counts_dropped() -> None:
    proposed = [
        change("Das ist gut.", "Das ist sehr gut."),
        change("Siehe @tab:werte", "Siehe Tabelle"),  # markup lost
        change("nicht vorhanden", "x"),  # not in selection
        change("und", "sowie"),  # "und" occurs once? no: also inside "Siehe ... und" only once
        change("", "x"),  # empty
        change("gut", "gut"),  # no-op
    ]
    kept, dropped = locate_changes(SELECTION, proposed)
    assert [k.change.original for k in kept] == ["und", "Das ist gut."]
    assert dropped == 4


def test_ambiguous_and_overlapping_changes_are_dropped() -> None:
    text = "eins zwei eins drei"
    kept, dropped = locate_changes(
        text, [change("eins", "1"), change("zwei eins", "2 1"), change("eins drei", "1 3")]
    )
    # "eins" is ambiguous; "zwei eins" and "eins drei" overlap: the later one is dropped.
    assert [k.change.original for k in kept] == ["zwei eins"]
    assert dropped == 2


def test_rebuild_and_utf16_offsets() -> None:
    text = "Ein 😀 Satz mit Fehlr."
    kept, _ = locate_changes(text, [change("Fehlr", "Fehler")])
    assert rebuild(text, kept) == "Ein 😀 Satz mit Fehler."
    [suggestion] = to_suggestions(text, selection_start=100, kept=kept)
    # The emoji is 1 code point but 2 UTF-16 units, so the offset is shifted by one.
    assert (suggestion.start, suggestion.end) == (100 + 16, 100 + 21)
    assert suggestion.source == "claude"
