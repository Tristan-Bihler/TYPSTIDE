"""Click-to-jump: markers from the real Typst compile, matched to the source."""

import json
from pathlib import Path

import pytest
import typst

from typst_writer.services import source_map

from helpers import FRONTEND_ORIGIN, WS_URL, app_client, receive_until

MAIN = (
    '#set page(height: 12cm)\n#set heading(numbering: "1.1")\n'
    "= Einleitung <sec:a>\n\n"
    "Der erste Absatz steht im Hauptdokument und ist *wichtig* für den Test.\n\n"
    '#include "kapitel/a.typ"\n\n'
    "Wiederholter Absatz mit genau diesem Text.\n"
)
CHAPTER = (
    "== Kapitel\n\n"
    "Ein Absatz im Kapitel verweist auf @sec:a und bleibt lesbar.\n\n"
    "#pagebreak()\n\n"
    "Wiederholter Absatz mit genau diesem Text.\n\n"
    "Der letzte Absatz des Kapitels ist lang genug, um mehrere Zeilen zu füllen, "
    "damit ein Klick in der Mitte auch in der Mitte des Quelltextes landet, "
    "und zwar ungefähr bei diesem Wort hier.\n"
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "kapitel").mkdir(parents=True)
    (root / "main.typ").write_text(MAIN, encoding="utf-8")
    (root / "kapitel" / "a.typ").write_text(CHAPTER, encoding="utf-8")
    return root


def _map(root: Path) -> source_map.SourceMap:
    wrapper = root / source_map.WRAPPER_NAME
    wrapper.write_text(source_map.wrapper_source("main.typ"), encoding="utf-8")
    raw = typst.query(str(wrapper), source_map.SELECTOR, field="value", root=str(root))
    files = {"main.typ": MAIN, "kapitel/a.typ": CHAPTER}
    return source_map.build(raw if isinstance(raw, str) else raw.decode(), "main.typ", files.get)


def test_markers_do_not_change_the_layout(project: Path) -> None:
    wrapper = project / source_map.WRAPPER_NAME
    wrapper.write_text(source_map.wrapper_source("main.typ"), encoding="utf-8")
    plain = typst.compile(str(project / "main.typ"), format="svg", root=str(project))
    marked = typst.compile(str(wrapper), format="svg", root=str(project))
    assert plain == marked


def test_every_paragraph_and_heading_is_matched_in_order(project: Path) -> None:
    mapping = _map(project)
    matched = [(p.block.path, p.marker.page, p.marker.text[:12]) for p in mapping.pairs]
    assert matched == [
        ("main.typ", 1, "Einleitung"),
        ("main.typ", 1, "Der erste Ab"),
        ("kapitel/a.typ", 1, "Kapitel"),
        ("kapitel/a.typ", 1, "Ein Absatz i"),
        ("kapitel/a.typ", 2, "Wiederholter"),
        ("kapitel/a.typ", 2, "Der letzte A"),
        ("main.typ", 2, "Wiederholter"),  # the same text again: the one in main.typ
    ]


def test_click_to_source_and_back(project: Path) -> None:
    mapping = _map(project)
    pairs = mapping.pairs
    chapter_par = pairs[3]
    path, index = mapping.to_source(chapter_par.marker.page, chapter_par.marker.y + 1) or ("", -1)
    assert (path, index) == ("kapitel/a.typ", CHAPTER.index("Ein Absatz"))
    # A click halfway down the long paragraph lands mid-paragraph, at a word start.
    long_par, after = pairs[5], pairs[6]
    assert after.marker.page == long_par.marker.page
    middle = (long_par.marker.y + after.marker.y) / 2
    path, index = mapping.to_source(long_par.marker.page, middle) or ("", -1)
    start, end = long_par.block.start, long_par.block.end
    assert path == "kapitel/a.typ"
    assert start + (end - start) // 4 < index < end - (end - start) // 4
    assert CHAPTER[index - 1] == " "
    # Source -> preview: the repeated paragraph in main.typ is on page 2.
    page, y = mapping.to_preview("main.typ", MAIN.index("Wiederholter") + 3) or (0, 0.0)
    assert page == 2
    assert y == pytest.approx(pairs[6].marker.y)
    page, y = mapping.to_preview("kapitel/a.typ", CHAPTER.index("Ein Absatz")) or (0, 0.0)
    assert page == 1
    assert y == pytest.approx(chapter_par.marker.y)


def test_cursor_after_an_include_follows_reading_order(project: Path) -> None:
    mapping = _map(project)
    last_of_chapter = mapping.pairs[5]
    after_include = MAIN.index("#include") + 3
    page, y = mapping.to_preview("main.typ", after_include) or (0, 0.0)
    assert page == last_of_chapter.marker.page
    assert y == pytest.approx(last_of_chapter.marker.y)
    # Before the include: the paragraph above it in main.typ.
    found = mapping.to_preview("main.typ", MAIN.index("#include") - 1)
    assert found is not None and found[1] >= mapping.pairs[1].marker.y
    assert found[0] == mapping.pairs[1].marker.page
    # Before anything with a marker (the set rules): nothing to show.
    assert mapping.to_preview("main.typ", 3) is None


def test_click_on_a_page_without_markers_uses_the_last_one_before(project: Path) -> None:
    mapping = _map(project)
    assert mapping.to_source(99, 10) == ("main.typ", MAIN.index("Wiederholter"))


def test_jump_and_preview_position_over_websocket(workspace: Path) -> None:
    (workspace / "main.typ").write_text(MAIN, encoding="utf-8")
    (workspace / "kapitel").mkdir()
    (workspace / "kapitel" / "a.typ").write_text(CHAPTER, encoding="utf-8")
    with app_client() as client:
        client.post("/api/workspace/open", json={"path": str(workspace)})
        with client.websocket_connect(WS_URL, headers={"origin": FRONTEND_ORIGIN}) as ws:
            receive_until(ws, "compile_status")
            located = {
                "type": "cursor_moved",
                "path": "kapitel/a.typ",
                "offset": CHAPTER.index("Ein Absatz"),
            }
            ws.send_text(json.dumps(located))
            position = receive_until(ws, "preview_position")
            assert position["page"] == 1
            ws.send_text(json.dumps({"type": "preview_click", "page": 1, "y": position["y"] + 1}))
            jump = receive_until(ws, "jump")
            assert jump == {
                "type": "jump",
                "path": "kapitel/a.typ",
                "offset": CHAPTER.index("Ein Absatz"),
            }
        # The helper file lives only in the compile mirror, never in the project.
        assert not (workspace / source_map.WRAPPER_NAME).exists()
