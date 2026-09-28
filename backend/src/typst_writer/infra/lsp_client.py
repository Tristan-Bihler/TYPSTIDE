"""Minimal Language Server Protocol client over stdio (JSON-RPC with Content-Length frames).

The server runs as a subprocess with a fixed argument list and no shell. Everything it
sends is untrusted: frames larger than the limit or malformed frames end the connection
(the owner restarts it), and requests from the server are answered by a callback.
"""

import asyncio
import contextlib
import itertools
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from typst_writer.infra.processes import NO_WINDOW

log = logging.getLogger(__name__)

MAX_HEADER_LINES = 16
MAX_HEADER_LINE_BYTES = 1024

NotificationHandler = Callable[[str, object], None]
RequestHandler = Callable[[str, object], Awaitable[object]]


class LspError(Exception):
    """The language server failed, answered with an error, or went away."""


class LspProtocolError(LspError):
    """The server sent something that is not a valid frame."""


def encode(message: Mapping[str, Any]) -> bytes:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


async def read_message(reader: asyncio.StreamReader, max_bytes: int) -> dict[str, Any] | None:
    """Read one frame; None at a clean end of stream."""
    length: int | None = None
    for count in itertools.count():
        if count >= MAX_HEADER_LINES:
            raise LspProtocolError("too many header lines")
        line = await reader.readline()
        if line == b"":
            if count == 0:
                return None
            raise LspProtocolError("stream ended inside a header")
        if len(line) > MAX_HEADER_LINE_BYTES:
            raise LspProtocolError("header line too long")
        if line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("ascii", errors="replace").partition(":")
        if name.strip().lower() == "content-length":
            if not value.strip().isdigit():
                raise LspProtocolError("invalid Content-Length")
            length = int(value.strip())
    if length is None:
        raise LspProtocolError("missing Content-Length")
    if length > max_bytes:
        raise LspProtocolError(f"message of {length} bytes exceeds the limit of {max_bytes}")
    try:
        body = await reader.readexactly(length)
        message = json.loads(body)
    except asyncio.IncompleteReadError as exc:
        raise LspProtocolError("stream ended inside a message") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LspProtocolError("message is not valid JSON") from exc
    if not isinstance(message, dict):
        raise LspProtocolError("message is not a JSON object")
    return message


class LspClient:
    def __init__(
        self,
        command: list[str],
        cwd: Path,
        *,
        max_message_bytes: int,
        on_notification: NotificationHandler,
        on_request: RequestHandler,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._env = dict(env) if env is not None else None
        self._max_bytes = max_message_bytes
        self._on_notification = on_notification
        self._on_request = on_request
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._ids = itertools.count(1)
        self._write_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._answers: set[asyncio.Task[None]] = set()
        self.closed = asyncio.Event()
        self.close_reason = ""

    @property
    def alive(self) -> bool:
        return self._process is not None and not self.closed.is_set()

    async def start(self) -> None:
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                env=self._env,
                creationflags=NO_WINDOW,
            )
        except OSError as exc:
            raise LspError(f"could not start the language server: {exc}") from exc
        self._tasks = [
            asyncio.create_task(self._read_loop()),
            asyncio.create_task(self._drain_stderr()),
        ]

    async def request(self, method: str, params: object, timeout: float) -> object:
        if not self.alive:
            raise LspError(self.close_reason or "the language server is not running")
        request_id = next(self._ids)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            async with asyncio.timeout(timeout):
                return await future
        except TimeoutError as exc:
            raise LspError(f"{method} timed out after {timeout:g} s") from exc
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: object) -> None:
        if not self.alive:
            raise LspError(self.close_reason or "the language server is not running")
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def stop(self, timeout: float = 3.0) -> None:
        """Polite shutdown, then kill if the server does not exit in time."""
        if self.alive:
            with contextlib.suppress(LspError, OSError, ConnectionError):
                await self.request("shutdown", None, timeout)
                await self.notify("exit", None)
        await self._terminate(timeout, "stopped")

    async def _send(self, message: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise LspError("the language server is not running")
        async with self._write_lock:
            try:
                process.stdin.write(encode(message))
                await process.stdin.drain()
            except (ConnectionError, OSError) as exc:
                raise LspError("the language server closed its input") from exc

    async def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        reason = "the language server exited"
        try:
            while True:
                message = await read_message(process.stdout, self._max_bytes)
                if message is None:
                    break
                self._dispatch(message)
        except LspProtocolError as exc:
            reason = f"the language server sent an invalid message: {exc}"
            log.warning(reason)
        except (ConnectionError, OSError):
            pass
        await self._terminate(1.0, reason)

    def _dispatch(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if isinstance(method, str):
            if "id" in message:
                task = asyncio.create_task(
                    self._answer(message["id"], method, message.get("params"))
                )
                self._answers.add(task)
                task.add_done_callback(self._answers.discard)
            else:
                try:
                    self._on_notification(method, message.get("params"))
                except Exception:  # a handler bug must not kill the connection
                    log.exception("LSP notification handler failed for %s", method)
            return
        request_id = message.get("id")
        future = self._pending.get(request_id) if isinstance(request_id, int) else None
        if future is None or future.done():
            return
        if "error" in message:
            error = message["error"]
            text = error.get("message", "") if isinstance(error, dict) else str(error)
            future.set_exception(LspError(f"the language server answered with an error: {text}"))
        else:
            future.set_result(message.get("result"))

    async def _answer(self, request_id: object, method: str, params: object) -> None:
        try:
            result = await self._on_request(method, params)
            reply: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception:
            log.exception("LSP request handler failed for %s", method)
            reply = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": "internal error"},
            }
        with contextlib.suppress(LspError):
            await self._send(reply)

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        with contextlib.suppress(ConnectionError, OSError, ValueError):
            while line := await process.stderr.readline():
                log.debug("language server: %s", line[:500].decode("utf-8", errors="replace"))

    async def _terminate(self, timeout: float, reason: str) -> None:
        if not self.closed.is_set():
            self.close_reason = reason
            self.closed.set()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(LspError(self.close_reason))
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        if process.returncode is None:
            try:
                async with asyncio.timeout(timeout):
                    await process.wait()
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        current = asyncio.current_task()
        for task in self._tasks:
            if task is not current:
                task.cancel()
