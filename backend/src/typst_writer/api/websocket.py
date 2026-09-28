"""Live preview over WebSocket.

Each connection holds the client's unsaved buffers ("overlays"). Any change schedules a
compile of the workspace's main file; compiles never overlap and a burst of changes
collapses into one more compile. Only pages whose SVG changed are sent again.
"""

import asyncio
import contextlib
import hashlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError

from typst_writer.api.deps import Services
from typst_writer.api.schemas import (
    ClientMessage,
    CompileState,
    CompileStatus,
    DocChanged,
    DocClosed,
    PageUpdate,
    PreviewPages,
    ProblemsMessage,
    WorkspaceChanged,
)
from typst_writer.domain.errors import NoMainFileError, WorkspaceError
from typst_writer.services.workspace import WorkspaceService

log = logging.getLogger(__name__)
_client_message: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)

router = APIRouter()


class Session:
    def __init__(self, ws: WebSocket, services: Services) -> None:
        self._ws = ws
        self._services = services
        self.overlays: dict[str, str] = {}
        self._page_hashes: list[str] = []
        self._wake = asyncio.Event()
        self._send_lock = asyncio.Lock()

    async def send(self, message: BaseModel) -> None:
        async with self._send_lock:
            await self._ws.send_text(message.model_dump_json())

    def request_compile(self) -> None:
        self._wake.set()

    def reset(self) -> None:
        self.overlays.clear()
        self._page_hashes = []

    async def compile_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            await self._compile_once()

    async def _compile_once(self) -> None:
        workspace = self._services.workspace
        info = workspace.info()
        if info is None or info.main is None:
            state: CompileState = "no_workspace" if info is None else "no_main"
            await self.send(ProblemsMessage(problems=[]))
            await self.send(CompileStatus(state=state, main=None))
            return
        await self.send(CompileStatus(state="compiling", main=info.main))
        try:
            result = await self._services.compile.preview(
                workspace.guard.root, info.main, dict(self.overlays)
            )
        except NoMainFileError:
            await self.send(ProblemsMessage(problems=[]))
            await self.send(CompileStatus(state="no_main", main=None))
            return
        if result.ok:
            await self.send(PreviewPages(pages=self._page_updates(result.pages)))
        await self.send(ProblemsMessage(problems=result.problems))
        await self.send(
            CompileStatus(
                state="ok" if result.ok else "error",
                main=info.main,
                duration_ms=round(result.duration_ms, 1),
            )
        )

    def _page_updates(self, pages: list[str]) -> list[PageUpdate]:
        hashes = [hashlib.sha1(p.encode("utf-8"), usedforsecurity=False).hexdigest() for p in pages]
        updates = [
            PageUpdate(
                index=i,
                hash=h,
                svg=None if i < len(self._page_hashes) and self._page_hashes[i] == h else page,
            )
            for i, (h, page) in enumerate(zip(hashes, pages, strict=True))
        ]
        self._page_hashes = hashes
        return updates

    def handle(self, message: ClientMessage) -> None:
        match message:
            case DocChanged(path=path, content=content):
                try:
                    self._services.workspace.guard.resolve(path)
                except WorkspaceError:
                    return  # ignore buffers outside the open folder (or no folder open)
                self.overlays[path] = content
            case DocClosed(path=path):
                self.overlays.pop(path, None)
            case _:
                pass  # refresh
        self.request_compile()


class Hub:
    """All live connections; REST handlers notify them when files or the workspace change."""

    def __init__(self, workspace: WorkspaceService) -> None:
        self._workspace = workspace
        self.sessions: set[Session] = set()

    async def workspace_changed(self, reopened: bool = False) -> None:
        message = WorkspaceChanged(workspace=self._workspace.info(), reopened=reopened)
        for session in list(self.sessions):
            if reopened:
                session.reset()
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                await session.send(message)
            session.request_compile()


@router.websocket("/ws")
async def live(ws: WebSocket) -> None:
    services: Services = ws.app.state.services
    origin = ws.headers.get("origin")
    if origin is not None and origin not in ws.app.state.allowed_origins:
        await ws.close(code=1008)  # policy violation: foreign web page
        return
    await ws.accept()
    session = Session(ws, services)
    services.hub.sessions.add(session)
    worker = asyncio.create_task(session.compile_loop())
    try:
        await session.send(WorkspaceChanged(workspace=services.workspace.info(), reopened=True))
        session.request_compile()
        while True:
            raw = await ws.receive_text()
            try:
                session.handle(_client_message.validate_json(raw))
            except ValidationError:
                log.warning("ignored malformed WebSocket message")
    except WebSocketDisconnect:
        pass
    finally:
        services.hub.sessions.discard(session)
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
