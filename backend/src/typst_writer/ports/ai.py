from typing import Protocol

from pydantic import BaseModel

from typst_writer.domain.models import Language, ReviewRequest, Suggestion
from typst_writer.domain.review import ProposedChange


class AIStatus(BaseModel):
    available: bool
    reason: str  # why it is unavailable; shown as tooltip ("" when available)
    models: list[str]


class ParagraphCheckRequest(BaseModel):
    """Live check of one paragraph (Phase 5)."""

    paragraph: str
    language: Language = "de-DE"


class ReviewDraft(BaseModel):
    """What a provider proposes. ReviewService validates it against the selection."""

    explanation: str
    changes: list[ProposedChange]


class AIProvider(Protocol):
    name: str

    async def status(self) -> AIStatus: ...

    async def check_paragraph(self, req: ParagraphCheckRequest, model: str) -> list[Suggestion]: ...

    async def review_selection(self, req: ReviewRequest, model: str) -> ReviewDraft:
        """Raises AIUnavailableError or AIFailedError."""
        ...
