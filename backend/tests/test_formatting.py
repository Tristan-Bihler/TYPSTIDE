"""Format controls: font, size and line spacing. Every generated result is compiled."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
import typst
from fastapi.testclient import TestClient

from typst_writer.config import SNIPPETS_PATH
from typst_writer.domain.formatting import (
    CannotFormatError,
    Edit,
    current,
    format_selection,
    set_document,
    space_paragraphs,
)
from typst_writer.services.formatting import FormattingService

DOC = (
    '#set text(lang: "de")\n#set heading(numbering: "1.")\n= Titel <sec:t>\n\n'
    "Das ist ein *wichtiger* Satz mit $x^2$ und @sec:t.\n"
    "Er geht auf der nächsten Zeile weiter.\n\n"
    "#figure(rect(width: 1cm), caption: [Ein _kleines_ Bild]) <fig:a>\n\n"
    "Zweiter Absatz // mit Kommentar\nund Text.\n"
)


def apply(text: str, edit: Edit) -> str:
    return text[: edit.start] + edit.insert + text[edit.end :]


Compiles = Callable[[str], str]


@pytest.fixture
def compiles(tmp_path: Path) -> Compiles:
    def check(source: str) -> str:
        (tmp_path / "main.typ").write_text(source, encoding="utf-8")
        typst.compile(str(tmp_path / "main.typ"), root=str(tmp_path))  # raises on errors
        return source

    return check


def at(text: str, needle: str, length: int | None = None) -> tuple[int, int]:
    start = text.index(needle)
    return start, start + (len(needle) if length is None else length)


# --- selection ---------------------------------------------------------------------------


def test_size_and_font_wrap_the_selection(compiles: Compiles) -> None:
    start, end = at(DOC, " *wichtiger* ")  # surrounding spaces are left outside
    result = compiles(apply(DOC, format_selection(DOC, start, end, "size", "14pt")))
    assert "Das ist ein #text(size: 14pt)[*wichtiger*] Satz" in result
    start, end = at(result, "#text(size: 14pt)[*wichtiger*]")
    merged = compiles(apply(result, format_selection(result, start, end, "font", '"DejaVu Sans"')))
    assert '#text(size: 14pt, font: "DejaVu Sans")[*wichtiger*]' in merged
    start, end = at(merged, '#text(size: 14pt, font: "DejaVu Sans")[*wichtiger*]')
    resized = compiles(apply(merged, format_selection(merged, start, end, "size", "9pt")))
    assert '#text(size: 9pt, font: "DejaVu Sans")[*wichtiger*]' in resized


def test_selections_over_lines_math_figures_and_captions(compiles: Compiles) -> None:
    for needle in [
        "Satz mit $x^2$ und @sec:t.\nEr geht",
        "#figure(rect(width: 1cm), caption: [Ein _kleines_ Bild]) <fig:a>",
        "_kleines_",  # inside the caption's content block
        "wich",  # inside bold
    ]:
        start, end = at(DOC, needle)
        compiles(apply(DOC, format_selection(DOC, start, end, "size", "12pt")))


@pytest.mark.parametrize(
    ("needle", "length", "why"),
    [
        ("$x^2$", 3, "cuts through code"),
        ("width: 1cm", None, "cuts through code"),
        ("*wichtiger* Satz", 5, "whole bold part"),
        ("_kleines_ Bild", 4, "whole italic part"),
        ("Kommentar\nund", None, "cuts through code, maths or a comment"),
        ("   ", None, "Select some text"),
    ],
)
def test_selections_that_would_break_markup_are_refused(
    needle: str, length: int | None, why: str
) -> None:
    text = DOC + "   "
    start, end = at(text, needle, length)
    with pytest.raises(CannotFormatError, match=why):
        format_selection(text, start, end, "size", "12pt")


def test_font_names_are_escaped(compiles: Compiles) -> None:
    start, end = at(DOC, "Zweiter")
    result = apply(DOC, format_selection(DOC, start, end, "font", '"A \\"B\\" \\\\ C"'))
    compiles(result)  # an unknown font only falls back; the code stays valid


# --- line spacing ------------------------------------------------------------------------


def test_line_spacing_covers_whole_paragraphs_and_updates_in_place(compiles: Compiles) -> None:
    start, end = at(DOC, "wichtiger", 4)
    spaced = compiles(apply(DOC, space_paragraphs(DOC, start, end, "1.05em")))
    assert (
        "#[\n#set par(leading: 1.05em)\nDas ist ein *wichtiger* Satz mit $x^2$ und @sec:t.\n"
        "Er geht auf der nächsten Zeile weiter.\n]" in spaced
    )
    # Again, from anywhere inside: the value changes, no second block.
    start, end = at(spaced, "nächsten", 3)
    again = compiles(apply(spaced, space_paragraphs(spaced, start, end, "1.65em")))
    assert again.count("#set par(leading:") == 1
    assert "#set par(leading: 1.65em)" in again
    # Selecting the whole block also updates it.
    start = again.index("#[")
    end = again.index("weiter.\n]") + len("weiter.\n]")
    third = compiles(apply(again, space_paragraphs(again, start, end, "0.5em")))
    assert third.count("#set par(leading:") == 1 and "leading: 0.5em" in third


def test_line_spacing_over_several_paragraphs(compiles: Compiles) -> None:
    start = DOC.index("Satz mit")
    end = DOC.index("und Text")
    spaced = compiles(apply(DOC, space_paragraphs(DOC, start, end, "1.05em")))
    block = spaced[spaced.index("#[") :]
    assert block.startswith("#[\n#set par(leading: 1.05em)\nDas ist ein")
    assert block.endswith("und Text.\n]\n")


def test_line_spacing_in_a_caption_stays_inside_it(compiles: Compiles) -> None:
    start, end = at(DOC, "kleines", 3)
    result = compiles(apply(DOC, space_paragraphs(DOC, start, end, "1.05em")))
    assert "caption: [#[\n#set par(leading: 1.05em)\nEin _kleines_ Bild\n]]" in result


def test_measured_line_spacing_matches_word(tmp_path: Path) -> None:
    """Baseline distance (em) of the configured leadings, with Typst's own serif font."""
    options = {o.label: o.leading for o in FormattingService(SNIPPETS_PATH).options().line_spacing}
    probes = "\n".join(
        f"#context [#metadata((label: {json.dumps(label)}, step: (measure(block(width: 8cm)["
        f"#set text(size: 10pt); #set par(leading: {leading}); A \\ A]).height - "
        f"measure(block(width: 8cm)[#set text(size: 10pt); A]).height).pt()))<m>]"
        for label, leading in options.items()
    )
    (tmp_path / "m.typ").write_text(probes, encoding="utf-8")
    raw = typst.query(str(tmp_path / "m.typ"), "<m>", field="value", root=str(tmp_path))
    steps = {m["label"]: m["step"] / 10 for m in json.loads(raw)}
    word_single = 1.15  # em, Times-like fonts
    for label, step in steps.items():
        assert step == pytest.approx(word_single * float(label), abs=0.03), (label, step)


# --- whole document ------------------------------------------------------------------


def test_document_defaults_are_added_or_updated(compiles: Compiles) -> None:
    sized = compiles(apply(DOC, set_document(DOC, "text", "size", "12pt")))
    assert sized.startswith('#set text(lang: "de", size: 12pt)\n')
    resized = compiles(apply(sized, set_document(sized, "text", "size", "14pt")))
    assert resized.count("size:") == 1 and "size: 14pt" in resized
    spaced = compiles(apply(resized, set_document(resized, "par", "leading", "1.05em")))
    assert '#set heading(numbering: "1.")\n#set par(leading: 1.05em)\n= Titel' in spaced


def test_document_defaults_go_after_a_template(compiles: Compiles) -> None:
    text = "#let doc(body) = {\n  set text(size: 9pt)\n  body\n}\n#show: doc.with()\n\nText."
    result = compiles(apply(text, set_document(text, "text", "font", '"DejaVu Sans"')))
    assert result.endswith('#show: doc.with()\n#set text(font: "DejaVu Sans")\n\nText.')
    plain = "Nur Text."
    assert apply(plain, set_document(plain, "text", "size", "12pt")) == (
        "#set text(size: 12pt)\nNur Text."
    )


# --- current values --------------------------------------------------------------------


def test_current_values_at_the_cursor() -> None:
    main = '#set text(font: ("DejaVu Sans", "Noto"), size: 12pt)\n#include "k.typ"\n'
    chapter = (
        "#set par(leading: 0.5em)\nA\n\n#[\n#set par(leading: 1.05em)\n"
        'B #text(size: 16pt)[C *#text(font: "X")[D]*] E\n]\n'
    )
    assert current(chapter, chapter.index("A"), main).__dict__ == {
        "font": "DejaVu Sans",
        "size": "12pt",
        "leading": "0.5em",
    }
    assert current(chapter, chapter.index("C"), main).size == "16pt"
    inner = current(chapter, chapter.index("D"), main)
    assert (inner.font, inner.size, inner.leading) == ("X", "16pt", "1.05em")
    assert current("Text", 2, None).__dict__ == {"font": None, "size": None, "leading": None}


# --- API --------------------------------------------------------------------------------


def test_options_list_typsts_fonts_builtin_first(client: TestClient) -> None:
    options = client.get("/api/format/options").json()
    fonts = options["fonts"]
    builtin = [f["family"] for f in fonts if f["builtin"]]
    assert {"Libertinus Serif", "New Computer Modern", "DejaVu Sans Mono"} <= set(builtin)
    assert [f["builtin"] for f in fonts] == sorted((f["builtin"] for f in fonts), reverse=True)
    assert options["default_size"] == 11 and 10.5 in options["sizes"]
    assert [s["label"] for s in options["line_spacing"]] == ["1.0", "1.15", "1.5", "2.0"]


def test_apply_uses_utf16_offsets_and_checks_values(client: TestClient) -> None:
    content = "😀 Hallo Welt"
    body = {"content": content, "start": 3, "end": 8, "change": {"kind": "size", "value": "14"}}
    edit = client.post("/api/format/apply", json=body).json()
    assert edit == {"start": 3, "end": 8, "insert": "#text(size: 14pt)[Hallo]"}
    for change, code in [
        ({"kind": "font", "value": "Comic Sans Fantasy"}, "cannot_format"),
        ({"kind": "size", "value": "200"}, "cannot_format"),
        ({"kind": "size", "value": "big"}, "cannot_format"),
        ({"kind": "line_spacing", "value": "3.0"}, "cannot_format"),
    ]:
        refused = client.post("/api/format/apply", json={**body, "change": change})
        assert refused.status_code == 422 and refused.json()["code"] == code, change
    bad = client.post("/api/format/apply", json={**body, "change": {"kind": "color", "value": "x"}})
    assert bad.status_code == 422
    cut = {**body, "content": "a $x + y$ b", "start": 3, "end": 6}
    assert client.post("/api/format/apply", json=cut).json()["code"] == "cannot_format"


def test_document_and_current_endpoints(client: TestClient) -> None:
    change = {"kind": "font", "value": "Libertinus Serif"}
    edit = client.post("/api/format/document", json={"content": "= A\n", "change": change})
    assert edit.json() == {"start": 0, "end": 0, "insert": '#set text(font: "Libertinus Serif")\n'}
    spacing = {"kind": "line_spacing", "value": "1.5"}
    edit = client.post("/api/format/document", json={"content": "", "change": spacing}).json()
    assert edit["insert"] == "#set par(leading: 1.05em)\n"
    found = client.post(
        "/api/format/current",
        json={"content": "x", "offset": 1, "main_content": "#set text(size: 12pt)\n"},
    ).json()
    assert found == {"font": None, "size": "12pt", "leading": None}
