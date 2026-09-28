import json

import pytest
import typst

from typst_writer.domain.typst_text import (
    escape_markup,
    escape_string,
    is_label,
    make_label,
    slugify,
)

HOSTILE = [
    "Kosten #100 und $5",
    "*fett* _kursiv_ `raw` ~",
    "Klammern [a] ] und [",
    "@ref <label> \\backslash",
    "URL https://example.org // Kommentar /* Block",
    "= keine Überschrift - kein Punkt + kein Schritt",
    "- kein Listenpunkt",
    "+ kein Schritt",
    "1. Platz am 12. Mai",
    "2026",
    "Zeile 1\nZeile 2",
]


def rendered_caption(caption: str) -> str:
    """The plain text Typst renders for a caption built with escape_markup."""
    source = f"#figure([x], caption: [{escape_markup(caption)}]) <f>"
    value = json.loads(typst.query(source.encode(), "<f>", field="caption", one=True))
    body = value["body"]
    children = body["children"] if body["func"] == "sequence" else [body]
    return "".join(" " if c["func"] == "space" else c["text"] for c in children)


@pytest.mark.parametrize("text", HOSTILE)
def test_escaped_text_renders_exactly_as_typed(text: str) -> None:
    assert rendered_caption(text) == " ".join(text.split())


def test_escape_string() -> None:
    assert escape_string('a "b" \\c') == 'a \\"b\\" \\\\c'


def test_labels() -> None:
    assert is_label("tab:messwerte")
    assert is_label("fig:größe_2.b-c")
    assert not is_label("tab messwerte")
    assert not is_label("_x")
    assert not is_label("")


def test_slugify() -> None:
    assert slugify("Messwerte (Übersicht) für März") == "messwerte-uebersicht-fuer-maerz"
    assert slugify("   ") == ""
    assert len(slugify("a" * 100)) == 40


def test_make_label_is_unique() -> None:
    existing = {"tab:messwerte", "tab:messwerte-2"}
    assert make_label("tab", "Messwerte", existing) == "tab:messwerte-3"
    assert make_label("fig", "", set()) == "fig:fig"
