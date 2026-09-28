"""Spelling and grammar in the browser (fake LTeX+: "Fehlr" and "durchgefürt" in German,
"teh" in English are misspelled; repeated words are flagged)."""

from pathlib import Path

from playwright.sync_api import Locator, Page, expect

from e2e.ui_helpers import expand_folder

CHAPTER = "Ein Fehlr im Text.\nDer Versuch wird durchgefürt.\n"


def open_chapter(page: Page, workspace: Path, content: str = CHAPTER) -> None:
    (workspace / "kapitel" / "01-einleitung.typ").write_text(content, encoding="utf-8")
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()


def underline(page: Page, word: str) -> Locator:
    return page.locator(".cm-suggestion-rule", has_text=word)


def test_findings_are_underlined_listed_and_clickable(page: Page, workspace: Path) -> None:
    open_chapter(page, workspace)
    expect(underline(page, "Fehlr")).to_be_visible()
    expect(underline(page, "durchgefürt")).to_be_visible()
    expect(page.locator(".checker-status")).to_have_text("2 spelling issues")
    problem = page.locator(".problem.grammar", has_text="Fehlr")
    expect(problem).to_contain_text("1:5")
    problem.click()
    expect(page.get_by_text("Ln 1, Col 5")).to_be_visible()


def test_apply_a_fix_from_the_hover_card(page: Page, workspace: Path) -> None:
    open_chapter(page, workspace)
    underline(page, "Fehlr").hover()
    card = page.locator(".suggestion-card")
    expect(card).to_contain_text("Possible spelling mistake")
    card.get_by_role("button", name="Fehler").click()
    expect(page.locator(".cm-line").first).to_have_text("Ein Fehler im Text.")
    expect(underline(page, "Fehlr")).to_have_count(0)
    expect(page.locator(".checker-status")).to_have_text("1 spelling issue")


def test_keyboard_opens_the_card_at_the_cursor(page: Page, workspace: Path) -> None:
    open_chapter(page, workspace)
    expect(underline(page, "Fehlr")).to_be_visible()
    page.locator(".cm-content").click()
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowRight")  # "E|in"
    for _ in range(4):
        page.keyboard.press("ArrowRight")  # inside "Fehlr"
    page.keyboard.press("Control+.")
    fix = page.locator(".suggestion-card").get_by_role("button", name="Fehler")
    expect(fix).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator(".cm-line").first).to_have_text("Ein Fehler im Text.")


def test_ignore_keeps_the_finding_hidden_after_rechecks(page: Page, workspace: Path) -> None:
    open_chapter(page, workspace, "Ein Fehlr hier und ein Fehlr dort.\n")
    expect(underline(page, "Fehlr")).to_have_count(2)
    underline(page, "Fehlr").first.hover()
    page.locator(".suggestion-card").get_by_role("button", name="Ignore").click()
    expect(underline(page, "Fehlr")).to_have_count(0)
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" Es ist das das Neue.")
    expect(underline(page, "das das")).to_be_visible()  # a new check ran
    expect(underline(page, "Fehlr")).to_have_count(0)
    expect(page.locator(".problem.grammar", has_text="Fehlr")).to_have_count(0)


def test_add_to_dictionary(page: Page, workspace: Path) -> None:
    # "Beispeil" is used only here: the dictionary is kept for the whole test session.
    open_chapter(page, workspace, "Ein Fehlr und ein Beispeil.\n")
    underline(page, "Beispeil").hover()
    page.locator(".suggestion-card").get_by_role("button", name="Add to dictionary").click()
    expect(underline(page, "Beispeil")).to_have_count(0)
    expect(underline(page, "Fehlr")).to_be_visible()
    page.reload()
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()
    expect(underline(page, "Fehlr")).to_be_visible()
    expect(underline(page, "Beispeil")).to_have_count(0)  # stays accepted


def test_switching_the_language_rechecks(page: Page, workspace: Path) -> None:
    open_chapter(page, workspace, "Ein Fehlr and teh end.\n")
    expect(underline(page, "Fehlr")).to_be_visible()
    expect(underline(page, "teh")).to_have_count(0)
    page.get_by_label("Document language").select_option("en-US")
    expect(underline(page, "teh")).to_be_visible()
    expect(underline(page, "Fehlr")).to_have_count(0)


def test_word_list_in_settings(page: Page, workspace: Path) -> None:
    open_chapter(page, workspace)
    expect(underline(page, "Fehlr")).to_be_visible()
    page.keyboard.press("Control+,")
    words = page.locator(".words-section")
    expect(words).to_contain_text("in Bachelorarbeit")
    words.get_by_label("New word").fill("zwei Wörter")
    words.get_by_role("button", name="Add").click()
    expect(words.get_by_role("alert")).to_have_text("One word at a time (no spaces).")
    words.get_by_label("New word").fill("Fehlr")
    words.get_by_role("button", name="Add").click()
    expect(words.locator(".word")).to_have_text(["Fehlr"])
    expect(underline(page, "Fehlr")).to_have_count(0)  # rechecked with the new word
    words.get_by_role("button", name="Remove Fehlr").click()
    expect(words.locator(".word")).to_have_count(0)
    page.locator("dialog.settings-dialog").get_by_role("button", name="Done").click()
    expect(underline(page, "Fehlr")).to_be_visible()
