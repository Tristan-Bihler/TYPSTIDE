"""Local settings in <config dir>/settings.json, restored on start: the AI slots and the
spelling/grammar language and dictionary."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from typst_writer.domain.models import AISettings, GrammarSettings


class StoredSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai: AISettings = AISettings()
    grammar: GrammarSettings = GrammarSettings()


class SettingsService:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> StoredSettings:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return StoredSettings()
        try:
            return StoredSettings.model_validate_json(raw)
        except ValidationError:
            pass
        try:  # before Phase 4 the file held only the AI slots
            return StoredSettings(ai=AISettings.model_validate_json(raw))
        except ValidationError:
            return StoredSettings()  # corrupt: defaults (both AI slots None) rather than fail

    def get(self) -> AISettings:
        return self.load().ai

    def save(self, settings: AISettings) -> AISettings:
        self._write(self.load().model_copy(update={"ai": settings}))
        return settings

    def grammar(self) -> GrammarSettings:
        return self.load().grammar

    def save_grammar(self, settings: GrammarSettings) -> GrammarSettings:
        self._write(self.load().model_copy(update={"grammar": settings}))
        return settings

    def _write(self, stored: StoredSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(stored.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.path)
