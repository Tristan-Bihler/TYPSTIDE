"""Local AI through Ollama's HTTP API (live check of edited paragraphs).

Only talks to the Ollama on this computer (config.py rejects any other host) and ignores
proxy settings from the environment, so the text never leaves the machine. Answers are
forced into CHANGE_SCHEMA with Ollama's structured outputs and validated with Pydantic.
"""

import time

import httpx
from pydantic import BaseModel, ValidationError

from typst_writer.adapters.change_schema import CHANGE_SCHEMA, ChangePayload
from typst_writer.config import OllamaConfig
from typst_writer.domain.errors import AIFailedError, AIUnavailableError
from typst_writer.domain.models import Language, ReviewRequest
from typst_writer.domain.review import ProposedChange
from typst_writer.ports.ai import AIStatus, ParagraphCheckRequest, ReviewDraft

_STATUS_TIMEOUT_S = 3.0
_STATUS_TTL_S = 30.0
_MAX_ANSWER_CHARS = 100_000

_LANGUAGE_NAMES: dict[Language, str] = {"de-DE": "German", "en-US": "English"}

NOT_RUNNING = (
    "Ollama is not running. Start the Ollama app (or run: ollama serve), "
    "then come back to this window."
)
NO_MODELS = "Ollama has no models yet. Download one, e.g. in a terminal: ollama pull qwen2.5:7b"


def system_prompt(language: Language) -> str:
    lang = _LANGUAGE_NAMES[language]
    return "\n".join(
        [
            f"You check one paragraph of an academic text written in {lang} in Typst markup, "
            "while the author is still writing it.",
            "Report only real problems: grammar, agreement, wrong word choice, punctuation "
            "and clearly awkward or unclear phrasing. Do not report spelling mistakes (a "
            "spell checker handles them) or matters of taste. If the paragraph is fine, "
            "return an empty list of changes.",
            "Never change Typst markup: anything starting with #, math between $ signs, "
            "references starting with @, labels in <angle brackets> and text in backticks "
            "must stay exactly as they are.",
            "For each change, 'original' must be copied verbatim from the paragraph and be "
            "long enough to occur only once in it; 'replacement' is the corrected text; "
            f"'reason' is one short sentence in {lang}. Leave 'explanation' empty.",
            "The text before the paragraph is context only; never change it.",
        ]
    )


def user_message(req: ParagraphCheckRequest) -> str:
    return (
        f"<context_before>\n{req.context_before}\n</context_before>\n"
        f"<paragraph>\n{req.paragraph}\n</paragraph>"
    )


class _Model(BaseModel):
    name: str


class _Tags(BaseModel):
    models: list[_Model] = []


class _Message(BaseModel):
    content: str


class _ChatResponse(BaseModel):
    message: _Message


class OllamaProvider:
    name = "ollama"

    def __init__(self, config: OllamaConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        # trust_env=False: never route the local request through a proxy from the environment.
        self._client = client or httpx.AsyncClient(base_url=config.base_url, trust_env=False)
        self._cached: tuple[float, AIStatus] | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def status(self, refresh: bool = False) -> AIStatus:
        now = time.monotonic()
        if not refresh and self._cached and now - self._cached[0] < _STATUS_TTL_S:
            return self._cached[1]
        status = await self._check()
        self._cached = (now, status)
        return status

    async def _check(self) -> AIStatus:
        try:
            response = await self._client.get("/api/tags", timeout=_STATUS_TIMEOUT_S)
            response.raise_for_status()
            tags = _Tags.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError):
            return AIStatus(available=False, reason=NOT_RUNNING, models=[])
        models = sorted({m.name for m in tags.models})
        if not models:
            return AIStatus(available=False, reason=NO_MODELS, models=[])
        return AIStatus(available=True, reason="", models=models)

    async def check_paragraph(self, req: ParagraphCheckRequest, model: str) -> list[ProposedChange]:
        body = {
            "model": model,
            "stream": False,
            "format": CHANGE_SCHEMA,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system_prompt(req.language)},
                {"role": "user", "content": user_message(req)},
            ],
        }
        try:
            response = await self._client.post(
                "/api/chat", json=body, timeout=float(self._config.timeout_seconds)
            )
        except httpx.TimeoutException as exc:
            raise AIFailedError(
                f"The local model did not answer within {self._config.timeout_seconds} s."
            ) from exc
        except httpx.HTTPError as exc:
            self._cached = None  # Ollama may have stopped; check again next time
            raise AIUnavailableError(NOT_RUNNING) from exc
        if response.status_code == 404:
            raise AIUnavailableError(f"Ollama does not have the model '{model}' (any more).")
        if response.status_code != 200:
            raise AIFailedError(f"Ollama answered with HTTP {response.status_code}.")
        try:
            content = _ChatResponse.model_validate_json(response.content).message.content
            if len(content) > _MAX_ANSWER_CHARS:
                raise AIFailedError("The local model's answer is unexpectedly long.")
            return ChangePayload.model_validate_json(content).changes
        except ValidationError as exc:
            raise AIFailedError(
                "The local model returned an answer in an unexpected format."
            ) from exc

    async def review_selection(self, req: ReviewRequest, model: str) -> ReviewDraft:
        # The local slot only drives the live check; the review belongs to the Claude slot.
        raise AIUnavailableError("The selection review uses the Claude slot.")
