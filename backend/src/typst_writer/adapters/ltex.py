"""Spelling and grammar checks with LTeX+ (LanguageTool for Typst) over LSP.

One LTeX+ process serves all files; checks run one at a time, because LTeX+ reports its
findings without saying which version of a file they belong to. A check that times out
restarts the process so that a late answer cannot be mistaken for the next check's.
Everything LTeX+ sends is validated; findings caused by Typst markup are dropped
(domain/grammar_filter.py), and offsets are converted to UTF-16 like the editor uses.
"""

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, ValidationError

from typst_writer.domain.errors import CheckerUnavailableError
from typst_writer.domain.grammar_filter import Finding, is_false_alarm
from typst_writer.domain.models import Language, Suggestion
from typst_writer.domain.positions import TextPositions
from typst_writer.domain.typst_prose import scan
from typst_writer.infra.lsp_client import LspClient, LspError
from typst_writer.ports.rule_checker import CheckerStatus

log = logging.getLogger(__name__)

MAX_RESTARTS = 3
MAX_FIX_REQUESTS = 60  # findings per check that get quick fixes (the rest are still shown)
MAX_FIXES = 3
URI_ROOT = "file:///typst-writer/"  # LTeX+ never reads files; the URI only names the buffer


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Position(_Model):
    line: int
    character: int


class _Range(_Model):
    start: _Position
    end: _Position


class _Diagnostic(_Model):
    range: _Range
    message: str = ""
    code: str | int | None = None


class _Published(_Model):
    uri: str
    diagnostics: list[_Diagnostic]


class _TextEdit(_Model):
    range: _Range
    newText: str  # noqa: N815 - LSP field name


class _DocumentEdit(_Model):
    edits: list[_TextEdit] = []


class _WorkspaceEdit(_Model):
    documentChanges: list[_DocumentEdit] = []  # noqa: N815 - LSP field name


class _CodeAction(_Model):
    kind: str = ""
    edit: _WorkspaceEdit | None = None


def is_spelling_rule(rule: str) -> bool:
    """Unknown-word rules (same families as LTeX+'s isUnknownWordRule)."""
    return (
        rule.startswith(("MORFOLOGIK_", "HUNSPELL_"))
        or rule.endswith(("_SPELLER_RULE", "_SPELLING_RULE"))
        or "ORTHOGRAPHY" in rule
    )


def document_uri(path: str) -> str:
    return URI_ROOT + quote(path)


StatusListener = Callable[[CheckerStatus], None]
_State = Literal["starting", "ready", "failed"]


class LtexChecker:
    def __init__(
        self,
        command: list[str],
        cwd: Path,
        *,
        max_message_bytes: int,
        startup_timeout_s: float,
        check_timeout_s: float,
        on_status: StatusListener | None = None,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._max_bytes = max_message_bytes
        self._startup_timeout = startup_timeout_s
        self._check_timeout = check_timeout_s
        self._on_status = on_status
        self._client: LspClient | None = None
        self._state: _State = "starting"
        self._reason = "LTeX+ is starting (the first check takes up to a minute)."
        self._restarts = 0
        self._start_lock = asyncio.Lock()
        self._check_lock = asyncio.Lock()
        self._versions: dict[str, int] = {}
        self._settings: dict[str, object] = {}
        self._waiting: dict[str, asyncio.Future[_Published]] = {}
        self._warm = False

    def status(self) -> CheckerStatus:
        return CheckerStatus(state=self._state, reason=self._reason)

    def _set_state(self, state: _State, reason: str) -> None:
        self._state, self._reason = state, reason
        if self._on_status is not None:
            self._on_status(self.status())

    # --- process lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        """Start LTeX+ and warm it up (idempotent). Failures end in state "failed"."""
        with contextlib.suppress(CheckerUnavailableError):
            await self._ensure_client()

    async def _ensure_client(self) -> LspClient:
        async with self._start_lock:
            if self._client is not None and self._client.alive:
                return self._client
            if self._client is not None:  # it died
                self._restarts += 1
                self._client = None
                self._versions.clear()
                self._warm = False
            if self._restarts > MAX_RESTARTS:
                self._set_state("failed", "LTeX+ stopped working repeatedly. Restart the app.")
                raise CheckerUnavailableError(self._reason)
            self._set_state("starting", "LTeX+ is starting (the first check takes up to a minute).")
            client = LspClient(
                self._command,
                self._cwd,
                max_message_bytes=self._max_bytes,
                on_notification=self._notification,
                on_request=self._server_request,
            )
            try:
                await client.start()
                params = {
                    "processId": None,
                    "rootUri": None,
                    "capabilities": {"workspace": {"configuration": True}},
                    "initializationOptions": {},
                }
                await client.request("initialize", params, self._startup_timeout)
                await client.notify("initialized", {})
            except LspError as exc:
                await client.stop(timeout=1.0)
                self._restarts += 1
                self._set_state("failed", f"LTeX+ could not be started: {exc}")
                raise CheckerUnavailableError(self._reason) from exc
            self._client = client
            if self._warm:
                self._set_state("ready", "")
            return client

    async def close(self) -> None:
        async with self._start_lock:
            client, self._client = self._client, None
        if client is not None:
            await client.stop()

    async def _restart(self) -> None:
        """Stop the process; the next check starts a fresh one (counts as a restart)."""
        client, self._client = self._client, None
        self._versions.clear()
        self._warm = False
        self._restarts += 1
        if client is not None:
            await client.stop(timeout=1.0)

    # --- messages from LTeX+ -----------------------------------------------------------

    def _notification(self, method: str, params: object) -> None:
        if method != "textDocument/publishDiagnostics":
            return
        try:
            published = _Published.model_validate(params)
        except ValidationError:
            log.warning("ignored malformed diagnostics from LTeX+")
            return
        future = self._waiting.pop(published.uri, None)
        if future is not None and not future.done():
            future.set_result(published)

    async def _server_request(self, method: str, params: object) -> object:
        if method == "workspace/configuration":
            items = params.get("items", []) if isinstance(params, dict) else []
            return [self._settings for _ in items] if isinstance(items, list) else []
        return None

    # --- checking --------------------------------------------------------------------

    async def check(
        self, path: str, source: str, language: Language, dictionary: list[str]
    ) -> list[Suggestion]:
        async with self._check_lock:
            client = await self._ensure_client()
            uri = document_uri(path)
            self._settings = {
                "language": language,
                "enabled": ["typst"],
                "dictionary": {language: list(dictionary)},
                "completionEnabled": False,
            }
            future: asyncio.Future[_Published] = asyncio.get_running_loop().create_future()
            self._waiting[uri] = future
            timeout = self._check_timeout if self._warm else self._startup_timeout
            try:
                await self._send_text(client, uri, source)
                published = await _published_or_closed(client, future, timeout)
                diagnostics = published.diagnostics
                fixes = await self._fixes(client, uri, diagnostics[:MAX_FIX_REQUESTS])
            except (LspError, TimeoutError) as exc:
                self._waiting.pop(uri, None)
                await self._restart()  # a late answer must not reach the next check
                reason = (
                    "LTeX+ did not answer in time" if isinstance(exc, TimeoutError) else str(exc)
                )
                raise CheckerUnavailableError(f"Spelling check failed: {reason}.") from exc
            if not self._warm:
                self._warm = True
                self._set_state("ready", "")
            return to_suggestions(source, diagnostics, fixes)

    async def _send_text(self, client: LspClient, uri: str, source: str) -> None:
        version = self._versions.get(uri)
        if version is None:
            self._versions[uri] = 1
            document = {"uri": uri, "languageId": "typst", "version": 1, "text": source}
            await client.notify("textDocument/didOpen", {"textDocument": document})
        else:
            self._versions[uri] = version + 1
            await client.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": version + 1},
                    "contentChanges": [{"text": source}],
                },
            )

    async def forget(self, path: str) -> None:
        """The file was closed in the editor: let LTeX+ free it."""
        uri = document_uri(path)
        async with self._check_lock:
            if self._versions.pop(uri, None) is not None and self._client is not None:
                with contextlib.suppress(LspError):
                    await self._client.notify(
                        "textDocument/didClose", {"textDocument": {"uri": uri}}
                    )

    async def _fixes(
        self, client: LspClient, uri: str, diagnostics: list[_Diagnostic]
    ) -> list[list[str]]:
        """Replacements per finding. LTeX+ offers at most 5 per code-action request across
        everything in the range, so ask once per finding (in parallel)."""

        async def fixes_for(diagnostic: _Diagnostic) -> list[str]:
            params = {
                "textDocument": {"uri": uri},
                "range": diagnostic.range.model_dump(),
                "context": {"diagnostics": [diagnostic.model_dump(exclude_none=True)]},
            }
            result = await client.request("textDocument/codeAction", params, self._check_timeout)
            words: list[str] = []
            for raw in result if isinstance(result, list) else []:
                try:
                    action = _CodeAction.model_validate(raw)
                except ValidationError:
                    continue
                if action.kind != "quickfix.ltex.acceptSuggestions" or action.edit is None:
                    continue
                for change in action.edit.documentChanges:
                    for edit in change.edits:
                        if edit.range == diagnostic.range and edit.newText not in words:
                            words.append(edit.newText)
            return words[:MAX_FIXES]

        return list(await asyncio.gather(*(fixes_for(d) for d in diagnostics)))


async def _published_or_closed(
    client: LspClient, future: asyncio.Future[_Published], timeout: float
) -> _Published:
    """The findings, or an error as soon as LTeX+ exits (not only after the timeout)."""

    async def fail_when_closed() -> None:
        await client.closed.wait()
        if not future.done():
            future.set_exception(LspError(client.close_reason or "LTeX+ stopped"))

    watcher = asyncio.create_task(fail_when_closed())
    try:
        async with asyncio.timeout(timeout):
            return await future
    finally:
        watcher.cancel()


def to_suggestions(
    source: str, diagnostics: list[_Diagnostic], fixes: list[list[str]]
) -> list[Suggestion]:
    positions = TextPositions(source)
    prose = scan(source)
    suggestions: list[Suggestion] = []
    for i, diagnostic in enumerate(diagnostics):
        start = positions.index(diagnostic.range.start.line, diagnostic.range.start.character)
        end = positions.index(diagnostic.range.end.line, diagnostic.range.end.character)
        rule = str(diagnostic.code or "")
        if end < start or is_false_alarm(Finding(start, end, rule), prose):
            continue
        options = fixes[i] if i < len(fixes) else []
        original = source[start:end]
        utf16_start = positions.utf16_offset(start)
        utf16_end = positions.utf16_offset(end)
        key = f"{utf16_start}:{utf16_end}:{rule}:{original}"
        suggestions.append(
            Suggestion(
                id="rule-" + hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12],
                source="rule",
                start=utf16_start,
                end=utf16_end,
                original=original,
                replacement=options[0] if options else original,
                reason=diagnostic.message,
                category="spelling" if is_spelling_rule(rule) else "grammar",
                fixes=options,
                rule=rule,
            )
        )
    return suggestions
