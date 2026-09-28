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
from typst_writer.domain.errors import CheckerUnavailableError, InvalidNameError
from typst_writer.domain.models import (
    MAX_DICTIONARY_WORDS,
    GrammarSettings,
    Language,
    Suggestion,
)
from typst_writer.infra.ltex_install import (
    DOWNLOAD_MB,
    InstallPhase,
    LtexInstallation,
    LtexInstallError,
    find_installation,
    install,
)
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
    settings: GrammarSettings


class GrammarService:
    def __init__(self, config: AppConfig, settings: SettingsService) -> None:
        self._config = config
        self._settings = settings
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
        return GrammarOverview(status=self.status(), settings=self._settings.grammar())

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
        except LtexInstallError as exc:
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
        return self._settings.grammar()

    def set_language(self, language: Language) -> GrammarOverview:
        current = self._settings.grammar()
        self._settings.save_grammar(current.model_copy(update={"language": language}))
        return self.overview()

    def add_word(self, language: Language, word: str) -> GrammarOverview:
        current = self._settings.grammar()
        words = list(current.dictionary.get(language, []))
        if word not in words:
            if len(words) >= MAX_DICTIONARY_WORDS:
                raise InvalidNameError(f"The dictionary is full ({MAX_DICTIONARY_WORDS} words).")
            words.append(word)
        dictionary = {**current.dictionary, language: sorted(words, key=str.casefold)}
        self._settings.save_grammar(current.model_copy(update={"dictionary": dictionary}))
        return self.overview()

    # --- checking ----------------------------------------------------------------------

    async def check(self, path: str, source: str) -> list[Suggestion]:
        settings = self._settings.grammar()
        words = settings.dictionary.get(settings.language, [])
        return await self._checker.check(path, source, settings.language, words)

    async def forget(self, path: str) -> None:
        await self._checker.forget(path)
