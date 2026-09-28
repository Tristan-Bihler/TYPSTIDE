"""Local AI live check: after a typing pause, edited paragraphs go to the local model.

User decision: only paragraphs changed since the file was opened are sent (the one at the
cursor first). Untouched text is never sent, and a paragraph whose text, model and
language were checked before comes from the ParagraphCache instead. One request runs at a
time per connection; any edit cancels it (a plain HTTP request, safe to abandon).
Proposed changes are untrusted: domain/review.py keeps only those that preserve Typst
markup and occur exactly once in their paragraph. The local slot set to None means the
NoneProvider answers and nothing leaves the editor.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from typst_writer.adapters.none import NoneProvider
from typst_writer.domain.errors import AIFailedError, AIUnavailableError
from typst_writer.domain.models import Language, Suggestion
from typst_writer.domain.paragraphs import Paragraph, paragraph_at, split_paragraphs
from typst_writer.domain.positions import TextPositions
from typst_writer.domain.review import ProposedChange, locate_changes, to_suggestions, utf16_len
from typst_writer.infra.cache import ParagraphCache
from typst_writer.ports.ai import AIProvider, ParagraphCheckRequest
from typst_writer.services.settings import SettingsService

log = logging.getLogger(__name__)

MODE = "live"


class LocalAI:
    """App-wide: the provider for the local slot, the cache and the validation."""

    def __init__(
        self, provider: AIProvider, settings: SettingsService, max_paragraph_chars: int
    ) -> None:
        self.provider = provider
        self._none = NoneProvider()
        self._settings = settings
        self._max_chars = max_paragraph_chars
        self.cache = ParagraphCache()

    def model(self) -> str | None:
        return self._settings.get().local_model

    def language(self) -> Language:
        return self._settings.grammar().language

    def cached(self, paragraph: str, model: str, language: Language) -> list[ProposedChange] | None:
        return self.cache.get(ParagraphCache.key(paragraph, model, MODE, language))

    def fits(self, paragraph: str) -> bool:
        return len(paragraph) <= self._max_chars

    async def check(
        self, paragraph: str, context: str, model: str | None, language: Language
    ) -> None:
        """Ask the model about one paragraph and cache the safe changes."""
        provider: AIProvider = self._none if model is None else self.provider
        request = ParagraphCheckRequest(
            paragraph=paragraph, context_before=context[-self._max_chars :], language=language
        )
        proposed = await provider.check_paragraph(request, model or "")
        kept, _dropped = locate_changes(paragraph, proposed)
        if model is not None:
            key = ParagraphCache.key(paragraph, model, MODE, language)
            self.cache.put(key, [located.change for located in kept])


SendSuggestions = Callable[[str, int | None, list[Suggestion]], Awaitable[None]]
SendStatus = Callable[[int], Awaitable[None]]  # paragraphs still to check (0 = idle)
ReadSaved = Callable[[str], str | None]  # the file's content on disk, if readable


@dataclass
class _Doc:
    content: str
    version: int | None
    baseline: frozenset[str]  # paragraph texts when the file was opened
    rule_ranges: list[tuple[int, int]] = field(default_factory=list)  # UTF-16, same version


class LocalCheck:
    """Per WebSocket connection."""

    def __init__(
        self, ai: LocalAI, send: SendSuggestions, status: SendStatus, read_saved: ReadSaved
    ) -> None:
        self._ai = ai
        self._send = send
        self._status = status
        self._read_saved = read_saved
        self._docs: dict[str, _Doc] = {}
        self._worker: asyncio.Task[None] | None = None
        self._worker_path: str | None = None

    # --- events --------------------------------------------------------------------------

    async def opened(self, path: str, content: str, version: int | None) -> None:
        if not path.endswith(".typ") or path in self._docs:
            return
        baseline = frozenset(p.text for p in split_paragraphs(content))
        self._docs[path] = _Doc(content, version, baseline)
        await self.publish(path, skip_empty=True)  # findings cached earlier in this session

    def changed(self, path: str, content: str, version: int | None) -> None:
        doc = self._docs.get(path)
        if doc is None:
            if path.endswith(".typ"):  # unsaved changes resent after a reconnect
                saved = self._read_saved(path) or ""
                baseline = frozenset(p.text for p in split_paragraphs(saved))
                self._docs[path] = _Doc(content, version, baseline)
            return
        doc.content, doc.version, doc.rule_ranges = content, version, []
        if self._worker_path == path:
            self._cancel()

    def rule_findings(self, path: str, version: int | None, found: list[Suggestion]) -> None:
        """Spelling/grammar findings: local AI suggestions on the same text are dropped."""
        doc = self._docs.get(path)
        if doc is not None and doc.version == version:
            doc.rule_ranges = [(s.start, s.end) for s in found]

    def paused(self, path: str, version: int | None, cursor: int) -> None:
        doc = self._docs.get(path)
        if doc is None or doc.version != version:
            return  # an older pause; a newer one follows
        self._cancel()
        self._worker_path = path
        self._worker = asyncio.create_task(self._work(path, doc, cursor))

    def closed(self, path: str) -> None:
        self._docs.pop(path, None)
        if self._worker_path == path:
            self._cancel()

    async def refresh_all(self) -> None:
        """The model or language changed: show what the cache has for the new setting."""
        self._cancel()
        for path in list(self._docs):
            await self.publish(path)

    async def stop(self) -> None:
        self._cancel()
        if self._worker is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker

    def clear(self) -> None:
        self._cancel()
        self._docs.clear()

    # --- work ----------------------------------------------------------------------------

    def _cancel(self) -> None:
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
        self._worker_path = None

    def _to_check(self, doc: _Doc, cursor: int, model: str, language: Language) -> list[int]:
        """Indexes of edited, uncached paragraphs; the one at the cursor first."""
        paragraphs = split_paragraphs(doc.content)
        todo = [
            i
            for i, p in enumerate(paragraphs)
            if p.text not in doc.baseline
            and self._ai.fits(p.text)
            and self._ai.cached(p.text, model, language) is None
        ]
        at_cursor = paragraph_at(paragraphs, TextPositions(doc.content).index_of_utf16(cursor))
        if at_cursor is not None:
            first = paragraphs.index(at_cursor)
            if first in todo:
                todo.remove(first)
                todo.insert(0, first)
        return todo

    async def _work(self, path: str, doc: _Doc, cursor: int) -> None:
        model, language = self._ai.model(), self._ai.language()
        try:
            # Cached findings first (they follow paragraphs that moved); with the slot set
            # to None this clears old local suggestions and nothing is sent to any model.
            await self.publish(path)
            if model is None:
                return
            paragraphs = split_paragraphs(doc.content)
            todo = self._to_check(doc, cursor, model, language)
            for done, index in enumerate(todo):
                await self._status(len(todo) - done)
                context = paragraphs[index - 1].text if index > 0 else ""
                try:
                    await self._ai.check(paragraphs[index].text, context, model, language)
                except AIFailedError as exc:
                    log.info("local AI check of one paragraph failed: %s", exc)
                    continue
                await self.publish(path)
        except AIUnavailableError as exc:
            log.info("local AI unavailable: %s", exc)
        finally:
            with contextlib.suppress(Exception):
                await self._status(0)

    async def publish(self, path: str, skip_empty: bool = False) -> None:
        """Send the cached findings of every current paragraph of `path`."""
        doc = self._docs.get(path)
        if doc is None:
            return
        model, language = self._ai.model(), self._ai.language()
        found: list[Suggestion] = []
        if model is not None:
            for paragraph in split_paragraphs(doc.content):
                changes = self._ai.cached(paragraph.text, model, language)
                if changes:
                    found.extend(_suggestions(doc.content, paragraph, changes))
        found = [s for s in found if not _overlaps(s, doc.rule_ranges)]
        if found or not skip_empty:
            await self._send(path, doc.version, found)


def _suggestions(
    content: str, paragraph: Paragraph, changes: list[ProposedChange]
) -> list[Suggestion]:
    kept, _ = locate_changes(paragraph.text, changes)
    start = utf16_len(content[: paragraph.start])
    return to_suggestions(paragraph.text, start, kept, source="local_ai")


def _overlaps(suggestion: Suggestion, ranges: list[tuple[int, int]]) -> bool:
    return any(suggestion.start < end and start < suggestion.end for start, end in ranges)
