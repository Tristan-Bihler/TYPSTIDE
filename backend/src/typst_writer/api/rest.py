"""REST endpoints under `/api`."""

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response

from typst_writer.adapters.typst_py import typst_version
from typst_writer.api.deps import ServicesDep
from typst_writer.api.schemas import (
    CreateEntryRequest,
    DictionaryWordRequest,
    EntryPath,
    ExportRequest,
    FileContent,
    GrammarLanguageRequest,
    HealthResponse,
    OpenWorkspaceRequest,
    OverlaysRequest,
    RenameRequest,
    RenderRequest,
    RenderResponse,
    SaveFileRequest,
    SetMainRequest,
)
from typst_writer.domain.errors import AIFailedError, NoMainFileError
from typst_writer.domain.models import (
    AISettings,
    ReviewRequest,
    ReviewResult,
    Snippet,
    UiSettings,
)
from typst_writer.infra.paths import WorkspaceGuard
from typst_writer.infra.state_store import OpenTabs
from typst_writer.services.grammar import GrammarOverview
from typst_writer.services.references import WorkspaceIndex, build_index
from typst_writer.services.review import AIOverview
from typst_writer.services.workspace import DirListing, Tree, WorkspaceInfo

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", typst_version=typst_version())


# --- workspace -----------------------------------------------------------------------


@router.get("/workspace")
async def get_workspace(s: ServicesDep) -> WorkspaceInfo | None:
    return s.workspace.info()


@router.post("/workspace/open")
async def open_workspace(body: OpenWorkspaceRequest, s: ServicesDep) -> WorkspaceInfo:
    info = s.workspace.open(body.path)
    await s.hub.workspace_changed(reopened=True)
    return info


@router.get("/workspace/tabs")
async def get_open_tabs(s: ServicesDep) -> OpenTabs:
    """The editor tabs to restore for the open folder."""
    return s.workspace.open_tabs()


@router.put("/workspace/tabs")
async def save_open_tabs(body: OpenTabs, s: ServicesDep) -> OpenTabs:
    s.workspace.save_open_tabs(body)
    return body


@router.get("/workspace/browse")
async def browse(s: ServicesDep, path: str | None = None) -> DirListing:
    return s.workspace.browse(path)


@router.get("/workspace/tree")
async def tree(s: ServicesDep) -> Tree:
    return s.workspace.tree()


@router.put("/workspace/main")
async def set_main(body: SetMainRequest, s: ServicesDep) -> WorkspaceInfo:
    info = s.workspace.set_main(body.path)
    await s.hub.workspace_changed()
    return info


# --- files ---------------------------------------------------------------------------


@router.get("/workspace/file")
async def read_file(s: ServicesDep, path: str = Query()) -> FileContent:
    return FileContent(path=path, content=s.workspace.read_text(path))


@router.put("/workspace/file")
async def save_file(body: SaveFileRequest, s: ServicesDep) -> EntryPath:
    s.workspace.write_text(body.path, body.content)
    await s.hub.workspace_changed()
    return EntryPath(path=body.path)


@router.post("/workspace/file")
async def create_file(body: CreateEntryRequest, s: ServicesDep) -> EntryPath:
    path = s.workspace.create_file(body.parent, body.name, overwrite=body.overwrite)
    await s.hub.workspace_changed()
    return EntryPath(path=path)


@router.post("/workspace/folder")
async def create_folder(body: CreateEntryRequest, s: ServicesDep) -> EntryPath:
    path = s.workspace.create_folder(body.parent, body.name)
    await s.hub.workspace_changed()
    return EntryPath(path=path)


@router.post("/workspace/rename")
async def rename(body: RenameRequest, s: ServicesDep) -> EntryPath:
    path = s.workspace.rename(body.path, body.new_name, overwrite=body.overwrite)
    await s.hub.workspace_changed()
    return EntryPath(path=path)


@router.delete("/workspace/entry")
async def delete_entry(s: ServicesDep, path: str = Query()) -> EntryPath:
    s.workspace.delete(path)
    await s.hub.workspace_changed()
    return EntryPath(path=path)


# --- insert toolbar -----------------------------------------------------------------


def _index(guard: WorkspaceGuard, overlays: dict[str, str]) -> WorkspaceIndex:
    for rel in overlays:
        guard.resolve(rel)  # reject paths outside the workspace
    return build_index(guard, overlays)


@router.get("/snippets")
async def list_snippets(s: ServicesDep) -> list[Snippet]:
    return s.snippets.list()


@router.post("/snippets/{snippet_id}/render")
async def render_snippet(snippet_id: str, body: RenderRequest, s: ServicesDep) -> RenderResponse:
    """Typst code for a dialog snippet. Unsaved buffers are needed to keep labels unique."""
    guard = s.workspace.guard
    code = s.snippets.render(snippet_id, body.params, guard, _index(guard, body.overlays))
    return RenderResponse(code=code)


@router.post("/workspace/references")
async def references(body: OverlaysRequest, s: ServicesDep) -> WorkspaceIndex:
    """Labels, citation keys and images for the insert dialogs."""
    return _index(s.workspace.guard, body.overlays)


# --- look and editor behaviour -------------------------------------------------------


@router.get("/settings/ui")
async def get_ui_settings(s: ServicesDep) -> UiSettings:
    return s.settings.ui()


@router.put("/settings/ui")
async def put_ui_settings(body: UiSettings, s: ServicesDep) -> UiSettings:
    return s.settings.save_ui(body)


# --- spelling and grammar (LTeX+) ---------------------------------------------------


@router.get("/grammar")
async def grammar_status(s: ServicesDep) -> GrammarOverview:
    return s.grammar.overview()


@router.post("/grammar/install")
async def grammar_install(s: ServicesDep) -> GrammarOverview:
    """Download LTeX+ in the background (only when the user clicks Install)."""
    return s.grammar.install()


@router.put("/grammar/settings")
async def grammar_settings(body: GrammarLanguageRequest, s: ServicesDep) -> GrammarOverview:
    overview = s.grammar.set_language(body.language)
    s.hub.recheck_all()
    return overview


@router.post("/grammar/dictionary")
async def grammar_add_word(body: DictionaryWordRequest, s: ServicesDep) -> GrammarOverview:
    overview = s.grammar.add_word(body.language, body.word)
    s.hub.recheck_all()
    return overview


# --- AI -----------------------------------------------------------------------------


@router.get("/ai/status")
async def ai_status(s: ServicesDep, refresh: bool = False) -> AIOverview:
    return await s.review.overview(refresh=refresh)


@router.put("/ai/settings")
async def ai_settings(body: AISettings, s: ServicesDep) -> AIOverview:
    overview = await s.review.update_settings(body)
    s.hub.local_ai_changed()
    return overview


async def _unless_disconnected(
    request: Request, work: Coroutine[Any, Any, ReviewResult]
) -> ReviewResult:
    """Run `work`, cancelling it (and so stopping the claude process) if the browser leaves."""
    task = asyncio.ensure_future(work)
    while True:
        done, _ = await asyncio.wait({task}, timeout=0.5)
        if done:
            return task.result()
        if await request.is_disconnected():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise AIFailedError("The review was cancelled.")


@router.post("/review")
async def review(body: ReviewRequest, request: Request, s: ServicesDep) -> ReviewResult:
    """Review the selection with the model in the Claude slot (NoneProvider when None)."""
    return await _unless_disconnected(request, s.review.review(body))


# --- export --------------------------------------------------------------------------


@router.post("/export/pdf")
async def export_pdf(body: ExportRequest, s: ServicesDep) -> Response:
    """Compile the main file, including the client's unsaved buffers, to PDF."""
    main = s.workspace.main
    if main is None:
        raise NoMainFileError()
    guard = s.workspace.guard
    for rel in body.overlays:
        guard.resolve(rel)  # reject paths outside the workspace
    pdf = await s.compile.export_pdf(guard.root, main, body.overlays)
    filename = main.rsplit("/", 1)[-1].removesuffix(".typ") + ".pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
