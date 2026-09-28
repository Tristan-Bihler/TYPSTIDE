"""Phase 4 acceptance with the real LTeX+ (skipped when it is not installed).

Install it once with `python scripts/install_ltex.py`. One test, so LTeX+ starts only once
(about 15-30 s); the steps are the acceptance criteria from CLAUDE.md:
German errors are found, a re-check takes < 500 ms, Typst markup gives no false alarms.
"""

import statistics
import time
from pathlib import Path

import pytest

from typst_writer.adapters.ltex import LtexChecker
from typst_writer.config import load_config
from typst_writer.domain.models import Suggestion
from typst_writer.infra.ltex_install import find_installation

pytestmark = [pytest.mark.anyio, pytest.mark.ltex]

# Looked up at import time, before the autouse fixture points the app home elsewhere.
INSTALLATION = find_installation(load_config().ltex)
FIXTURES = Path(__file__).parent / "fixtures"

GERMAN_ERRORS = (
    "= Einleitung\n\n"
    "Das ist ein ein Satz mit einem Fehlr, wie in @sec:einleitung beschrieben. "
    "Die Kinder spielt draußen.\n"
)


def _originals(found: list[Suggestion]) -> list[str]:
    return [s.original for s in found]


@pytest.mark.skipif(INSTALLATION is None, reason="LTeX+ not installed (scripts/install_ltex.py)")
async def test_real_ltex_acceptance() -> None:
    assert INSTALLATION is not None
    config = load_config()
    checker = LtexChecker(
        INSTALLATION.command(),
        INSTALLATION.home,
        max_message_bytes=config.limits.max_lsp_message_bytes,
        startup_timeout_s=config.ltex.startup_timeout_seconds,
        check_timeout_s=config.ltex.check_timeout_seconds,
    )
    try:
        # 1. German errors are found, with fixes.
        found = await checker.check("kapitel/a.typ", GERMAN_ERRORS, "de-DE", [])
        originals = _originals(found)
        assert "Fehlr" in originals
        assert "ein ein" in originals
        assert any("spielt" in o for o in originals), originals
        fehlr = next(s for s in found if s.original == "Fehlr")
        assert fehlr.category == "spelling"
        assert "Fehler" in fehlr.fixes
        assert all(not o.startswith(("@", "<", "=")) for o in originals)

        # 2. Re-checks after warm-up are fast (target: underline < 500 ms after typing).
        durations = []
        for i in range(5):
            text = GERMAN_ERRORS.replace("draußen", f"draußen {i}")
            start = time.perf_counter()
            await checker.check("kapitel/a.typ", text, "de-DE", [])
            durations.append((time.perf_counter() - start) * 1000)
        print(f"re-check durations (ms): {[round(d) for d in durations]}")
        assert statistics.median(durations) < 500

        # 3. No false alarms on Typst markup, German and English.
        german = (FIXTURES / "grammar_markup.typ").read_text(encoding="utf-8")
        assert _originals(await checker.check("markup.typ", german, "de-DE", [])) == []
        english = (FIXTURES / "grammar_markup_en.typ").read_text(encoding="utf-8")
        assert _originals(await checker.check("markup_en.typ", english, "en-US", [])) == []

        # 4. The dictionary is applied.
        found = await checker.check("kapitel/a.typ", GERMAN_ERRORS, "de-DE", ["Fehlr"])
        assert "Fehlr" not in _originals(found)
    finally:
        await checker.close()
