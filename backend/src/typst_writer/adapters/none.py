"""Null Object for an AI slot set to None: services never branch on "is AI enabled"."""

from typst_writer.domain.models import ReviewRequest, Suggestion
from typst_writer.ports.ai import AIStatus, ParagraphCheckRequest, ReviewDraft


class NoneProvider:
    name = "none"

    async def status(self, refresh: bool = False) -> AIStatus:
        return AIStatus(available=True, reason="", models=[])

    async def check_paragraph(self, req: ParagraphCheckRequest, model: str) -> list[Suggestion]:
        return []

    async def review_selection(self, req: ReviewRequest, model: str) -> ReviewDraft:
        return ReviewDraft(explanation="", changes=[])
