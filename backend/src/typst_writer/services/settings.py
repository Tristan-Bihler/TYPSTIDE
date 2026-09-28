"""AI slot selection, persisted in <config dir>/settings.json and restored on start."""

from pathlib import Path

from pydantic import ValidationError

from typst_writer.domain.models import AISettings


class SettingsService:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self) -> AISettings:
        try:
            return AISettings.model_validate_json(self.path.read_bytes())
        except (FileNotFoundError, ValidationError):
            return AISettings()  # default: both slots None

    def save(self, settings: AISettings) -> AISettings:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return settings
