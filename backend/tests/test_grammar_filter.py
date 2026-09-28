import pytest

from typst_writer.domain.grammar_filter import Finding, is_false_alarm
from typst_writer.domain.positions import TextPositions
from typst_writer.domain.typst_prose import ProseMap, scan


def markup_text(text: str, prose: ProseMap) -> str:
    """The text with every markup character replaced by "·" (for readable assertions)."""
    return "".join("·" if prose.markup[i] else c for i, c in enumerate(text))


def starts(text: str) -> list[str]:
    """The first word at every block start."""
    prose = scan(text)
    return [text[i:].split()[0] for i in sorted(prose.block_starts)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("= Titel <sec:a>\n", "··Titel········\n"),
        ("Wie in @fig:x gezeigt.", "Wie in ······ gezeigt."),
        ("siehe @knuth1984.", "siehe ··········."),
        ("mail@example.com", "mail@example.com"),
        ("Die Formel $E = m c^2$ gilt.", "Die Formel ··········· gilt."),
        ("Code `x()` hier", "Code ····· hier"),
        ("A // Kommentar\nB", "A ············\nB"),
        ("A /* x */ B", "A ······· B"),
        ("*fett* und _kursiv_", "·fett· und ·kursiv·"),
        ("Wort#footnote[Text der Fußnote.] weiter", "Wort··········Text der Fußnote.· weiter"),
        ('#image("a.png", width: 80%)', "···························"),
        ('#set text(lang: "de")\nText', "·····················\nText"),
        (
            '#figure(image("/b.svg"), caption: [Der Aufbau]) <fig:a>',
            "·" * 35 + "Der Aufbau" + "·" * 10,
        ),
        ("- Punkt\n+ Schritt\n1. Eins", "··Punkt\n··Schritt\n···Eins"),
        ("Ein \\#Zeichen", "Ein \\#Zeichen"),
        ("#{ let x = [inhalt] }", "············inhalt···"),
    ],
)
def test_markup_spans(text: str, expected: str) -> None:
    assert markup_text(text, scan(text)) == expected


def test_block_starts() -> None:
    text = (
        "Erster Satz geht\nweiter hier.\n\n"
        "= Überschrift\n"
        "- Listenpunkt\n\n"
        '#figure(\n  image("/b.svg"),\n  caption: [Beschriftung hier],\n) <fig:a>\n'
        "Danach kommt Text.\n"
        "Wie @fig:a. Neuer Satz, und noch\n"
        "siehe @knuth.\nNächste Zeile.\n"
        "$ x $\n\nAbsatz nach Formel."
    )
    assert starts(text) == [
        "Erster",
        "Überschrift",
        "Listenpunkt",
        "Beschriftung",
        "Danach",
        "Neuer",
        "Nächste",
        "Absatz",
    ]


def test_unterminated_constructs_do_not_crash() -> None:
    for text in ["#figure(", "$ x", "`code", "/* x", "#f[unclosed", '#image("x', "#", "@", "<"]:
        prose = scan(text)
        assert len(prose.markup) == len(text)


def test_positions_handle_emoji_crlf_and_the_end() -> None:
    text = "a😀b\r\nzweite\nx"
    positions = TextPositions(text)
    assert positions.index(0, 3) == 2  # after the emoji (2 UTF-16 units)
    assert positions.index(1, 0) == text.index("zweite")
    assert positions.index(1, 99) == text.index("\nx")  # clamped to the line end
    assert positions.index(9, 0) == len(text)
    assert positions.utf16_offset(3) == 4
    assert positions.line_column(text.index("x")) == (3, 1)


def _finding(text: str, word: str, rule: str, occurrence: int = 0) -> Finding:
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(word, start + 1)
    return Finding(start, start + len(word), rule)


def test_false_alarms_found_with_ltex_are_dropped() -> None:
    text = (
        "= Einleitung <sec:einleitung>\n\n"
        '#figure(\n  image("/b.svg"),\n  caption: [Der Aufbau],\n) <fig:a>\n\n'
        "Die Messung ist gut, siehe @knuth1984. Die Werte stimmen.\n"
    )
    prose = scan(text)
    label = text.index(" <sec:")
    assert is_false_alarm(Finding(label, label + 18, "COMMA_PARENTHESIS_WHITESPACE"), prose)
    assert is_false_alarm(_finding(text, "Der", "DE_CASE"), prose)
    assert is_false_alarm(_finding(text, "Die", "DE_CASE"), prose)
    assert is_false_alarm(_finding(text, "Die", "DE_CASE", occurrence=1), prose)


def test_real_errors_next_to_markup_are_kept() -> None:
    text = (
        "Das ist ein ein Fehler, siehe @fig:a.\n\n"
        '#figure(image("/b.svg"), caption: [Der Aufbau im Labr]) <fig:a>\n\n'
        "Der Versuch zeigt, dass Die Werte stimmen.\n"
    )
    prose = scan(text)
    assert not is_false_alarm(_finding(text, "ein ein", "GERMAN_WORD_REPEAT_RULE"), prose)
    assert not is_false_alarm(_finding(text, "Labr", "GERMAN_SPELLER_RULE"), prose)
    # Mid-sentence capital letter that is not at a block start: a real finding.
    assert not is_false_alarm(_finding(text, "Die", "DE_CASE"), prose)
    # Other rules at a block start are kept.
    assert not is_false_alarm(_finding(text, "Der", "GERMAN_SPELLER_RULE"), prose)
