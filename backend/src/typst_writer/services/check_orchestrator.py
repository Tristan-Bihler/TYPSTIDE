"""Rule checks for the files open in one editor connection.

Every change stores the newest text; each file has at most one check running and at most
one waiting (with the newest text), so a burst of typing collapses into one more check.
Results for text that changed meanwhile are dropped: the next check replaces them.
Running checks are never interrupted (see LtexChecker.check).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass

from typst_writer.domain.errors import CheckerUnavailableError
from typst_writer.domain.models import Suggestion
from typst_writer.services.grammar import GrammarService

log = logging.getLogger(__name__)

SendSuggestions = Callable[[str, int | None, list[Suggestion]], Awaitable[None]]


@dataclass
class _Doc:
    content: str
    version: int | None
    stamp: int  # increases with every update, also when the client sends no version


class CheckOrchestrator:
    def __init__(self, grammar: GrammarService, send: SendSuggestions, max_chars: int) -> None:
        self._grammar = grammar
        self._send = send
        self._max_chars = max_chars
        self._docs: dict[str, _Doc] = {}
        self._dirty: set[str] = set()
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._stamp = 0
        self._stopped = False

    def update(self, path: str, content: str, version: int | None) -> None:
        if not path.endswith(".typ"):
            return
        self._stamp += 1
        self._docs[path] = _Doc(content, version, self._stamp)
        self._schedule(path)

    def recheck_all(self) -> None:
        for path in self._docs:
            self._schedule(path)

    def close(self, path: str) -> None:
        if self._docs.pop(path, None) is not None:
            self._dirty.discard(path)
            self._spawn_forget(path)

    def clear(self) -> None:
        for path in list(self._docs):
            self.close(path)

    async def stop(self) -> None:
        self._stopped = True
        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        for worker in workers:
            with contextlib.suppress(asyncio.CancelledError):
                await worker

    def _schedule(self, path: str) -> None:
        self._dirty.add(path)
        if path not in self._workers:
            self._start(path, self._work(path))

    def _spawn_forget(self, path: str) -> None:
        if path not in self._workers:
            self._start(path, self._grammar.forget(path))

    def _start(self, path: str, work: Coroutine[object, object, None]) -> None:
        if self._stopped:
            work.close()
            return
        worker = asyncio.create_task(work)
        self._workers[path] = worker
        worker.add_done_callback(lambda _: self._worker_done(path))

    def _worker_done(self, path: str) -> None:
        self._workers.pop(path, None)
        # A change may have arrived after the worker's last look at `_dirty`.
        if path in self._dirty and path in self._docs:
            self._schedule(path)

    async def _work(self, path: str) -> None:
        while path in self._dirty:
            self._dirty.discard(path)
            doc = self._docs.get(path)
            if doc is None:
                return
            if len(doc.content) > self._max_chars:
                await self._send(path, doc.version, [])
                continue
            try:
                found = await self._grammar.check(path, doc.content)
            except CheckerUnavailableError as exc:
                log.info("rule check skipped: %s", exc)  # the status bar shows why
                continue
            current = self._docs.get(path)
            if current is not None and current.stamp == doc.stamp:
                await self._send(path, doc.version, found)
        if path not in self._docs:
            await self._grammar.forget(path)
