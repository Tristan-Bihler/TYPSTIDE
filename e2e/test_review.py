"""Phase 3 UI flows: AI selector and the Claude review (fake claude on PATH)."""

from playwright.sync_api import Page, expect


def select_last_sentence(page: Page) -> None:
    """Type a sentence on a new line in the chapter and select it."""
    page.get_by_role("treeitem", name="kapitel").click()
    page.get_by_role("treeitem", name="01-einleitung.typ").click()
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.type("\nEin Fehlr, sehr sehr deutlich.")
    page.keyboard.press("Shift+Home")


def choose_claude(page: Page, model: str) -> None:
    page.get_by_label("Claude", exact=True).select_option(model)
    expect(page.get_by_label("Claude", exact=True)).to_have_value(model)


def test_selector_defaults_to_none_and_lists_claude_models(page: Page) -> None:
    claude = page.get_by_label("Claude", exact=True)
    expect(claude).to_have_value("")
    expect(claude).to_be_enabled()
    expect(claude.locator("option")).to_have_text(["None", "sonnet", "opus", "haiku"])
    local = page.get_by_label("Local AI", exact=True)
    expect(local).to_be_disabled()
    expect(local).to_have_attribute(
        "title", "Local AI (Ollama) comes in a later version of typst-writer."
    )


def test_review_needs_a_model_and_editor_still_works(page: Page) -> None:
    select_last_sentence(page)
    page.keyboard.press("Control+Shift+k")
    dialog = page.locator("dialog.dialog")
    expect(dialog).to_contain_text("Choose a Claude model at the bottom right first.")
    dialog.get_by_role("button", name="OK").click()

    page.locator(".cm-content").click(button="right")  # the selection survives the click
    item = page.get_by_role("menuitem", name="Review with Claude")
    expect(item).to_be_disabled()
    page.keyboard.press("Escape")
    expect(page.locator(".compile-status")).to_contain_text("Compiled")


def test_review_accept_one_change_reject_the_other(page: Page) -> None:
    choose_claude(page, "sonnet")
    select_last_sentence(page)
    page.keyboard.press("Control+Shift+k")
    page.get_by_role("button", name="Improve").click()

    diff = page.locator("dialog.diff-dialog")
    changes = diff.locator(".change")
    expect(changes).to_have_count(2)
    expect(changes.nth(0)).to_contain_text("Fehlr→Fehler")
    changes.nth(1).get_by_role("button", name="Reject").click()
    diff.get_by_role("button", name="Apply 1 change").click()

    expect(page.locator(".cm-content")).to_contain_text("Ein Fehler, sehr sehr deutlich.")
    expect(page.locator(".compile-status")).to_contain_text("Compiled")
    page.keyboard.press("Control+z")  # one undo step reverts the review
    expect(page.locator(".cm-content")).to_contain_text("Ein Fehlr, sehr sehr deutlich.")


def test_review_from_the_context_menu(page: Page) -> None:
    choose_claude(page, "haiku")
    select_last_sentence(page)
    page.locator(".cm-content").click(button="right")
    page.get_by_role("menuitem", name="Review with Claude").click()
    page.get_by_role("button", name="Check").click()
    diff = page.locator("dialog.diff-dialog")
    diff.get_by_role("button", name="Apply 2 changes").click()
    expect(page.locator(".cm-content")).to_contain_text("Ein Fehler, sehr deutlich.")
