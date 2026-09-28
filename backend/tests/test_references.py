"""Workspace index for the insert dialogs, and the snippet/reference endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient

from typst_writer.infra.paths import WorkspaceGuard
from typst_writer.services.references import build_index, scan_bib, scan_typst

CHAPTER = """== Einleitung <sec:einleitung>
Text mit `<nicht:label>` im Code, // Kommentar <auch:nicht>
/* Block <nein:nein> */
#link("https://example.org")[Link] und "<im:string>".

#figure(
  table(columns: 2, [a], [b]),
  caption: [Messwerte \\[kalibriert\\]],
) <tab:messwerte>

#figure(image("/bilder/logo.svg"), caption: [Das Logo]) <fig:logo>
#math.equation(block: true, numbering: "(1)", $ x $) <eq:x>
Ein Absatz <frei>
"""

BIB = """@comment{ignoriert}
@article{knuth1984,
  title = {Literate Programming},
  year = {1984},
}
@book{müller:2020,
  title = "Schreiben lernen",
}
"""


def test_scan_typst_finds_labels_with_kind_and_description() -> None:
    targets, has_call = scan_typst(CHAPTER, "kapitel/eins.typ")
    found = {t.key: (t.kind, t.line, t.description) for t in targets}
    assert found == {
        "sec:einleitung": ("heading", 1, "Einleitung"),
        "tab:messwerte": ("table", 9, "Messwerte [kalibriert]"),
        "fig:logo": ("figure", 11, "Das Logo"),
        "eq:x": ("equation", 12, '#math.equation(block: true, numbering: "(1)", $ x $) <eq:x>'),
        "frei": ("label", 13, "Ein Absatz <frei>"),
    }
    assert has_call is False
    assert scan_typst('#bibliography("refs.bib")', "main.typ")[1] is True
    assert scan_typst('// #bibliography("refs.bib")', "main.typ")[1] is False


def test_scan_bib() -> None:
    targets = scan_bib(BIB, "quellen.bib")
    assert [(t.key, t.description, t.line) for t in targets] == [
        ("knuth1984", "Literate Programming", 2),
        ("müller:2020", "Schreiben lernen", 6),
    ]


def test_build_index_uses_unsaved_buffers(tmp_path: Path) -> None:
    (tmp_path / "bilder").mkdir()
    (tmp_path / "bilder" / "a.PNG").write_bytes(b"x")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "b.png").write_bytes(b"x")
    (tmp_path / "main.typ").write_text("<alt:label>", encoding="utf-8")
    (tmp_path / "quellen.bib").write_text(BIB, encoding="utf-8")
    index = build_index(WorkspaceGuard(tmp_path), {"main.typ": "<neu:label>"})
    assert index.images == ["bilder/a.PNG"]
    assert index.bibliographies == ["quellen.bib"]
    assert index.labels() == {"neu:label"}
    assert {t.key for t in index.targets if t.kind == "citation"} == {"knuth1984", "müller:2020"}


def test_snippets_endpoint(client: TestClient) -> None:
    snippets = client.get("/api/snippets").json()
    assert snippets[0]["id"] == "heading-1"
    assert {"table", "figure", "equation", "reference"} <= {s["dialog"] for s in snippets}


def test_render_endpoint_checks_labels_against_unsaved_buffers(opened: TestClient) -> None:
    body = {"params": {"rows": 1, "columns": 2, "label": "tab:a"}}
    ok = opened.post("/api/snippets/table/render", json=body)
    assert ok.status_code == 200
    assert ok.json()["code"].startswith("#figure(")

    clash = opened.post(
        "/api/snippets/table/render",
        json={**body, "overlays": {"chapters/intro.typ": "#figure([x]) <tab:a>"}},
    )
    assert (clash.status_code, clash.json()["code"]) == (422, "invalid_params")
    assert "already used" in clash.json()["detail"]


def test_render_endpoint_errors(opened: TestClient) -> None:
    unknown = opened.post("/api/snippets/chart-3d/render", json={})
    assert (unknown.status_code, unknown.json()["code"]) == (404, "unknown_snippet")
    outside = opened.post("/api/snippets/figure/render", json={"params": {"image": "../x.png"}})
    assert outside.status_code == 422
    overlay = opened.post("/api/snippets/table/render", json={"overlays": {"../x.typ": ""}})
    assert overlay.status_code == 403


def test_references_endpoint(opened: TestClient, workspace: Path) -> None:
    (workspace / "images" / "plot.svg").write_text("<svg/>", encoding="utf-8")
    index = opened.post(
        "/api/workspace/references",
        json={"overlays": {"chapters/intro.typ": "#figure([x], caption: [Plot]) <fig:plot>"}},
    ).json()
    assert index["images"] == ["images/plot.svg"]
    assert [(t["key"], t["kind"], t["description"]) for t in index["targets"]] == [
        ("fig:plot", "figure", "Plot")
    ]
    assert index["has_bibliography_call"] is False


def test_references_need_a_workspace(client: TestClient) -> None:
    assert client.post("/api/workspace/references", json={}).status_code == 409
