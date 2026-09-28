"""Small helpers shared by the UI tests."""

from playwright.sync_api import Page, expect


def expand_folder(page: Page, name: str) -> None:
    """Expand a folder in the file tree; the tree remembers expanded folders, so it may
    already be open (clicking again would collapse it)."""
    folder = page.get_by_role("treeitem", name=name)
    expect(folder).to_be_visible()
    if folder.get_attribute("aria-expanded") != "true":
        folder.click()
