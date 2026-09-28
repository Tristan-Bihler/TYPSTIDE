"""Autocomplete with the real Tinymist (skipped when it is not installed).

Install it once with `python scripts/install_tinymist.py`.
"""

import asyncio
import time
from pathlib import Path

import pytest

from typst_writer.adapters.tinymist import TinymistCompleter
from typst_writer.config import load_config
from typst_writer.domain.models import CompletionItem
from typst_writer.infra.tinymist_install import find_installation

pytestmark = [pytest.mark.anyio, pytest.mark.tinymist]

# Looked up at import time, before the autouse fixture points the app home elsewhere.
PROGRAM = find_installation(load_config().tinymist)


@pytest.mark.skipif(PROGRAM is None, reason="Tinymist not installed (scripts/install_tinymist.py)")
async def test_real_tinymist_completes_functions_and_labels(tmp_path: Path) -> None:
    assert PROGRAM is not None
    root = tmp_path / "arbeit"
    (root / "kapitel").mkdir(parents=True)
    (root / "main.typ").write_text(
        '#set heading(numbering: "1.")\n= Titel <sec:titel>\n#include "kapitel/a.typ"\n',
        encoding="utf-8",
    )
    (root / "kapitel" / "a.typ").write_text(
        "== Kapitel <sec:kap>\n\n#figure([x], caption: [Bild]) <fig:bild>\n", encoding="utf-8"
    )
    config = load_config()
    completer = TinymistCompleter(
        [str(PROGRAM), "lsp"],
        max_message_bytes=config.limits.max_lsp_message_bytes,
        startup_timeout_s=config.tinymist.startup_timeout_seconds,
        request_timeout_s=config.tinymist.request_timeout_seconds,
    )
    chapter = (
        "== Kapitel <sec:kap>\n\nSiehe @ und #fi\n\n#figure([x], caption: [Bild]) <fig:bild>\n"
    )
    root = root.resolve()

    async def at(needle: str) -> list[CompletionItem]:
        offset = chapter.index(needle) + len(needle)
        return await completer.complete(root, "main.typ", "kapitel/a.typ", chapter, offset)

    try:
        functions = await at("#fi")
        figure = next(i for i in functions if i.label == "figure")
        assert figure.kind == "function"
        assert (figure.start, figure.end) == (chapter.index("#fi") + 1, chapter.index("#fi") + 3)
        labels: list[str] = []
        for _ in range(20):  # labels need Tinymist's first compile of the pinned main file
            labels = [i.label for i in await at("@")]
            if labels:
                break
            await asyncio.sleep(0.25)
        assert {"sec:titel", "sec:kap", "fig:bild"} <= set(labels)
        started = time.perf_counter()
        await at("#fi")
        assert time.perf_counter() - started < 0.5
    finally:
        await completer.close()
