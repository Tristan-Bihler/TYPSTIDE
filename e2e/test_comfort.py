"""Phase 6a in the browser: settings and theme, find & replace, remembered tabs,
autosave and word count."""

from pathlib import Path

from playwright.sync_api import Page, expect

from e2e.ui_helpers import expand_folder


def open_chapter(page: Page) -> None:
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()


def test_theme_switch_applies_and_is_remembered(page: Page) -> None:
    page.get_by_role("button", name="Settings").click()
    dialog = page.locator("dialog.settings-dialog")
    dialog.locator(".segment", has_text="Dark").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    dialog.get_by_role("button", name="Done").click()
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.keyboard.press("Control+,")
    page.locator("dialog.settings-dialog .segment", has_text="Like the system").click()
    expect(page.locator("html")).not_to_have_attribute("data-theme", "dark")


def test_find_and_replace(page: Page) -> None:
    open_chapter(page)
    page.locator(".cm-content").click()
    page.keyboard.press("Control+h")
    panel = page.locator(".cm-search")
    panel.get_by_placeholder("Find").fill("Arbeit")
    panel.get_by_placeholder("Replace with").fill("Thesis")
    panel.get_by_role("button", name="Replace all").click()
    expect(page.locator(".cm-content")).to_contain_text("beschreibt die Thesis.")
    expect(page.locator(".tab.dirty")).to_have_count(1)


def test_open_tabs_come_back_after_a_reload(page: Page) -> None:
    open_chapter(page)
    page.get_by_role("treeitem", name="main.typ").click()
    page.get_by_role("tab", name="01-einleitung.typ").click()
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.wait_for_timeout(1300)  # tabs are remembered after 1 s
    page.reload()
    expect(page.get_by_role("tab")).to_have_count(2)
    expect(page.get_by_role("tab", name="01-einleitung.typ")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.get_by_text("Ln 4, Col 1")).to_be_visible()  # cursor restored at the end


def test_autosave_writes_the_file(page: Page, workspace: Path) -> None:
    page.keyboard.press("Control+,")
    page.locator("dialog.settings-dialog").get_by_label("Save automatically").check()
    page.locator("dialog.settings-dialog").get_by_role("button", name="Done").click()
    expect(page.locator("dialog.settings-dialog")).to_have_count(0)
    open_chapter(page)
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.type("Automatisch gespeichert.")
    expect(page.locator(".save-notice")).to_have_text("Saved", timeout=6000)
    assert "Automatisch gespeichert." in (workspace / "kapitel" / "01-einleitung.typ").read_text()
    expect(page.locator(".tab.dirty")).to_have_count(0)


def test_word_count_for_file_and_document(page: Page) -> None:
    # main: "Bachelorarbeit"; chapter: "Einleitung" + 5 words ("#set …" is code).
    expect(page.locator(".word-count")).to_have_text("7 words")
    open_chapter(page)
    expect(page.locator(".word-count")).to_have_text("6 of 7 words")
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" Zwei mehr.")
    expect(page.locator(".word-count")).to_have_text("8 of 9 words")
