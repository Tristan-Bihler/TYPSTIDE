"""Phase 6c in the browser: click in the preview to jump to the source, and the preview
follows the cursor."""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from e2e.ui_helpers import expand_folder

CHAPTER = (
    "== Einleitung\n\nDieses Kapitel beschreibt die Arbeit.\n\n#pagebreak()\n"
    "== Methode\n\nErster Absatz der Methode mit etwas Text.\n\n"
    "Zweiter Absatz der Methode, der etwas länger ist als der erste Absatz.\n\n"
    "#pagebreak()\n== Ergebnis\n\nDer Ergebnisabsatz steht auf der dritten Seite.\n"
)


@pytest.fixture
def workspace(workspace: Path) -> Path:
    (workspace / "kapitel" / "01-einleitung.typ").write_text(CHAPTER, encoding="utf-8")
    return workspace


def line_of(text: str) -> int:
    return CHAPTER[: CHAPTER.index(text)].count("\n") + 1


def test_click_in_the_preview_opens_the_chapter_there(page: Page) -> None:
    expect(page.locator(".page")).to_have_count(3)
    second = page.locator(".page").nth(1)
    second.scroll_into_view_if_needed()
    box = second.bounding_box()
    assert box is not None
    # Below the last paragraph of page 2: the nearest element above is that paragraph.
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.6)
    expect(page.get_by_role("tab", name="01-einleitung.typ")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.get_by_text(f"Ln {line_of('Zweiter Absatz')}, Col 1")).to_be_visible()
    # A click on page 1's title goes to main.typ.
    first = page.locator(".page").nth(0)
    first.scroll_into_view_if_needed()
    box = first.bounding_box()
    assert box is not None
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.08)
    expect(page.get_by_role("tab", name="main.typ")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_text("Ln 2, Col 1")).to_be_visible()


def test_preview_follows_the_cursor(page: Page) -> None:
    expect(page.locator(".page")).to_have_count(3)
    desk = page.locator(".desk")
    assert desk.evaluate("d => d.scrollTop") == 0
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    mark = page.locator(".page").nth(2).locator(".preview-mark")
    expect(mark).to_be_visible()
    expect(mark).to_be_in_viewport()
    assert desk.evaluate("d => d.scrollTop") > 0


def test_preview_stays_put_when_following_is_off(page: Page) -> None:
    page.keyboard.press("Control+,")
    dialog = page.locator("dialog.settings-dialog")
    dialog.get_by_label("Preview follows the cursor").uncheck()
    dialog.get_by_role("button", name="Done").click()
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.wait_for_timeout(1000)
    expect(page.locator(".preview-mark")).to_have_count(0)
    assert page.locator(".desk").evaluate("d => d.scrollTop") == 0
