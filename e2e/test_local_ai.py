"""Local AI live check in the browser (fake Ollama: "weil er hat keine Zeit" and
"die Ergebnis" are wrong; every paragraph it receives is logged)."""

import json
from pathlib import Path

from playwright.sync_api import Locator, Page, expect

from e2e.ui_helpers import expand_folder

UNTOUCHED = "Dieser Absatz bleibt, wie er ist, weil er hat keine Zeit für Änderungen."
CHAPTER = f"== Einleitung\n\n{UNTOUCHED}\n\nDer zweite Absatz wird gleich bearbeitet."
ADDED = " Das geht nicht, weil er hat keine Zeit dafür."


def sent(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def open_chapter(page: Page, workspace: Path) -> None:
    (workspace / "kapitel" / "01-einleitung.typ").write_text(CHAPTER, encoding="utf-8")
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()


def choose_local(page: Page, model: str) -> None:
    local = page.get_by_label("Local AI", exact=True)
    local.select_option(model)
    expect(local).to_have_value(model)


def type_at_end(page: Page, text: str) -> None:
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(text)


def blue(page: Page, text: str) -> Locator:
    return page.locator(".cm-suggestion-local_ai", has_text=text)


def test_edited_paragraph_gets_a_suggestion_after_a_pause(
    page: Page, workspace: Path, ollama_log: Path
) -> None:
    choose_local(page, "fake-model:1b")
    open_chapter(page, workspace)
    before = len(sent(ollama_log))
    type_at_end(page, ADDED)
    expect(blue(page, "weil er hat keine Zeit")).to_be_visible(timeout=8000)
    expect(page.locator(".problem.ai")).to_contain_text("Im Nebensatz steht das Verb am Ende.")
    # Only the edited paragraph was sent; the untouched one (same mistake) never was.
    new = sent(ollama_log)[before:]
    assert new == ["Der zweite Absatz wird gleich bearbeitet." + ADDED]

    blue(page, "weil er hat keine Zeit").hover()
    card = page.locator(".suggestion-card.local_ai")
    expect(card).to_contain_text("Im Nebensatz steht das Verb am Ende.")
    expect(card.get_by_role("button", name="Add to dictionary")).to_have_count(0)
    card.get_by_role("button", name="weil er keine Zeit hat").click()
    expect(page.locator(".cm-line").last).to_contain_text("weil er keine Zeit hat dafür.")
    expect(blue(page, "weil er hat keine Zeit")).to_have_count(0)


def test_ignore_hides_a_local_suggestion(page: Page, workspace: Path) -> None:
    choose_local(page, "fake-model:1b")
    open_chapter(page, workspace)
    type_at_end(page, " Und die Ergebnis auch.")
    expect(blue(page, "die Ergebnis")).to_be_visible(timeout=8000)
    blue(page, "die Ergebnis").hover()
    page.locator(".suggestion-card").get_by_role("button", name="Ignore").click()
    expect(blue(page, "die Ergebnis")).to_have_count(0)
    expect(page.locator(".problem.ai")).to_have_count(0)


def test_local_ai_none_sends_nothing(page: Page, workspace: Path, ollama_log: Path) -> None:
    open_chapter(page, workspace)
    before = len(sent(ollama_log))
    type_at_end(page, ADDED)
    page.wait_for_timeout(2500)  # longer than the typing pause
    assert len(sent(ollama_log)) == before
    expect(page.locator(".cm-suggestion-local_ai")).to_have_count(0)
