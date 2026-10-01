// Top bar: file actions on the left, the insert toolbar (Phase 2) on the right.

import type { Actions } from "../state/actions";
import { isDirty, type AppState, type Store } from "../state/store";
import { el } from "../ui/dom";
import { iconNode, icons } from "../ui/icons";
import { targetFolder } from "../filetree/tree";

function action(label: string, icon: string, title: string, run: () => void): HTMLButtonElement {
  const button = el("button", { type: "button", class: "tool", title, "aria-label": label }, iconNode(icon), el("span", {}, label));
  button.addEventListener("click", run);
  return button;
}

/** Returns the (empty) insert-toolbar element for mountInsertToolbar. */
export function mountTopbar(host: HTMLElement, store: Store<AppState>, actions: Actions): HTMLElement {
  const newFile = action("New file", icons.newFile, "New .typ file", () => void actions.newFile(targetFolder()));
  const newFolder = action("New folder", icons.newFolder, "New folder", () => void actions.newFolder(targetFolder()));
  const open = action("Open folder", icons.openFolder, "Open a folder as workspace", () => void actions.openFolderDialog());
  const save = action("Save", icons.save, "Save all changed files (Ctrl+S)", () => void actions.saveAll());
  const exportPdf = action("Export PDF", icons.exportPdf, "Export the main document as PDF", () => void actions.exportPdf());

  const fileGroup = el("div", { class: "tool-group", role: "toolbar", "aria-label": "File" }, newFile, newFolder, open, save, exportPdf);
  // Filled from snippets.toml by mountInsertToolbar.
  const insertGroup = el("div", { class: "tool-group insert-toolbar", role: "toolbar", "aria-label": "Insert" });
  const settings = el(
    "button",
    { type: "button", class: "tool settings-button", title: "Settings (Ctrl+,)", "aria-label": "Settings" },
    iconNode(icons.settings),
  );
  settings.addEventListener("click", () => actions.openSettings());
  const plans = el(
    "button",
    { type: "button", class: "tool plans-button", title: "Plans: break a task into steps", "aria-haspopup": "menu" },
    iconNode(icons.plans),
    el("span", {}, "Plans"),
  );
  plans.addEventListener("click", () => void actions.showPlans(plans));
  host.append(fileGroup, el("div", { class: "tool-divider", role: "presentation" }), insertGroup, plans, settings);

  store.subscribe((state) => {
    const hasWorkspace = state.workspace !== null;
    newFile.disabled = !hasWorkspace;
    newFolder.disabled = !hasWorkspace;
    save.disabled = !state.docs.some(isDirty);
    exportPdf.disabled = state.workspace?.main == null;
    plans.hidden = !state.ui.planner_enabled;
    plans.disabled = !hasWorkspace;
    plans.classList.toggle("active", state.planner !== null);
  });
  return insertGroup;
}
