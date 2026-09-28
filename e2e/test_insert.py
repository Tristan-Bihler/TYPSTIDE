"""Phase 2 UI flows: the insert toolbar writes Typst code that compiles."""

from playwright.sync_api import Locator, Page, expect


def open_chapter_at_end(page: Page) -> None:
    page.get_by_role("treeitem", name="kapitel").click()
    page.get_by_role("treeitem", name="01-einleitung.typ").click()
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")


def source(page: Page) -> str:
    return page.locator(".cm-content").inner_text()


def expect_source(page: Page, text: str) -> None:
    """Wait until the editor contains `text` (dialog inserts arrive after a server render)."""
    expect(page.locator(".cm-content")).to_contain_text(text)


def snippet_dialog(page: Page) -> Locator:
    return page.locator("dialog.snippet-dialog")


def expect_compiles(page: Page) -> None:
    expect(page.locator(".compile-status")).to_contain_text("Compiled", timeout=5000)
    expect(page.locator(".problem")).to_have_count(0)


def test_insert_table_via_dialog(page: Page) -> None:
    open_chapter_at_end(page)
    before = page.locator(".page img").first.get_attribute("src")
    page.get_by_role("button", name="Table", exact=True).click()
    dialog = snippet_dialog(page)
    dialog.get_by_label("Rows").fill("2")
    dialog.get_by_label("Columns").fill("4")
    dialog.get_by_label("Caption").fill("Messwerte [kalibriert] #1")
    expect(dialog.get_by_label("Label")).to_have_value("tab:messwerte-kalibriert-1")
    expect(dialog.locator(".code-preview")).to_contain_text("columns: 4")
    dialog.get_by_role("button", name="Insert", exact=True).click()

    expect(dialog).to_have_count(0)
    assert "table.header[*Spalte 1*][*Spalte 2*][*Spalte 3*][*Spalte 4*]" in source(page)
    assert "caption: [Messwerte \\[kalibriert\\] \\#1]" in source(page)
    page.wait_for_function(
        "b => document.querySelector('.page img').getAttribute('src') !== b", arg=before
    )
    expect_compiles(page)
    page.keyboard.type("Weiter im Text.")  # focus is back in the editor, on a fresh line
    assert "\nWeiter im Text." in source(page)


def test_bold_italic_and_shortcuts_wrap_the_selection(page: Page) -> None:
    open_chapter_at_end(page)
    page.keyboard.type("wichtig")
    page.keyboard.press("Shift+Home")
    page.get_by_role("button", name="Bold").click()
    assert "*wichtig*" in source(page)
    page.keyboard.press("Control+i")  # selection is still the word
    assert "*_wichtig_*" in source(page)
    expect_compiles(page)


def test_heading_dropdown_sets_and_replaces_level(page: Page) -> None:
    open_chapter_at_end(page)
    page.keyboard.type("Methodik")
    page.get_by_role("button", name="Heading").click()
    page.get_by_role("menuitem", name="Heading 3").click()
    assert "=== Methodik" in source(page)
    page.get_by_role("button", name="Heading").click()
    page.get_by_role("menuitem", name="Heading 2").click()
    assert "\n== Methodik" in source(page) and "=== Methodik" not in source(page)
    expect_compiles(page)


def test_figure_then_reference_to_it(page: Page) -> None:
    open_chapter_at_end(page)
    page.get_by_role("button", name="Figure", exact=True).click()
    dialog = snippet_dialog(page)
    expect(dialog.get_by_role("option", name="aufbau.svg")).to_have_attribute(
        "aria-selected", "true"
    )
    dialog.get_by_label("Caption").fill("Versuchsaufbau")
    dialog.get_by_role("button", name="Insert", exact=True).click()
    expect_source(page, 'image("/bilder/aufbau.svg", width: 80%)')

    page.keyboard.type("Siehe ")
    page.get_by_role("button", name="Reference", exact=True).click()
    dialog = snippet_dialog(page)
    dialog.get_by_label("Filter").fill("Versuch")
    dialog.get_by_role("option", name="Versuchsaufbau").click()
    expect(dialog.locator(".code-preview")).to_have_text("@fig:versuchsaufbau")
    dialog.get_by_role("button", name="Insert", exact=True).click()
    expect_source(page, "Siehe @fig:versuchsaufbau")
    expect_compiles(page)


def test_citation_offers_to_print_the_bibliography(page: Page) -> None:
    open_chapter_at_end(page)
    page.get_by_role("button", name="Reference", exact=True).click()
    snippet_dialog(page).get_by_role("button", name="Insert bibliography at the cursor").click()
    expect_source(page, '#bibliography("/quellen.bib")')

    page.keyboard.press("Control+Home")
    page.keyboard.press("End")
    page.keyboard.type(" Nach ")
    page.get_by_role("button", name="Reference", exact=True).click()
    dialog = snippet_dialog(page)
    expect(dialog.locator(".note")).to_have_count(0)  # bibliography is printed now
    dialog.get_by_role("option", name="Literate Programming").click()
    dialog.get_by_role("button", name="Insert", exact=True).click()
    expect_source(page, "Nach @knuth1984")
    expect_compiles(page)


def test_equation_with_label_is_numbered(page: Page) -> None:
    open_chapter_at_end(page)
    page.get_by_role("button", name="Equation", exact=True).click()
    dialog = snippet_dialog(page)
    dialog.get_by_label("Formula (Typst math)").fill("E = m c^2")
    dialog.get_by_label("Label").fill("eq:energie")
    dialog.get_by_role("button", name="Insert", exact=True).click()
    expect_source(page, '#math.equation(block: true, numbering: "(1)", $ E = m c^2 $) <eq:energie>')
    expect_compiles(page)
