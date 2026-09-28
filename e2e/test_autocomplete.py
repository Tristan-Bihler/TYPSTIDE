"""Phase 6d in the browser: autocomplete with the fake Tinymist."""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from e2e.ui_helpers import expand_folder


@pytest.fixture
def workspace(workspace: Path) -> Path:
    main = workspace / "main.typ"
    main.write_text(main.read_text().replace("= Bachelorarbeit", "= Bachelorarbeit <sec:arbeit>"))
    return workspace


def open_chapter_at_end(page: Page) -> None:
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")


def test_function_completion_inserts_a_snippet(page: Page) -> None:
    open_chapter_at_end(page)
    page.keyboard.type("#fi")
    popup = page.locator(".cm-tooltip-autocomplete")
    expect(popup.get_by_role("option").first).to_contain_text("figure")
    expect(popup).to_contain_text("(..) => figure")
    page.wait_for_timeout(150)  # CodeMirror ignores Enter for 75 ms after the list appears
    page.keyboard.press("Enter")
    page.keyboard.type("Bild")  # the snippet's first field ("body") is selected
    expect(page.locator(".cm-content")).to_contain_text("#figure(Bild)")


def test_labels_from_other_files_after_at(page: Page) -> None:
    open_chapter_at_end(page)
    page.keyboard.type("Siehe @")
    popup = page.locator(".cm-tooltip-autocomplete")
    expect(popup.get_by_role("option", name="sec:arbeit")).to_be_visible()
    page.keyboard.type("sec:a")
    page.keyboard.press("Enter")
    expect(page.locator(".cm-content")).to_contain_text("Siehe @sec:arbeit")


def test_prose_does_not_ask_for_completions(page: Page) -> None:
    open_chapter_at_end(page)
    page.keyboard.type(" Ein Satz. Noch einer")
    page.wait_for_timeout(500)
    expect(page.locator(".cm-tooltip-autocomplete")).to_have_count(0)


def test_settings_show_autocomplete_ready(page: Page) -> None:
    page.keyboard.press("Control+,")
    dialog = page.locator("dialog.settings-dialog")
    expect(dialog.locator(".setting-row", has_text="Tinymist")).to_contain_text("Ready (offline)")
