"""Load and validate `config.toml` from the repository root."""

import os
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator

CONFIG_ENV_VAR = "TYPST_WRITER_CONFIG"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.toml"
SNIPPETS_PATH = REPO_ROOT / "snippets.toml"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerConfig(_Section):
    backend_port: int = 8000
    frontend_port: int = 5173


class TypstConfig(_Section):
    version: str = "0.15.0"


class TimingConfig(_Section):
    doc_changed_debounce_ms: int = 300
    typing_paused_ms: int = 1500


class LimitsConfig(_Section):
    max_ws_message_bytes: int = 2_000_000
    max_ai_text_chars: int = 20_000
    max_check_chars: int = 200_000
    max_lsp_message_bytes: int = 20_000_000


class ClaudeConfig(_Section):
    models: list[str] = []
    timeout_seconds: int = 120


class OllamaConfig(_Section):
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: int = 60
    max_paragraph_chars: int = 4000

    @field_validator("base_url")
    @classmethod
    def _local_only(cls, value: str) -> str:
        """The local AI slot must stay on this computer: text never leaves it."""
        url = urlsplit(value)
        if url.scheme not in ("http", "https") or url.hostname not in LOOPBACK_HOSTS:
            raise ValueError(
                "[ollama] base_url must point at this computer "
                "(http://127.0.0.1:11434, localhost or [::1])"
            )
        return value.rstrip("/")


class LtexConfig(_Section):
    version: str = "18.7.0"
    url: str = ""
    sha256: dict[str, str] = {}  # platform key (e.g. "windows-x64") -> archive checksum
    startup_timeout_seconds: int = 180
    check_timeout_seconds: int = 30


class AppConfig(_Section):
    server: ServerConfig = ServerConfig()
    typst: TypstConfig = TypstConfig()
    timing: TimingConfig = TimingConfig()
    limits: LimitsConfig = LimitsConfig()
    claude: ClaudeConfig = ClaudeConfig()
    ollama: OllamaConfig = OllamaConfig()
    ltex: LtexConfig = LtexConfig()


def load_config(path: Path | None = None) -> AppConfig:
    """Read the config file; `TYPST_WRITER_CONFIG` overrides the default location."""
    if path is None:
        env_path = os.environ.get(CONFIG_ENV_VAR)
        path = Path(env_path) if env_path else DEFAULT_CONFIG_PATH
    with path.open("rb") as f:
        return AppConfig.model_validate(tomllib.load(f))
