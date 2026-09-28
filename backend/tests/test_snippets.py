"""Every snippet in snippets.toml compiles with the pinned Typst (CLAUDE.md, Phase 2)."""

from pathlib import Path

import pytest
import typst

from typst_writer.config import SNIPPETS_PATH
from typst_writer.domain.errors import InvalidSnippetParamsError, UnknownSnippetError
from typst_writer.domain.models import Snippet
from typst_writer.infra.paths import WorkspaceGuard
from typst_writer.services.references import build_index
from typst_writer.services.snippets import SnippetService, apply_simple

SERVICE = SnippetService(SNIPPETS_PATH)
SIMPLE = [s for s in SERVICE.list() if s.kind != "dialog"]
HOSTILE_CAPTION = "Kosten #100 $5 *a* [b] ] @c <d> `e` \\f ~g //h /* i"
BIB = """@article{knuth1984,
  title = {Literate Programming},
  author = {Knuth, Donald},
  year = {1984},
}
"""
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
    '<rect width="40" height="20"/></svg>'
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "Arbeit"
    (root / "kapitel").mkdir(parents=True)
    (root / "bilder").mkdir()
    (root / "bilder" / "Logo (neu).svg").write_text(SVG, encoding="utf-8")
    (root / "quellen.bib").write_text(BIB, encoding="utf-8")
    (root / "main.typ").write_text(
        '#set heading(numbering: "1.1")\n= Titel\n#include "kapitel/eins.typ"\n'
        '#bibliography("quellen.bib")\n',
        encoding="utf-8",
    )
    (root / "kapitel" / "eins.typ").write_text("Text.\n", encoding="utf-8")
    return root


def compile_chapter(project: Path, chapter: str) -> None:
    """Compile the project with `chapter` as kapitel/eins.typ; fail on errors or warnings."""
    (project / "kapitel" / "eins.typ").write_text(chapter, encoding="utf-8")
    try:
        _, warnings = typst.Compiler(
            str(project / "main.typ"), root=str(project)
        ).compile_with_warnings(format="svg")
    except typst.TypstError as e:
        pytest.fail(f"does not compile:\n{chapter}\n{e.diagnostic}")
    assert [w.message for w in warnings] == [], chapter


def test_snippets_file_is_valid() -> None:
    ids = [s.id for s in SERVICE.list()]
    assert len(ids) == len(set(ids))
    groups = {s.group for s in SERVICE.list() if s.in_toolbar}
    assert {"heading", "bold", "italic", "list", "table", "figure", "equation"} <= groups
    assert {"reference", "footnote", "outline", "pagebreak"} <= groups


@pytest.mark.parametrize("snippet", SIMPLE, ids=lambda s: s.id)
def test_simple_snippet_compiles(project: Path, snippet: Snippet) -> None:
    if snippet.kind == "wrap":
        with_selection = apply_simple(snippet, selection="ausgewählter Text")
        empty = apply_simple(snippet)
        compile_chapter(project, f"Ein Satz mit {with_selection} und {empty} darin.\n")
    elif snippet.kind == "line_prefix":
        line = apply_simple(snippet, line="Eine Zeile")
        replaced = apply_simple(snippet, line="== Alte Überschrift")
        toggled = apply_simple(snippet, line=line)
        assert toggled == "Eine Zeile"
        compile_chapter(project, f"Absatz.\n\n{line}\n\n{replaced}\n")
    else:
        compile_chapter(project, f"Vorher.\n\n{apply_simple(snippet)}\n\nNachher.\n")


def render(project: Path, snippet_id: str, **params: object) -> str:
    guard = WorkspaceGuard(project)
    return SERVICE.render(snippet_id, dict(params), guard, build_index(guard, {}))


@pytest.mark.parametrize("header_row", [True, False])
@pytest.mark.parametrize("caption", ["Messwerte", HOSTILE_CAPTION, ""])
def test_table_compiles_and_is_referenceable(project: Path, header_row: bool, caption: str) -> None:
    code = render(
        project,
        "table",
        rows=2,
        columns=4,
        header_row=header_row,
        caption=caption,
        label="tab:werte",
    )
    compile_chapter(project, f"{code}\n\nSiehe @tab:werte.\n")


def test_large_table_compiles(project: Path) -> None:
    compile_chapter(project, render(project, "table", rows=200, columns=50, language="en-US"))


def test_figure_compiles_from_a_subfolder_chapter(project: Path) -> None:
    code = render(
        project, "figure", image="bilder/Logo (neu).svg", caption=HOSTILE_CAPTION, label="fig:logo"
    )
    assert 'image("/bilder/Logo (neu).svg", width: 80%)' in code
    compile_chapter(project, f"{code}\n\nSiehe @fig:logo.\n")


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"math": "a^2 + b^2 = c^2", "block": False}, "$a^2 + b^2 = c^2$"),
        ({"math": "sum_(i=1)^n i", "block": True}, "$ sum_(i=1)^n i $"),
        ({"math": "E = m c^2", "block": True, "label": "eq:energie"}, "#math.equation("),
    ],
)
def test_equation_compiles(project: Path, params: dict[str, object], expected: str) -> None:
    code = render(project, "equation", **params)
    assert code.startswith(expected)
    reference = "\n\nSiehe @eq:energie." if params.get("label") else ""
    compile_chapter(project, f"Formel: {code}{reference}\n")


def test_references_and_citations_compile(project: Path) -> None:
    table = render(project, "table", rows=1, columns=1, label="tab:a")
    ref = render(project, "reference", target="tab:a")
    cite = render(project, "reference", target="knuth1984")
    odd = render(project, "reference", target="odd key")
    assert (ref, cite) == ("@tab:a", "@knuth1984")
    assert odd == '#ref(label("odd key"))'
    compile_chapter(project, f"{table}\n\nSiehe {ref} und {cite}.\n")


def test_bibliography_snippet_compiles(project: Path) -> None:
    (project / "main.typ").write_text('#include "kapitel/eins.typ"\n', encoding="utf-8")
    code = render(project, "bibliography", file="quellen.bib")
    assert code == '#bibliography("/quellen.bib")'
    compile_chapter(project, f"Zitat @knuth1984.\n\n{code}\n")


@pytest.mark.parametrize(
    ("snippet_id", "params", "message"),
    [
        ("table", {"rows": 0}, "greater than or equal to 1"),
        ("table", {"columns": 51}, "less than or equal to 50"),
        ("table", {"label": "tab werte"}, "Labels may contain"),
        ("table", {"surprise": 1}, "Extra inputs"),
        ("figure", {"image": "../secret.svg"}, "outside the open folder"),
        ("figure", {"image": "quellen.bib"}, "is not an image"),
        ("figure", {"image": "bilder/fehlt.png"}, "is not an image"),
        ("equation", {"math": "$x$"}, "Leave out the $"),
        ("equation", {"math": "x", "block": False, "label": "eq:x"}, "Only block equations"),
        ("bibliography", {"file": "main.typ"}, "is not a .bib file"),
    ],
)
def test_invalid_params(
    project: Path, snippet_id: str, params: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidSnippetParamsError, match=message.replace("$", r"\$")):
        render(project, snippet_id, **params)


def test_duplicate_label_is_rejected(project: Path) -> None:
    (project / "kapitel" / "eins.typ").write_text(
        "#figure([x], caption: [a]) <tab:werte>\n", encoding="utf-8"
    )
    with pytest.raises(InvalidSnippetParamsError, match="already used"):
        render(project, "table", label="tab:werte")


def test_unknown_snippet(project: Path) -> None:
    with pytest.raises(UnknownSnippetError):
        render(project, "chart-3d")
    with pytest.raises(InvalidSnippetParamsError):
        apply_simple(SERVICE.get("table"))
