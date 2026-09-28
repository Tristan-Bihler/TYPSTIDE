"""Typst adapter and compile service against the pinned Typst version."""

from pathlib import Path

import pytest

from typst_writer.adapters.typst_py import TypstPyCompiler, parse_diagnostic
from typst_writer.domain.errors import NoMainFileError
from typst_writer.ports.compiler import CompileFailedError
from typst_writer.services.compile import CompileService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "chapters").mkdir(parents=True)
    (root / "main.typ").write_text('= Thesis\n#include "chapters/one.typ"\n', encoding="utf-8")
    (root / "chapters" / "one.typ").write_text("== Einleitung\nText.\n", encoding="utf-8")
    return root


@pytest.fixture
def service(tmp_path: Path) -> CompileService:
    return CompileService(TypstPyCompiler(), tmp_path / "cache")


def test_parse_diagnostic_maps_location(tmp_path: Path) -> None:
    diagnostic = (
        f"error: unknown variable: foo\n  ┌─ {tmp_path}/chapters/one.typ:3:4\n  │\n3 │ #foo\n"
    )
    problem = parse_diagnostic("unknown variable: foo", diagnostic, ["try x"], "error", tmp_path)
    assert (problem.file, problem.line, problem.column) == ("chapters/one.typ", 3, 5)
    assert problem.message == "unknown variable: foo (hint: try x)"


def test_parse_diagnostic_outside_root_has_no_location(tmp_path: Path) -> None:
    diagnostic = "warning: w\n  ┌─ /somewhere/else.typ:1:0\n"
    problem = parse_diagnostic("w", diagnostic, [], "warning", tmp_path / "ws")
    assert (problem.file, problem.line, problem.column) == ("", 0, 0)


@pytest.mark.anyio
async def test_single_page_is_normalized_to_list(service: CompileService, workspace: Path) -> None:
    result = await service.preview(workspace, "main.typ", {})
    assert result.ok
    assert len(result.pages) == 1
    assert result.pages[0].startswith("<svg")


@pytest.mark.anyio
async def test_unsaved_chapter_edit_changes_rendered_main(
    service: CompileService, workspace: Path
) -> None:
    overlay = {"chapters/one.typ": "== Einleitung\nA\n#pagebreak()\nB\n"}
    result = await service.preview(workspace, "main.typ", overlay)
    assert len(result.pages) == 2
    assert (workspace / "chapters" / "one.typ").read_text(encoding="utf-8").endswith("Text.\n")


@pytest.mark.anyio
async def test_error_in_chapter_points_at_chapter(service: CompileService, workspace: Path) -> None:
    overlay = {"chapters/one.typ": "== Einleitung\n\nSee #undefined-thing here.\n"}
    result = await service.preview(workspace, "main.typ", overlay)
    assert not result.ok
    assert result.pages == []
    [problem] = result.problems
    assert (problem.file, problem.line, problem.column) == ("chapters/one.typ", 3, 6)
    assert problem.severity == "error"
    assert "undefined-thing" in problem.message


@pytest.mark.anyio
async def test_umlauts_count_as_one_column(service: CompileService, workspace: Path) -> None:
    result = await service.preview(workspace, "main.typ", {"main.typ": "äöü #nope"})
    assert (result.problems[0].line, result.problems[0].column) == (1, 6)


@pytest.mark.anyio
async def test_warnings_are_reported(service: CompileService, workspace: Path) -> None:
    result = await service.preview(
        workspace, "main.typ", {"main.typ": '#text(font: "NoSuchFontXyz")[a]'}
    )
    assert result.ok
    assert [p.severity for p in result.problems] == ["warning"]
    assert result.problems[0].file == "main.typ"


@pytest.mark.anyio
async def test_pdf_export_and_failure(service: CompileService, workspace: Path) -> None:
    pdf = await service.export_pdf(workspace, "main.typ", {})
    assert pdf.startswith(b"%PDF-")
    with pytest.raises(CompileFailedError) as info:
        await service.export_pdf(workspace, "main.typ", {"main.typ": "#oops"})
    assert info.value.problems[0].file == "main.typ"


@pytest.mark.anyio
async def test_missing_main_file(service: CompileService, workspace: Path) -> None:
    with pytest.raises(NoMainFileError):
        await service.preview(workspace, "missing.typ", {})


@pytest.mark.anyio
async def test_typical_preview_is_fast(service: CompileService, workspace: Path) -> None:
    body = "\n\n".join(
        f"== Abschnitt {i}\n" + "Lorem ipsum dolor sit amet. " * 40 for i in range(40)
    )
    await service.preview(workspace, "main.typ", {"chapters/one.typ": body})
    result = await service.preview(workspace, "main.typ", {"chapters/one.typ": body + "\nEnde."})
    assert len(result.pages) > 5
    assert result.duration_ms < 1000
