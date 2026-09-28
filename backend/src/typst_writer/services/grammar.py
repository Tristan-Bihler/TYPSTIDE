"""Spelling and grammar checks: which checker runs, installing LTeX+, language, dictionary.

While LTeX+ is not installed the NoneRuleChecker answers (no findings), so callers never
branch on it. Installing happens only when the user asks (POST /api/grammar/install);
afterwards LTeX+ starts and is warmed up with a tiny check so the first real check is fast.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine

from pydantic import BaseModel

from typst_writer.adapters.ltex import LtexChecker
from typst_writer.adapters.none_checker import NoneRuleChecker
from typst_writer.config import AppConfig
from typst_writer.domain.errors import CheckerUnavailableError, InvalidNameError, NoWorkspaceError
from typst_writer.domain.models import (
    MAX_DICTIONARY_WORDS,
    GrammarSettings,
    GrammarView,
    Language,
    Suggestion,
)
from typst_writer.infra.ltex_install import (
    DOWNLOAD_MB,
    LtexInstallation,
    find_installation,
    install,
)
from typst_writer.infra.tool_download import InstallError, InstallPhase
from typst_writer.ports.rule_checker import CheckerStatus, RuleChecker
from typst_writer.services.settings import SettingsService

log = logging.getLogger(__name__)

NOT_INSTALLED = (
    f"Spelling and grammar checks need LTeX+ (about {DOWNLOAD_MB} MB, downloaded once, "
    "then offline). Click Install."
)
WARM_UP_TEXT: dict[Language, str] = {"de-DE": "Das ist ein Satz.", "en-US": "This is a sentence."}

StatusListener = Callable[[CheckerStatus], None]


class GrammarOverview(BaseModel):
    status: CheckerStatus
    settings: GrammarView


class GrammarService:
    def __init__(
        self,
        config: AppConfig,
        settings: SettingsService,
        project: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._project = project  # absolute path of the open folder, if any
        self._listeners: set[StatusListener] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._install_status: CheckerStatus | None = None  # while installing
        installation = find_installation(config.ltex)
        self._checker: RuleChecker = (
            self._ltex(installation)
            if installation is not None
            else NoneRuleChecker(CheckerStatus(state="not_installed", reason=NOT_INSTALLED))
        )

    def _ltex(self, installation: LtexInstallation) -> LtexChecker:
        return LtexChecker(
            installation.command(),
            installation.home,
            max_message_bytes=self._config.limits.max_lsp_message_bytes,
            startup_timeout_s=self._config.ltex.startup_timeout_seconds,
            check_timeout_s=self._config.ltex.check_timeout_seconds,
            on_status=self._publish,
        )

    # --- status ------------------------------------------------------------------------

    def status(self) -> CheckerStatus:
        return self._install_status or self._checker.status()

    def overview(self) -> GrammarOverview:
        settings = self.settings()
        project = self._project()
        words = settings.dictionaries.get(project, {}) if project is not None else {}
        view = GrammarView(language=settings.language, dictionary=words)
        return GrammarOverview(status=self.status(), settings=view)

    def subscribe(self, listener: StatusListener) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _publish(self, status: CheckerStatus | None = None) -> None:
        current = status or self.status()
        for listener in list(self._listeners):
            listener(current)

    def _spawn(self, coro: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --- lifecycle ---------------------------------------------------------------------

    async def startup(self) -> None:
        """Start LTeX+ in the background if it is installed (never blocks the app start)."""
        if isinstance(self._checker, LtexChecker):
            self._spawn(self._warm_up())

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._checker.close()

    async def _warm_up(self) -> None:
        language = self._settings.grammar().language
        with contextlib.suppress(CheckerUnavailableError):
            await self._checker.check("warm-up.typ", WARM_UP_TEXT[language], language, [])
            await self._checker.forget("warm-up.typ")

    def install(self) -> GrammarOverview:
        """Download and start LTeX+ in the background; progress arrives as status updates."""
        if self.status().state == "not_installed":
            self._install_status = CheckerStatus(
                state="installing", reason="Downloading LTeX+…", progress=0.0
            )
            self._publish()
            self._spawn(self._install())
        return self.overview()

    async def _install(self) -> None:
        shown = -1

        def progress(phase: InstallPhase, done: int, total: int | None) -> None:
            nonlocal shown
            if phase == "unpack":
                self._install_status = CheckerStatus(state="installing", reason="Unpacking LTeX+…")
                self._publish()
            elif total:
                percent = done * 100 // total
                if percent != shown:
                    shown = percent
                    self._install_status = CheckerStatus(
                        state="installing",
                        reason=f"Downloading LTeX+… {percent} %",
                        progress=done / total,
                    )
                    self._publish()

        try:
            installation = await install(self._config.ltex, progress)
        except InstallError as exc:
            log.warning("LTeX+ install failed: %s", exc)
            self._checker = NoneRuleChecker(
                CheckerStatus(state="not_installed", reason=f"{exc} Click Install to try again.")
            )
            self._install_status = None
            self._publish()
            return
        self._checker = self._ltex(installation)
        self._install_status = None
        self._publish()
        await self._warm_up()

    # --- settings ----------------------------------------------------------------------

    def settings(self) -> GrammarSettings:
        """The stored settings; a global word list from before Phase 6 moves into the open
        project the first time one is open."""
        settings = self._settings.grammar()
        project = self._project()
        if project is None or not settings.dictionary:
            return settings
        words = dict(settings.dictionaries.get(project, {}))
        for language, legacy in settings.dictionary.items():
            merged = set(words.get(language, [])) | set(legacy)
            words[language] = sorted(merged, key=str.casefold)[:MAX_DICTIONARY_WORDS]
        settings = settings.model_copy(
            update={"dictionary": {}, "dictionaries": {**settings.dictionaries, project: words}}
        )
        self._settings.save_grammar(settings)
        return settings

    def _project_words(self, language: Language) -> list[str]:
        project = self._project()
        if project is None:
            return []
        return list(self.settings().dictionaries.get(project, {}).get(language, []))

    def _save_project_words(self, language: Language, words: list[str]) -> None:
        project = self._project()
        if project is None:
            raise NoWorkspaceError()
        current = self.settings()
        project_words = {**current.dictionaries.get(project, {}), language: words}
        dictionaries = {**current.dictionaries, project: project_words}
        self._settings.save_grammar(current.model_copy(update={"dictionaries": dictionaries}))

    def set_language(self, language: Language) -> GrammarOverview:
        current = self.settings()
        self._settings.save_grammar(current.model_copy(update={"language": language}))
        return self.overview()

    def add_word(self, language: Language, word: str) -> GrammarOverview:
        """Accept `word` in the open project's word list."""
        words = self._project_words(language)
        if word not in words:
            if len(words) >= MAX_DICTIONARY_WORDS:
                raise InvalidNameError(f"The word list is full ({MAX_DICTIONARY_WORDS} words).")
            words.append(word)
        self._save_project_words(language, sorted(words, key=str.casefold))
        return self.overview()

    def remove_word(self, language: Language, word: str) -> GrammarOverview:
        words = [w for w in self._project_words(language) if w != word]
        self._save_project_words(language, words)
        return self.overview()

    # --- checking ----------------------------------------------------------------------

    async def check(self, path: str, source: str) -> list[Suggestion]:
        language = self._settings.grammar().language
        return await self._checker.check(path, source, language, self._project_words(language))

    async def forget(self, path: str) -> None:
        await self._checker.forget(path)
