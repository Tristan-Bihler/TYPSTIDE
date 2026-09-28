import asyncio
import sys
from pathlib import Path

import pytest

from typst_writer.infra.lsp_client import (
    LspClient,
    LspError,
    LspProtocolError,
    encode,
    read_message,
)

pytestmark = pytest.mark.anyio

FAKE_LTEX = Path(__file__).parent / "fakes" / "ltex.py"


def _reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


async def test_frames_round_trip_including_unicode() -> None:
    message = {"jsonrpc": "2.0", "method": "x", "params": {"text": "Grüße 😀"}}
    reader = _reader(encode(message) + encode({"id": 1, "result": None}))
    assert await read_message(reader, 1000) == message
    assert await read_message(reader, 1000) == {"id": 1, "result": None}
    assert await read_message(reader, 1000) is None


async def test_frames_split_across_reads() -> None:
    frame = encode({"id": 7, "result": [1, 2, 3]})
    reader = asyncio.StreamReader()

    async def feed() -> None:
        for i in range(len(frame)):
            reader.feed_data(frame[i : i + 1])
            await asyncio.sleep(0)
        reader.feed_eof()

    task = asyncio.create_task(feed())
    assert await read_message(reader, 1000) == {"id": 7, "result": [1, 2, 3]}
    await task


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"Content-Length: 5000\r\n\r\n" + b"x" * 10, "exceeds the limit"),
        (b"Content-Type: x\r\n\r\n{}", "missing Content-Length"),
        (b"Content-Length: abc\r\n\r\n{}", "invalid Content-Length"),
        (b"Content-Length: 5\r\n\r\nnope!", "not valid JSON"),
        (b"Content-Length: 2\r\n\r\n[]", "not a JSON object"),
        (b"Content-Length: 50\r\n\r\n{}", "ended inside a message"),
        (b"Content-Length: 2\r\n", "ended inside a header"),
        (b"X: " + b"y" * 2000 + b"\r\n\r\n", "header line too long"),
        (b"X: y\r\n" * 20, "too many header lines"),
    ],
)
async def test_invalid_frames_are_rejected(data: bytes, match: str) -> None:
    with pytest.raises(LspProtocolError, match=match):
        await read_message(_reader(data), 1000)


class Recorder:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, object]] = []
        self.requests: list[tuple[str, object]] = []
        self.diagnostics = asyncio.Event()

    def notify(self, method: str, params: object) -> None:
        self.notifications.append((method, params))
        if method == "textDocument/publishDiagnostics":
            self.diagnostics.set()

    async def answer(self, method: str, params: object) -> object:
        self.requests.append((method, params))
        return [{"language": "de-DE"}] if method == "workspace/configuration" else None


def _client(recorder: Recorder, mode: str, tmp_path: Path) -> LspClient:
    return LspClient(
        [sys.executable, str(FAKE_LTEX)],
        tmp_path,
        max_message_bytes=100_000,
        on_notification=recorder.notify,
        on_request=recorder.answer,
        env={"FAKE_LTEX_MODE": mode, "PATH": ""},
    )


async def _open(client: LspClient, text: str) -> None:
    await client.request("initialize", {"processId": None, "capabilities": {}}, 10)
    await client.notify("initialized", {})
    document = {"uri": "file:///x.typ", "languageId": "typst", "version": 1, "text": text}
    await client.notify("textDocument/didOpen", {"textDocument": document})


async def test_requests_notifications_and_server_requests(tmp_path: Path) -> None:
    recorder = Recorder()
    client = _client(recorder, "ok", tmp_path)
    await client.start()
    try:
        await _open(client, "Ein Fehlr.")
        async with asyncio.timeout(10):
            await recorder.diagnostics.wait()
        assert recorder.requests[0][0] == "workspace/configuration"
        method, params = recorder.notifications[-1]
        assert method == "textDocument/publishDiagnostics"
        assert "GERMAN_SPELLER_RULE" in str(params)
    finally:
        await client.stop()
    assert not client.alive


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("crash_on_check", "exited"),
        ("garbage", "invalid message"),
        ("huge", "exceeds the limit"),
    ],
)
async def test_broken_server_closes_and_fails_pending_requests(
    tmp_path: Path, mode: str, reason: str
) -> None:
    recorder = Recorder()
    client = _client(recorder, mode, tmp_path)
    await client.start()
    await _open(client, "Text.")
    async with asyncio.timeout(10):
        await client.closed.wait()
    assert reason in client.close_reason
    with pytest.raises(LspError):
        await client.request("textDocument/codeAction", {}, 5)
    await client.stop()


async def test_missing_executable_is_an_lsp_error(tmp_path: Path) -> None:
    recorder = Recorder()
    client = LspClient(
        [str(tmp_path / "no-such-java")],
        tmp_path,
        max_message_bytes=1000,
        on_notification=recorder.notify,
        on_request=recorder.answer,
    )
    with pytest.raises(LspError, match="could not start"):
        await client.start()


async def test_request_timeout(tmp_path: Path) -> None:
    recorder = Recorder()
    client = _client(recorder, "slow_check", tmp_path)
    await client.start()
    try:
        await _open(client, "Text.")  # the fake is now busy for 5 s
        with pytest.raises(LspError, match="timed out"):
            await client.request("textDocument/codeAction", {}, 0.3)
    finally:
        await client.stop(timeout=0.5)
