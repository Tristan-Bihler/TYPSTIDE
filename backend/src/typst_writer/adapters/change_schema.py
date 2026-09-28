"""The JSON answer format shared by the AI adapters (Claude CLI and Ollama): a list of
changes, each copied verbatim from the text, plus an optional explanation."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from typst_writer.domain.review import ProposedChange

CATEGORIES = ["grammar", "spelling", "punctuation", "style", "clarity", "brevity"]

CHANGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string"},
                    "replacement": {"type": "string"},
                    "reason": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                },
                "required": ["original", "replacement", "reason", "category"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["explanation", "changes"],
    "additionalProperties": False,
}


class ChangePayload(BaseModel):
    """An answer in CHANGE_SCHEMA, validated (AI output is untrusted)."""

    model_config = ConfigDict(extra="forbid")

    explanation: str = Field("", max_length=5_000)
    changes: list[ProposedChange] = Field(default_factory=list, max_length=200)
