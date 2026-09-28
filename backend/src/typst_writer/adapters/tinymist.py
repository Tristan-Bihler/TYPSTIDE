"""Autocomplete with Tinymist (Typst language server) over LSP.

One Tinymist process per open folder, started on the first completion request. The main
file is pinned, so labels and citations from every chapter are offered. The editor's text
of the file being edited is sent before each request (Tinymist reads other files from
disk). Everything Tinymist answers is validated; its diagnostics are ignored, because the
app's own compile is the only source of errors. Requests run one at a time, so a text
update and the completion that belongs to it never interleave with another request's.
"""

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from typst_writer.domain.errors import CheckerUnavailableError
from typst_writer.domain.models import MAX_COMPLETION_ITEMS, CompletionItem
from typst_writer.domain.positions import TextPositions
from typst_writer.domain.review import utf16_len
from typst_writer.infra.lsp_client import LspClient, LspError
from typst_writer.ports.rule_checker import CheckerStatus

log = logging.getLogger(__name__)

MAX_RESTARTS = 3
MAX_LABEL = 200
MAX_DETAIL = 160
MAX_INSERT = 4000
PIN_SETTLE_S = 2.0
TEXT_SETTLE_S = 0.3

# LSP CompletionItemKind -> editor icon name.
KINDS: dict[int, str] = {
    1: "text",
    2: "function",
    3: "function",
    4: "function",
    5: "variable",
    6: "variable",
    7: "type",
    8: "type",
    9: "namespace",
    10: "property",
    11: "constant",
    12: "constant",
    13: "type",
    14: "keyword",
    15: "keyword",
    16: "constant",
    17: "file",
    18: "label",
    19: "file",
    20: "constant",
    21: "constant",
    22: "type",
    25: "type",
}
# Tinymist's settings: never write files (PDF export), no formatting, no extra analysis.
INITIALIZATION_OPTIONS = {
    "exportPdf": "never",
    "formatterMode": "disable",
    "semanticTokens": "disable",
    "compileStatus": "enable",  # tells when a text change has been taken in (see _settle)
    "lint": {"enabled": False},
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Position(_Model):
    line: int
    character: int


class _Range(_Model):
    start: _Position
    end: _Position


class _TextEdit(_Model):
    newText: str  # noqa: N815 - LSP field name
    range: _Range | None = None
    insert: _Range | None = None  # InsertReplaceEdit


class _LabelDetails(_Model):
    description: str | None = None


class _Item(_Model):
    label: str
    kind: int | None = None
    detail: str | None = None
    labelDetails: _LabelDetails | None = None  # noqa: N815
    insertText: str | None = None  # noqa: N815
    insertTextFormat: int | None = None  # noqa: N815 - 2 = snippet
    textEdit: _TextEdit | None = None  # noqa: N815
    sortText: str | None = None  # noqa: N815


def lsp_position(text: str, index: int) -> dict[str, int]:
    """LSP position (line, UTF-16 character in the line) of a Python index."""
    line = text.count("\n", 0, index)
    line_start = text.rfind("\n", 0, index) + 1
    return {"line": line, "character": utf16_len(text[line_start:index])}


def _one_line(text: str) -> str:
    first = text.strip().split("\n", 1)[0]
    return first if len(first) <= MAX_DETAIL else first[: MAX_DETAIL - 1] + "…"


def _fits(typed: str, label: str) -> bool:
    """Whether the typed characters occur in `label` in order (like the editor's filter)."""
    rest = iter(label.casefold())
    return all(c in rest for c in typed.casefold())


def to_items(content: str, cursor: int, result: object) -> list[CompletionItem]:
    """Validated completion items; `cursor` is the Python index of the request."""
    raw = result.get("items") if isinstance(result, dict) else result
    if not isinstance(raw, list):
        return []
    positions = TextPositions(content)
    parsed: list[_Item] = []
    for entry in raw[: MAX_COMPLETION_ITEMS * 2]:
        with contextlib.suppress(ValidationError):
            parsed.append(_Item.model_validate(entry))
    parsed.sort(key=lambda item: item.sortText or item.label)
    items: list[CompletionItem] = []
    seen: set[tuple[str, str]] = set()
    for item in parsed:
        edit = item.textEdit
        span = edit.range or edit.insert if edit is not None else None
        insert = edit.newText if edit is not None else (item.insertText or item.label)
        if span is not None:
            start = positions.index(span.start.line, span.start.character)
            end = positions.index(span.end.line, span.end.character)
        else:
            start = end = cursor
        if not (start <= cursor <= end) or len(item.label) > MAX_LABEL or len(insert) > MAX_INSERT:
            continue
        if not _fits(content[start:cursor], item.label):
            continue  # the editor would hide it anyway; keeps the list under the cap
        if (item.label, insert) in seen:
            continue  # Tinymist lists some items twice (with and without signature)
        seen.add((item.label, insert))
        description = (item.labelDetails.description if item.labelDetails else None) or ""
        items.append(
            CompletionItem(
                label=item.label,
                detail=_one_line(description or item.detail or ""),
                kind=KINDS.get(item.kind or 1, "text"),
                insert=insert,
                snippet=item.insertTextFormat == 2,
                start=positions.utf16_offset(start),
                end=positions.utf16_offset(end),
            )
        )
        if len(items) >= MAX_COMPLETION_ITEMS:
            break
    return items


_State = Literal["ready", "failed"]


class TinymistCompleter:
    def __init__(
        self,
        command: list[str],
        *,
        max_message_bytes: int,
        startup_timeout_s: float,
        request_timeout_s: float,
    ) -> None:
        self._command = command
        self._max_bytes = max_message_bytes
        self._startup_timeout = startup_timeout_s
        self._request_timeout = request_timeout_s
        self._client: LspClient | None = None
        self._root: Path | None = None
        self._main: str | None = None
        self._versions: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._restarts = 0
        self._state: _State = "ready"
        self._reason = ""
        self._compiles: list[str] = []  # compile states reported during the current request
        self._compile_reported = asyncio.Event()

    def status(self) -> CheckerStatus:
        return CheckerStatus(state=self._state, reason=self._reason)

    async def close(self) -> None:
        async with self._lock:
            await self._stop()

    async def _stop(self) -> None:
        client, self._client = self._client, None
        self._root, self._main = None, None
        self._versions.clear()
        if client is not None:
            await client.stop(timeout=1.0)

    async def _ensure(self, root: Path) -> LspClient:
        if self._client is not None and self._client.alive and self._root == root:
            return self._client
        if self._client is not None:
            if self._root == root:
                self._restarts += 1  # it died
            await self._stop()
        if self._restarts > MAX_RESTARTS:
            self._state, self._reason = "failed", "Tinymist stopped working repeatedly."
            raise CheckerUnavailableError(self._reason)
        client = LspClient(
            self._command,
            root,
            max_message_bytes=self._max_bytes,
            on_notification=self._notification,
            on_request=self._server_request,
        )
        try:
            await client.start()
            params = {
                "processId": None,
                "rootUri": root.as_uri(),
                "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
                "capabilities": {
                    "workspace": {"configuration": True},
                    "textDocument": {"completion": {"completionItem": {"snippetSupport": True}}},
                },
                "initializationOptions": INITIALIZATION_OPTIONS,
            }
            await client.request("initialize", params, self._startup_timeout)
            await client.notify("initialized", {})
        except LspError as exc:
            await client.stop(timeout=1.0)
            self._restarts += 1
            self._reason = f"Tinymist could not be started: {exc}"
            raise CheckerUnavailableError(self._reason) from exc
        self._client, self._root = client, root
        self._state, self._reason = "ready", ""
        return client

    def _notification(self, method: str, params: object) -> None:
        # Diagnostics are ignored: our own compile is the only source of errors.
        if method == "tinymist/compileStatus" and isinstance(params, dict):
            self._compiles.append(str(params.get("status", "")))
            del self._compiles[:-50]
            self._compile_reported.set()

    def _compiled(self, finished: bool) -> bool:
        if "compiling" not in self._compiles:
            return False
        return not finished or self._compiles[-1] != "compiling"

    async def _settle(self, timeout: float, *, finished: bool = False) -> None:
        """Wait (at most `timeout`) until Tinymist starts (or `finished`) compiling after the
        last change.

        Tinymist takes text changes in on its own schedule; a request sent right after a
        change (above all right after start-up) can otherwise see the file on disk. A change
        to a file outside the main document compiles nothing, so this only waits.
        """
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                while not self._compiled(finished):
                    self._compile_reported.clear()
                    await self._compile_reported.wait()

    @staticmethod
    async def _server_request(method: str, params: object) -> object:
        if method == "workspace/configuration":
            items = params.get("items", []) if isinstance(params, dict) else []
            return [INITIALIZATION_OPTIONS for _ in items] if isinstance(items, list) else []
        return None  # registerCapability, workDoneProgress/create, ...

    async def complete(
        self, root: Path, main: str | None, path: str, content: str, offset: int
    ) -> list[CompletionItem]:
        async with self._lock:
            try:
                client = await self._ensure(root)
                if main != self._main:
                    target = str(root / main) if main is not None else None
                    command = {"command": "tinymist.pinMain", "arguments": [target]}
                    self._compiles.clear()
                    await client.request("workspace/executeCommand", command, self._request_timeout)
                    await self._settle(PIN_SETTLE_S, finished=True)
                    self._main = main
                uri = (root / path).as_uri()
                self._compiles.clear()
                await self._send_text(client, uri, content)
                await self._settle(TEXT_SETTLE_S)
                cursor = TextPositions(content).index_of_utf16(offset)
                params = {
                    "textDocument": {"uri": uri},
                    "position": lsp_position(content, cursor),
                }
                result = await client.request(
                    "textDocument/completion", params, self._request_timeout
                )
            except LspError as exc:
                log.warning("Tinymist completion failed: %s", exc)
                if self._client is not None:
                    self._restarts += 1
                await self._stop()  # a fresh process answers the next request
                raise CheckerUnavailableError(f"Autocomplete failed: {exc}") from exc
            return to_items(content, cursor, result)

    async def _send_text(self, client: LspClient, uri: str, content: str) -> None:
        version = self._versions.get(uri)
        if version is None:
            # Tinymist applies a didOpen in the background (a completion right after it can
            # still see the file on disk), but a didChange before the next request; so the
            # text is sent once more as a change.
            version = 1
            document = {"uri": uri, "languageId": "typst", "version": 1, "text": content}
            await client.notify("textDocument/didOpen", {"textDocument": document})
        self._versions[uri] = version + 1
        await client.notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version + 1},
                "contentChanges": [{"text": content}],
            },
        )
