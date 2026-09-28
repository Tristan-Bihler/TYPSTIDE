import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from typst_writer.adapters.change_schema import CHANGE_SCHEMA
from typst_writer.adapters.ollama import NO_MODELS, NOT_RUNNING, OllamaProvider
from typst_writer.config import OllamaConfig
from typst_writer.domain.errors import AIFailedError, AIUnavailableError
from typst_writer.ports.ai import ParagraphCheckRequest

pytestmark = pytest.mark.anyio

CONFIG = OllamaConfig(base_url="http://127.0.0.1:11434", timeout_seconds=5)
REQUEST = ParagraphCheckRequest(
    paragraph="Er kommt nicht, weil er hat keine Zeit.",
    context_before="Vorheriger Absatz.",
    language="de-DE",
)
CHANGE = {
    "original": "weil er hat keine Zeit",
    "replacement": "weil er keine Zeit hat",
    "reason": "Im Nebensatz steht das Verb am Ende.",
    "category": "grammar",
}


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> OllamaProvider:
    transport = httpx.MockTransport(handler)
    return OllamaProvider(CONFIG, httpx.AsyncClient(base_url=CONFIG.base_url, transport=transport))


def _chat(content: object, status: int = 200) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(status, json={"message": {"role": "assistant", "content": text}})


async def test_status_lists_models_and_is_cached() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        models = [{"name": "qwen2.5:7b"}, {"name": "llama3.2:latest"}]
        return httpx.Response(200, json={"models": models})

    provider = _provider(handler)
    status = await provider.status()
    assert status.available
    assert status.models == ["llama3.2:latest", "qwen2.5:7b"]
    await provider.status()
    assert calls == ["/api/tags"]
    await provider.status(refresh=True)
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused", request=r)), NOT_RUNNING),
        (lambda r: httpx.Response(200, json={"models": []}), NO_MODELS),
        (lambda r: httpx.Response(500, text="boom"), NOT_RUNNING),
        (lambda r: httpx.Response(200, text="not json"), NOT_RUNNING),
    ],
    ids=["refused", "no-models", "http-500", "garbage"],
)
async def test_unavailable_with_a_reason(
    handler: Callable[[httpx.Request], httpx.Response], reason: str
) -> None:
    status = await _provider(handler).status()
    assert (status.available, status.reason, status.models) == (False, reason, [])


async def test_chat_request_shape_and_answer() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        seen.append(json.loads(request.content))
        return _chat({"explanation": "", "changes": [CHANGE]})

    changes = await _provider(handler).check_paragraph(REQUEST, "qwen2.5:7b")
    assert [c.model_dump() for c in changes] == [CHANGE]
    [body] = seen
    assert body["model"] == "qwen2.5:7b"
    assert body["stream"] is False
    assert body["format"] == CHANGE_SCHEMA
    assert body["options"] == {"temperature": 0}
    messages = body["messages"]
    assert isinstance(messages, list)
    assert "German" in messages[0]["content"]
    assert "Never change Typst markup" in messages[0]["content"]
    assert (
        "<paragraph>\nEr kommt nicht, weil er hat keine Zeit.\n</paragraph>"
        in messages[1]["content"]
    )
    assert "Vorheriger Absatz." in messages[1]["content"]


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (_chat("not json at all"), AIFailedError),
        (_chat({"changes": [{"original": "x"}]}), AIFailedError),
        (_chat({"explanation": "", "changes": [], "extra": 1}), AIFailedError),
        (httpx.Response(200, json={"unexpected": True}), AIFailedError),
        (httpx.Response(500, text="model crashed"), AIFailedError),
        (httpx.Response(404, json={"error": "model not found"}), AIUnavailableError),
    ],
    ids=["not-json", "incomplete-change", "extra-field", "no-message", "http-500", "no-model"],
)
async def test_bad_answers_raise(response: httpx.Response, error: type[Exception]) -> None:
    with pytest.raises(error):
        await _provider(lambda _: response).check_paragraph(REQUEST, "qwen2.5:7b")


async def test_timeout_and_stopped_ollama() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(AIFailedError, match="did not answer within 5 s"):
        await _provider(slow).check_paragraph(REQUEST, "m")

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AIUnavailableError, match="not running"):
        await _provider(refused).check_paragraph(REQUEST, "m")


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434"],
)
def test_local_base_urls_are_accepted(url: str) -> None:
    assert OllamaConfig(base_url=url).base_url == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.20:11434",
        "https://ollama.example.com",
        "http://127.0.0.1.evil.com",
        "file:///x",
    ],
)
def test_remote_base_urls_are_refused(url: str) -> None:
    with pytest.raises(ValidationError, match="must point at this computer"):
        OllamaConfig(base_url=url)
