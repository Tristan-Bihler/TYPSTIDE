"""Autocomplete: which completer answers, installing Tinymist, and requests from the editor.

While Tinymist is not installed the NoneCompleter answers (nothing to offer), so callers
never branch on it. Installing happens only when the user asks
(POST /api/completion/install); progress is published to listeners like the spelling
check's.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from pathlib import Path

from typst_writer.adapters.none_completer import NoneCompleter
from typst_writer.adapters.tinymist import TinymistCompleter
from typst_writer.config import AppConfig
from typst_writer.domain.errors import CheckerUnavailableError, WorkspaceError
from typst_writer.domain.models import CompletionItem, CompletionRequest
from typst_writer.infra.tinymist_install import DOWNLOAD_MB, find_installation, install
from typst_writer.infra.tool_download import InstallError, InstallPhase
from typst_writer.ports.completer import Completer
from typst_writer.ports.rule_checker import CheckerStatus
from typst_writer.services.workspace import WorkspaceService

log = logging.getLogger(__name__)

NOT_INSTALLED = (
    f"Autocomplete needs Tinymist (about {DOWNLOAD_MB} MB, downloaded once, then offline). "
    "Click Install."
)

StatusListener = Callable[[CheckerStatus], None]


class CompletionService:
    def __init__(self, config: AppConfig, workspace: WorkspaceService) -> None:
        self._config = config
        self._workspace = workspace
        self._listeners: set[StatusListener] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._install_status: CheckerStatus | None = None  # while installing
        program = find_installation(config.tinymist)
        self._completer: Completer = (
            self._tinymist(program)
            if program is not None
            else NoneCompleter(CheckerStatus(state="not_installed", reason=NOT_INSTALLED))
        )

    def _tinymist(self, program: Path) -> TinymistCompleter:
        return TinymistCompleter(
            [str(program), "lsp"],
            max_message_bytes=self._config.limits.max_lsp_message_bytes,
            startup_timeout_s=self._config.tinymist.startup_timeout_seconds,
            request_timeout_s=self._config.tinymist.request_timeout_seconds,
        )

    def status(self) -> CheckerStatus:
        return self._install_status or self._completer.status()

    def subscribe(self, listener: StatusListener) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _publish(self) -> None:
        current = self.status()
        for listener in list(self._listeners):
            listener(current)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._completer.close()

    def install(self) -> CheckerStatus:
        """Download Tinymist in the background; progress arrives as status updates."""
        if self.status().state == "not_installed":
            self._install_status = CheckerStatus(
                state="installing", reason="Downloading Tinymist…", progress=0.0
            )
            self._publish()
            task = asyncio.create_task(self._install())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return self.status()

    async def _install(self) -> None:
        shown = -1

        def progress(phase: InstallPhase, done: int, total: int | None) -> None:
            nonlocal shown
            if phase == "download" and total:
                percent = done * 100 // total
                if percent != shown:
                    shown = percent
                    self._install_status = CheckerStatus(
                        state="installing",
                        reason=f"Downloading Tinymist… {percent} %",
                        progress=done / total,
                    )
                    self._publish()

        try:
            program = await install(self._config.tinymist, progress)
        except InstallError as exc:
            log.warning("Tinymist install failed: %s", exc)
            self._completer = NoneCompleter(
                CheckerStatus(state="not_installed", reason=f"{exc} Click Install to try again.")
            )
        else:
            self._completer = self._tinymist(program)
        self._install_status = None
        self._publish()

    async def complete(self, request: CompletionRequest) -> list[CompletionItem]:
        """Completions for a `.typ` file of the open folder; nothing when there is no
        folder, the path is outside it, or the completer fails."""
        info = self._workspace.info()
        if info is None or not request.path.endswith(".typ"):
            return []
        guard = self._workspace.guard
        try:
            path = guard.relative(guard.resolve(request.path))
        except WorkspaceError:
            return []
        try:
            return await self._completer.complete(
                guard.root, info.main, path, request.content, request.offset
            )
        except CheckerUnavailableError as exc:
            log.info("no completions: %s", exc)
            return []
