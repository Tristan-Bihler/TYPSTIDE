// "Open folder" dialog: type or paste a path, or click through sub-folders.

import { api } from "../api/client";
import type { DirListing } from "../api/types";
import { el } from "../ui/dom";
import { iconNode, icons } from "../ui/icons";

export function pickFolder(start: string | null): Promise<string | null> {
  return new Promise((resolve) => {
    const dialog = el("dialog", { class: "dialog folder-picker" });
    let result: string | null = null;
    let listing: DirListing | null = null;

    const input = el("input", { type: "text", class: "text-input", spellcheck: "false", "aria-label": "Folder path" });
    const go = el("button", { type: "submit", class: "button" }, "Go");
    const up = el("button", { type: "button", class: "button icon-button", title: "Parent folder", "aria-label": "Parent folder" }, iconNode(icons.up));
    const list = el("div", { class: "folder-list", role: "listbox", "aria-label": "Sub-folders" });
    const error = el("p", { class: "dialog-error", role: "alert" });
    const cancel = el("button", { type: "button", class: "button" }, "Cancel");
    const open = el("button", { type: "button", class: "button primary" }, "Open this folder");

    const load = async (path: string | null): Promise<void> => {
      try {
        listing = await api.browse(path);
        error.textContent = "";
      } catch (e: unknown) {
        error.textContent = e instanceof Error ? e.message : String(e);
        return;
      }
      input.value = listing.path;
      up.disabled = listing.parent === null;
      list.replaceChildren();
      for (const name of listing.dirs) {
        const sep = listing.path.includes("\\") ? "\\" : "/";
        const child = listing.path.endsWith(sep) ? listing.path + name : listing.path + sep + name;
        const row = el("button", { type: "button", class: "folder-row", role: "option" }, iconNode(icons.folder), el("span", {}, name));
        row.addEventListener("click", () => void load(child));
        list.append(row);
      }
      if (listing.dirs.length === 0) list.append(el("p", { class: "empty" }, "No sub-folders."));
    };

    const form = el("form", { class: "path-row" }, up, input, go);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void load(input.value.trim());
    });
    up.addEventListener("click", () => {
      if (listing?.parent) void load(listing.parent);
    });
    cancel.addEventListener("click", () => dialog.close());
    open.addEventListener("click", () => {
      if (listing) {
        result = listing.path;
        dialog.close();
      }
    });
    dialog.addEventListener("close", () => {
      dialog.remove();
      resolve(result);
    });

    dialog.append(
      el("h2", {}, "Open folder"),
      el("p", { class: "dialog-hint" }, "Choose the folder that holds your document. Its files appear on the left."),
      form,
      list,
      error,
      el("div", { class: "dialog-buttons" }, cancel, open),
    );
    document.body.append(dialog);
    dialog.showModal();
    void load(start);
  });
}
