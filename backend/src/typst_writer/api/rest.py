"""REST endpoints under `/api`."""

from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from typst_writer.adapters.typst_py import typst_version
from typst_writer.api.deps import ServicesDep
from typst_writer.api.schemas import (
    CreateEntryRequest,
    EntryPath,
    ExportRequest,
    FileContent,
    HealthResponse,
    OpenWorkspaceRequest,
    RenameRequest,
    SaveFileRequest,
    SetMainRequest,
)
from typst_writer.domain.errors import NoMainFileError
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
