"""AI slots and the on-demand selection review.

The Claude slot drives the review; when it is None the NoneProvider answers (no changes),
so this service never branches on "is AI enabled". The local slot (Ollama) drives the live
check (services/local_check.py); there is no hidden fallback between the two.
"""

import asyncio

from pydantic import BaseModel

from typst_writer.adapters.none import NoneProvider
from typst_writer.domain.errors import AIUnavailableError, TextTooLongError
from typst_writer.domain.models import AISettings, ReviewRequest, ReviewResult
from typst_writer.domain.review import locate_changes, rebuild, to_suggestions
from typst_writer.ports.ai import AIProvider, AIStatus
from typst_writer.services.settings import SettingsService


class AIOverview(BaseModel):
    local: AIStatus
    claude: AIStatus
    settings: AISettings


class ReviewService:
    def __init__(
        self, claude: AIProvider, local: AIProvider, settings: SettingsService, max_chars: int
    ) -> None:
        self._claude = claude
        self._local = local
        self._settings = settings
        self._none = NoneProvider()
        self._max_chars = max_chars

    async def overview(self, refresh: bool = False) -> AIOverview:
        local, claude = await asyncio.gather(
            self._local.status(refresh=refresh), self._claude.status(refresh=refresh)
        )
        return AIOverview(local=local, claude=claude, settings=self._settings.get())

    async def update_settings(self, new: AISettings) -> AIOverview:
        if new.local_model is not None:
            status = await self._local.status(refresh=True)
            if not status.available:
                raise AIUnavailableError(status.reason)
            if new.local_model not in status.models:
                raise AIUnavailableError(f"Ollama has no model '{new.local_model}'.")
        if new.claude_model is not None:
            status = await self._claude.status()
            if not status.available:
                raise AIUnavailableError(status.reason)
            if new.claude_model not in status.models:
                raise AIUnavailableError(f"'{new.claude_model}' is not in the Claude model list.")
        self._settings.save(new)
        return await self.overview()

    def _fit(self, req: ReviewRequest) -> ReviewRequest:
        """Keep the selection whole; shorten the context so everything fits the limit."""
        if len(req.selection) > self._max_chars:
            raise TextTooLongError(
                f"Select at most {self._max_chars:,} characters for a review "
                f"(the selection has {len(req.selection):,})."
            )
        room = (self._max_chars - len(req.selection)) // 2
        return req.model_copy(
            update={
                "context_before": req.context_before[-room:] if room else "",
                "context_after": req.context_after[:room],
            }
        )

    async def review(self, req: ReviewRequest) -> ReviewResult:
        req = self._fit(req)
        model = self._settings.get().claude_model
        provider: AIProvider = self._none if model is None else self._claude
        draft = await provider.review_selection(req, model or "")
        proposed = [] if req.mode == "explain" else draft.changes
        kept, dropped = locate_changes(req.selection, proposed)
        return ReviewResult(
            revised_text=rebuild(req.selection, kept),
            explanation=draft.explanation,
            changes=to_suggestions(req.selection, req.selection_start, kept),
            dropped=dropped,
        )
