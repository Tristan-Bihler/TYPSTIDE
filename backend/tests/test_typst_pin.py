"""The pinned Typst version compiles to both preview (SVG) and export (PDF) formats."""

import typst

from typst_writer.adapters.typst_py import typst_version

SOURCE = b"""= Einleitung

Dieses Kapitel beschreibt $a^2 + b^2 = c^2$.

#pagebreak()

= Second page
"""


def test_bundled_typst_matches_pin() -> None:
    assert typst_version() == "0.15.0"


def test_compiles_svg_pages() -> None:
    pages = typst.compile(SOURCE, format="svg")
    assert isinstance(pages, list)
    assert len(pages) == 2
    assert all(page.startswith(b"<svg") for page in pages)


def test_compiles_pdf() -> None:
    pdf = typst.compile(SOURCE, format="pdf")
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF-")
