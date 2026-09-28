"""Phase 1 UI flows in a real browser."""

import time
from pathlib import Path

from playwright.sync_api import Page, expect

from e2e.ui_helpers import expand_folder


def open_chapter(page: Page) -> None:
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()
    expect(page.get_by_role("tab", name="01-einleitung.typ")).to_have_attribute(
        "aria-selected", "true"
    )


def type_at_end(page: Page, text: str) -> None:
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.type(text)


def first_page_src(page: Page) -> str:
    return page.locator(".page img").first.get_attribute("src") or ""


def test_layout_shows_workspace_and_main_badge(page: Page) -> None:
    expect(page.locator(".files .panel-title")).to_have_text("Bachelorarbeit")
    expect(page.get_by_role("treeitem", name="main.typ")).to_contain_text("main")
    expect(page.locator(".compile-status")).to_contain_text("Compiled in")
    ai = page.get_by_role("group", name="AI assistance")
    expect(ai.get_by_label("Local AI")).to_have_value("")
    expect(ai.get_by_label("Claude")).to_have_value("")


def test_unsaved_chapter_edit_updates_main_preview_fast(page: Page) -> None:
    open_chapter(page)
    before = first_page_src(page)
    type_at_end(page, "\nNeuer Satz.")
    typed_at = time.perf_counter()
    page.wait_for_function(
        "before => document.querySelector('.page img').getAttribute('src') !== before", arg=before
    )
    # Includes the 300 ms typing debounce.
    assert time.perf_counter() - typed_at < 1.0

    type_at_end(page, "\n#pagebreak()\nZweite Seite.")
    expect(page.locator(".page")).to_have_count(2)


def test_save_writes_file_and_clears_unsaved_marker(page: Page, workspace: Path) -> None:
    open_chapter(page)
    type_at_end(page, "\nGespeichert.")
    tab = page.get_by_role("tab", name="01-einleitung.typ")
    expect(tab).to_have_class("tab active dirty")
    page.keyboard.press("Control+s")
    expect(tab).to_have_class("tab active")
    content = (workspace / "kapitel" / "01-einleitung.typ").read_text(encoding="utf-8")
    assert content.endswith("\nGespeichert.")


def test_error_is_listed_and_click_jumps_to_it(page: Page) -> None:
    open_chapter(page)
    type_at_end(page, "\n\nSiehe #unbekannt hier.")
    problem = page.locator(".problem.error")
    expect(problem).to_contain_text("unknown variable: unbekannt")
    expect(problem).to_contain_text("6:8")  # Typst points at the identifier
    expect(page.locator(".preview-banner")).to_be_visible()
    expect(page.locator(".compile-status")).to_have_text("1 error")

    page.get_by_role("treeitem", name="main.typ").click()
    expect(page.get_by_role("tab", name="main.typ")).to_have_attribute("aria-selected", "true")
    problem.click()
    expect(page.get_by_role("tab", name="01-einleitung.typ")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.locator(".statusbar")).to_contain_text("Ln 6, Col 8")
    expect(page.locator(".cm-lintRange-error")).to_have_text("unbekannt")


def test_new_file_from_top_bar(page: Page, workspace: Path) -> None:
    page.get_by_role("button", name="New file").click()
    dialog = page.locator("dialog.dialog")
    dialog.get_by_label("File name").fill("bad/name")
    expect(dialog.get_by_role("button", name="Create")).to_be_disabled()
    dialog.get_by_label("File name").fill("anhang")
    dialog.get_by_role("button", name="Create").click()
    expect(page.get_by_role("tab", name="anhang.typ")).to_be_visible()
    assert (workspace / "anhang.typ").is_file()


def test_rename_and_delete_from_context_menu(page: Page, workspace: Path) -> None:
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click(button="right")
    page.get_by_role("menuitem", name="Rename…").click()
    page.locator("dialog.dialog").get_by_label("New name").fill("01-intro.typ")
    page.locator("dialog.dialog").get_by_role("button", name="Rename").click()
    expect(page.get_by_role("treeitem", name="01-intro.typ")).to_be_visible()
    assert (workspace / "kapitel" / "01-intro.typ").is_file()

    page.get_by_role("treeitem", name="01-intro.typ").click(button="right")
    page.get_by_role("menuitem", name="Delete…").click()
    page.locator("dialog.dialog").get_by_role("button", name="Delete").click()
    expect(page.get_by_role("treeitem", name="01-intro.typ")).to_have_count(0)
    assert not (workspace / "kapitel" / "01-intro.typ").exists()
    expect(page.locator(".problem.error")).to_contain_text("01-einleitung.typ")


def test_export_pdf_downloads_main_document(page: Page) -> None:
    with page.expect_download() as info:
        page.get_by_role("button", name="Export PDF").click()
    download = info.value
    assert download.suggested_filename == "main.pdf"
    assert Path(download.path()).read_bytes().startswith(b"%PDF-")
