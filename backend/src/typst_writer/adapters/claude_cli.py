"""Claude through the locally installed Claude Code CLI (`claude -p`).

User decision: no API keys. The review runs with the user's existing Claude login.
Safety (CLAUDE.md, section 1): fixed argument list without a shell, the text on stdin
(never in argv), no tools and no MCP servers, an empty temporary working directory, no
ANTHROPIC_API_KEY in the environment, a timeout, and Pydantic validation of the output.
"""

import asyncio
import json
import os
import shutil
import tempfile
import time
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from typst_writer.adapters.change_schema import CHANGE_SCHEMA, ChangePayload
from typst_writer.domain.errors import AIFailedError, AIUnavailableError
from typst_writer.domain.models import Language, ReviewMode, ReviewRequest
from typst_writer.domain.review import ProposedChange
from typst_writer.infra.processes import NO_WINDOW
from typst_writer.ports.ai import AIStatus, ParagraphCheckRequest, ReviewDraft

REVIEW_SCHEMA = CHANGE_SCHEMA

_LANGUAGE_NAMES: dict[Language, str] = {"de-DE": "German", "en-US": "English"}

_MODE_TASKS: dict[ReviewMode, str] = {
    "check": "Fix only real errors: grammar, spelling, punctuation and agreement. "
    "Do not rephrase text that is already correct.",
    "improve": "Improve clarity, flow and academic style with as few changes as possible. "
    "Keep the meaning and the terminology.",
    "shorten": "Make the passage more concise without losing content: remove redundancy "
    "and filler, merge where it reads better.",
    "explain": "Do not propose changes (return an empty list). In the explanation, say in "
    "2 to 5 sentences what could be improved in the passage and why.",
}

_AUTH_TIMEOUT_S = 20.0
_STATUS_TTL_S = 60.0


def system_prompt(mode: ReviewMode, language: Language, glossary: list[str]) -> str:
    lang = _LANGUAGE_NAMES[language]
    rules = [
        f"You review a passage of an academic text written in {lang} in Typst markup.",
        _MODE_TASKS[mode],
        "Never change Typst markup: anything starting with #, math between $ signs, "
        "references starting with @, labels in <angle brackets>, text in backticks and "
        "code blocks must stay exactly as they are. Keep line breaks.",
        "For each change, 'original' must be copied verbatim from the selection and long "
        "enough to occur only once in it; 'replacement' is the new text; 'reason' is a short "
        f"explanation in {lang}.",
        "Only the selection may be changed; the surrounding context is for understanding.",
        "The explanation is written in "
        + lang
        + ("." if mode == "explain" else " and may be empty."),
    ]
    if glossary:
        rules.append("Keep these terms exactly as written: " + ", ".join(glossary) + ".")
    return "\n".join(rules)


def user_message(req: ReviewRequest) -> str:
    return (
        f"<context_before>\n{req.context_before}\n</context_before>\n"
        f"<selection>\n{req.selection}\n</selection>\n"
        f"<context_after>\n{req.context_after}\n</context_after>"
    )


class _Envelope(BaseModel):
    """The JSON printed by `claude -p --output-format json` (only fields we rely on)."""

    type: Literal["result"]
    subtype: str
    is_error: bool
    result: str = ""
    structured_output: dict[str, Any] | None = None


class _AuthStatus(BaseModel):
    loggedIn: bool  # noqa: N815 - field name from the CLI


def _child_env() -> dict[str, str]:
    """The CLI must use the user's Claude login, never an API key from the environment."""
    return {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}


class ClaudeCliProvider:
    name = "claude"

    def __init__(self, models: list[str], timeout_s: float, executable: str = "claude") -> None:
        self._models = models
        self._timeout_s = timeout_s
        self._executable = executable
        self._cached: tuple[float, AIStatus] | None = None

    async def _run(
        self, args: list[str], stdin: str, timeout_s: float, cwd: str | None = None
    ) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=_child_env(),
            creationflags=NO_WINDOW,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(stdin.encode("utf-8")), timeout_s)
        except BaseException:  # timeout, or the request was cancelled by the browser
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        code = process.returncode if process.returncode is not None else -1
        return code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    async def status(self, refresh: bool = False) -> AIStatus:
        now = time.monotonic()
        if not refresh and self._cached and now - self._cached[0] < _STATUS_TTL_S:
            return self._cached[1]
        status = await self._check()
        self._cached = (now, status)
        return status

    async def _check(self) -> AIStatus:
        path = shutil.which(self._executable)
        if path is None:
            return AIStatus(
                available=False,
                reason="The claude command (Claude Code) was not found. Install Claude Code "
                "and log in once with: claude auth login",
                models=[],
            )
        try:
            code, out, _ = await self._run([path, "auth", "status", "--json"], "", _AUTH_TIMEOUT_S)
            logged_in = code == 0 and _AuthStatus.model_validate_json(out).loggedIn
        except (TimeoutError, ValidationError, OSError):
            logged_in = False
        if not logged_in:
            return AIStatus(
                available=False,
                reason="Claude Code is not logged in. Run in a terminal: claude auth login",
                models=[],
            )
        return AIStatus(available=True, reason="", models=list(self._models))

    async def check_paragraph(self, req: ParagraphCheckRequest, model: str) -> list[ProposedChange]:
        return []  # the Claude slot only drives the on-demand review (no hidden fallback)

    async def review_selection(self, req: ReviewRequest, model: str) -> ReviewDraft:
        if model not in self._models:
            raise AIUnavailableError(f"'{model}' is not one of the Claude models in config.toml.")
        status = await self.status()
        path = shutil.which(self._executable)
        if not status.available or path is None:
            raise AIUnavailableError(status.reason or "The claude command was not found.")
        args = [
            path,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(REVIEW_SCHEMA),
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--model",
            model,
            "--system-prompt",
            system_prompt(req.mode, req.language, req.glossary),
        ]
        with tempfile.TemporaryDirectory(prefix="typst-writer-claude-") as empty_dir:
            try:
                code, out, err = await self._run(
                    args, user_message(req), self._timeout_s, empty_dir
                )
            except TimeoutError as e:
                raise AIFailedError(
                    f"Claude did not answer within {self._timeout_s:.0f} seconds."
                ) from e
        return _parse(code, out, err)


def _parse(code: int, out: str, err: str) -> ReviewDraft:
    try:
        envelope = _Envelope.model_validate_json(out)
    except ValidationError as e:
        detail = (err.strip().splitlines() or ["no output"])[-1][:300]
        raise AIFailedError(f"The claude command failed (exit code {code}): {detail}") from e
    if envelope.is_error or envelope.subtype != "success" or envelope.structured_output is None:
        detail = envelope.result.strip()[:300] or envelope.subtype
        raise AIFailedError(f"Claude could not complete the review: {detail}")
    try:
        payload = ChangePayload.model_validate(envelope.structured_output)
    except ValidationError as e:
        raise AIFailedError("Claude returned an answer in an unexpected format.") from e
    return ReviewDraft(explanation=payload.explanation, changes=payload.changes)
