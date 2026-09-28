"""Live preview and rule checks over WebSocket.

Each connection holds the client's unsaved buffers ("overlays"). Any change schedules a
compile of the workspace's main file; compiles never overlap and a burst of changes
collapses into one more compile. Only pages whose SVG changed are sent again. Open files
are also spell- and grammar-checked (CheckOrchestrator) and the findings sent back.
"""

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import Coroutine

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError

from typst_writer.api.deps import Services
from typst_writer.api.schemas import (
    CheckerStatusMessage,
    ClientMessage,
    CompileState,
    CompileStatus,
    CursorMoved,
    DocChanged,
    DocClosed,
    DocOpened,
    Jump,
    LocalCheckStatus,
    PageUpdate,
    PreviewClick,
    PreviewPages,
    PreviewPosition,
    ProblemsMessage,
    SuggestionsMessage,
    TypingPaused,
    WordCount,
    WorkspaceChanged,
)
from typst_writer.domain.errors import NoMainFileError, WorkspaceError
from typst_writer.domain.models import Suggestion
from typst_writer.domain.positions import TextPositions
from typst_writer.domain.word_count import document_counts
from typst_writer.ports.compiler import CompileFailedError
from typst_writer.ports.rule_checker import CheckerStatus
from typst_writer.services import source_map
from typst_writer.services.check_orchestrator import CheckOrchestrator
from typst_writer.services.local_check import LocalCheck
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
        self.checks = CheckOrchestrator(
            services.grammar, self._send_suggestions, services.config.limits.max_check_chars
        )
        self.local = LocalCheck(
            services.local_ai, self._send_local, self._send_local_status, self._read_saved
        )
        self._local_tasks: set[asyncio.Task[None]] = set()
        self._source_map: source_map.SourceMap | None = None  # valid until the next compile

    async def send(self, message: BaseModel) -> None:
        async with self._send_lock:
            await self._ws.send_text(message.model_dump_json())

    async def _send_suggestions(
        self, path: str, version: int | None, suggestions: list[Suggestion]
    ) -> None:
        self.local.rule_findings(path, version, suggestions)
        message = SuggestionsMessage(
            path=path, version=version, source="rule", suggestions=suggestions
        )
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await self.send(message)

    async def _send_local(
        self, path: str, version: int | None, suggestions: list[Suggestion]
    ) -> None:
        message = SuggestionsMessage(
            path=path, version=version, source="local_ai", suggestions=suggestions
        )
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await self.send(message)

    async def _send_local_status(self, pending: int) -> None:
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await self.send(LocalCheckStatus(pending=pending))

    def _read_saved(self, path: str) -> str | None:
        try:
            return self._services.workspace.read_text(path)
        except (WorkspaceError, OSError):
            return None

    def _read(self, path: str) -> str | None:
        return self.overlays[path] if path in self.overlays else self._read_saved(path)

    async def _map(self) -> source_map.SourceMap | None:
        if self._source_map is not None:
            return self._source_map
        info = self._services.workspace.info()
        if info is None or info.main is None:
            return None
        try:
            raw = await self._services.compile.query_wrapper(
                self._services.workspace.guard.root,
                info.main,
                dict(self.overlays),
                source_map.WRAPPER_NAME,
                source_map.wrapper_source(info.main),
                source_map.SELECTOR,
            )
        except (CompileFailedError, NoMainFileError, WorkspaceError):
            return None  # e.g. the document has an error: no jumping until it compiles
        self._source_map = source_map.build(raw, info.main, self._read)
        return self._source_map

    async def _jump(self, page: int, y: float) -> None:
        mapping = await self._map()
        found = mapping.to_source(page, y) if mapping is not None else None
        if found is None:
            return
        path, index = found
        offset = TextPositions(self._read(path) or "").utf16_offset(index)
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await self.send(Jump(path=path, offset=offset))

    async def _locate(self, path: str, offset: int) -> None:
        mapping = await self._map()
        index = TextPositions(self._read(path) or "").index_of_utf16(offset)
        found = mapping.to_preview(path, index) if mapping is not None else None
        if found is None:
            return
        page, y = found
        message = PreviewPosition(path=path, offset=offset, page=page, y=round(y, 1))
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await self.send(message)

    def spawn(self, work: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(work)
        self._local_tasks.add(task)
        task.add_done_callback(self._local_tasks.discard)

    def request_compile(self) -> None:
        self._wake.set()

    def reset(self) -> None:
        self.overlays.clear()
        self._page_hashes = []
        self.checks.clear()
        self.local.clear()

    async def compile_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            await self._compile_once()

    async def _compile_once(self) -> None:
        self._source_map = None
        workspace = self._services.workspace
        info = workspace.info()
        if info is None or info.main is None:
            await self._nothing_to_show("no_workspace" if info is None else "no_main")
            return
        await self.send(CompileStatus(state="compiling", main=info.main))
        try:
            result = await self._services.compile.preview(
                workspace.guard.root, info.main, dict(self.overlays)
            )
        except NoMainFileError:
            await self._nothing_to_show("no_main")
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
        overlays = dict(self.overlays)
        counts = await asyncio.to_thread(
            document_counts, info.main, lambda path: overlays.get(path) or self._read_saved(path)
        )
        await self.send(WordCount(total=sum(counts.values()), files=counts))

    async def _nothing_to_show(self, state: CompileState) -> None:
        self._page_hashes = []  # the client clears its preview; resend every page next time
        await self.send(ProblemsMessage(problems=[]))
        await self.send(CompileStatus(state=state, main=None))

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

    def _in_workspace(self, path: str) -> bool:
        try:
            self._services.workspace.guard.resolve(path)
        except WorkspaceError:
            return False  # outside the open folder, or no folder open
        return True

    def handle(self, message: ClientMessage) -> None:
        match message:
            case DocOpened(path=path, content=content, version=version):
                if self._in_workspace(path):
                    self.checks.update(path, content, version)
                    self.spawn(self.local.opened(path, content, version))
                return  # opening a file does not change the preview
            case TypingPaused(path=path, version=version, cursor=cursor):
                if self._in_workspace(path):
                    self.local.paused(path, version, cursor)
                return
            case PreviewClick(page=page, y=y):
                self.spawn(self._jump(page, y))
                return
            case CursorMoved(path=path, offset=offset):
                if self._in_workspace(path):
                    self.spawn(self._locate(path, offset))
                return
            case DocChanged(path=path, content=content, version=version):
                if not self._in_workspace(path):
                    return
                self.overlays[path] = content
                self._source_map = None
                self.checks.update(path, content, version)
                self.local.changed(path, content, version)
            case DocClosed(path=path):
                self.overlays.pop(path, None)
                self.checks.close(path)
                self.local.closed(path)
            case _:
                pass  # refresh
        self.request_compile()


class Hub:
    """All live connections; REST handlers notify them when files or the workspace change."""

    def __init__(self, workspace: WorkspaceService) -> None:
        self._workspace = workspace
        self.sessions: set[Session] = set()
        self._sends: set[asyncio.Task[None]] = set()

    def checker_status(self, status: CheckerStatus) -> None:
        """Called by GrammarService (synchronously) whenever the checker's state changes."""
        for session in list(self.sessions):
            task = asyncio.create_task(
                self._send_quietly(session, CheckerStatusMessage(status=status))
            )
            self._sends.add(task)
            task.add_done_callback(self._sends.discard)
        if status.state == "ready":
            self.recheck_all()

    def recheck_all(self) -> None:
        """Language, dictionary or checker changed: check every open file again."""
        for session in list(self.sessions):
            session.checks.recheck_all()
            session.spawn(session.local.refresh_all())

    def local_ai_changed(self) -> None:
        """The local model changed: show what the cache has for it (or clear)."""
        for session in list(self.sessions):
            session.spawn(session.local.refresh_all())

    @staticmethod
    async def _send_quietly(session: Session, message: BaseModel) -> None:
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await session.send(message)

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
        await session.send(CheckerStatusMessage(status=services.grammar.status()))
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
        await session.checks.stop()
        await session.local.stop()
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
