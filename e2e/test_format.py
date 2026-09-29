"""Format controls in the browser: font, size and line spacing on a selection, and the
whole-document defaults when nothing is selected."""

from playwright.sync_api import Page, expect

from e2e.ui_helpers import expand_folder


def open_chapter(page: Page) -> None:
    expand_folder(page, "kapitel")
    page.get_by_role("treeitem", name="01-einleitung.typ").click()
    expect(page.locator(".format-font")).to_be_enabled()


def pick(page: Page, control: str, option: str) -> None:
    page.locator(f".format-{control}").click()
    page.locator(".format-popup .format-option", has_text=option).first.click()


def test_size_then_font_on_a_selection_make_one_text_call(page: Page) -> None:
    open_chapter(page)
    page.locator(".cm-content").get_by_text("Dieses Kapitel").dblclick(position={"x": 70, "y": 5})
    pick(page, "size", "14")
    content = page.locator(".cm-content")
    expect(content).to_contain_text("#text(size: 14pt)[Kapitel]")
    expect(page.locator(".compile-status")).to_contain_text("Compiled")
    # The wrapped text stays selected: the font goes into the same call.
    page.locator(".format-font").click()
    page.keyboard.type("dejavu sans mono")
    page.keyboard.press("Enter")
    expect(content).to_contain_text('#text(size: 14pt, font: "DejaVu Sans Mono")[Kapitel]')
    expect(page.locator(".format-font-name")).to_have_text("DejaVu Sans Mono")
    expect(page.locator(".format-size .format-value")).to_have_text("14")
    page.keyboard.press("Control+z")
    expect(content).to_contain_text("#text(size: 14pt)[Kapitel]")


def test_line_spacing_wraps_the_whole_paragraph(page: Page) -> None:
    open_chapter(page)
    page.locator(".cm-content").get_by_text("Dieses Kapitel").dblclick(position={"x": 5, "y": 5})
    expect(page.locator(".format-spacing")).to_have_attribute(
        "title", "Line spacing: The selected paragraphs"
    )
    pick(page, "spacing", "1.5")
    expect(page.locator(".cm-content")).to_contain_text(
        "#[#set par(leading: 1.05em)Dieses Kapitel beschreibt die Arbeit.]"
    )
    expect(page.locator(".compile-status")).to_contain_text("Compiled")


def test_without_a_selection_the_whole_document_changes(page: Page) -> None:
    open_chapter(page)
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    expect(page.locator(".format-size")).to_have_attribute(
        "title", "Font size: Whole document (main.typ)"
    )
    pick(page, "size", "12")
    expect(page.get_by_role("tab", name="main.typ")).to_have_attribute("aria-selected", "true")
    expect(page.locator(".cm-content")).to_contain_text(
        '#set page(numbering: "1")#set text(size: 12pt)= Bachelorarbeit'
    )
    expect(page.locator(".save-notice")).to_have_text("Set for the whole document in main.typ")
    # Back in the chapter, the size in effect comes from the main file.
    page.get_by_role("tab", name="01-einleitung.typ").click()
    page.locator(".cm-content").click()
    expect(page.locator(".format-size .format-value")).to_have_text("12")
