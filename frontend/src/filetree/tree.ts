// File tree of the open folder, with a context menu for file operations.

import type { TreeNode } from "../api/types";
import { isTextFile, type Actions } from "../state/actions";
import { isDirty, type AppState, type Store } from "../state/store";
import { showContextMenu, type MenuItem } from "../ui/contextMenu";
import { dirname, el, storage } from "../ui/dom";
import { iconNode, icons } from "../ui/icons";

const EXPANDED_KEY = "filetree.expanded";

let selectedFolder = "";

/** Folder where "New file" / "New folder" in the top bar create entries. */
export function targetFolder(): string {
  return selectedFolder;
}

function loadExpanded(): Set<string> {
  try {
    const parsed: unknown = JSON.parse(storage.get(EXPANDED_KEY) ?? "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((p): p is string => typeof p === "string") : []);
  } catch {
    return new Set();
  }
}

export function mountFileTree(host: HTMLElement, store: Store<AppState>, actions: Actions): void {
  const expanded = loadExpanded();
  const title = el("h2", { class: "panel-title" }, "Files");
  const body = el("div", { class: "panel-body tree", role: "tree", "aria-label": "Files" });
  host.append(title, body);

  const saveExpanded = (): void => storage.set(EXPANDED_KEY, JSON.stringify([...expanded]));

  const folderMenu = (path: string): (MenuItem | "separator")[] => {
    const items: (MenuItem | "separator")[] = [
      { label: "New file…", action: () => void actions.newFile(path) },
      { label: "New folder…", action: () => void actions.newFolder(path) },
    ];
    if (path !== "") {
      items.push(
        "separator",
        { label: "Rename…", action: () => void actions.rename(path, "folder") },
        { label: "Delete…", action: () => void actions.remove(path, "folder"), danger: true },
      );
    }
    return items;
  };

  const fileMenu = (path: string): (MenuItem | "separator")[] => {
    const items: (MenuItem | "separator")[] = [];
    if (isTextFile(path)) items.push({ label: "Open", action: () => void actions.openDoc(path) });
    if (path.toLowerCase().endsWith(".typ") && store.get().workspace?.main !== path) {
      items.push({ label: "Set as main file", action: () => void actions.setMain(path) });
    }
    if (items.length > 0) items.push("separator");
    items.push(
      { label: "Rename…", action: () => void actions.rename(path, "file") },
      { label: "Delete…", action: () => void actions.remove(path, "file"), danger: true },
    );
    return items;
  };

  const openMenu = (event: MouseEvent | KeyboardEvent, node: TreeNode, target: HTMLElement): void => {
    event.preventDefault();
    event.stopPropagation();
    selectedFolder = node.kind === "folder" ? node.path : dirname(node.path);
    const rect = target.getBoundingClientRect();
    const x = event instanceof MouseEvent ? event.clientX : rect.left + 24;
    const y = event instanceof MouseEvent ? event.clientY : rect.bottom;
    showContextMenu(x, y, node.kind === "folder" ? folderMenu(node.path) : fileMenu(node.path));
  };

  const renderNode = (node: TreeNode, depth: number, state: AppState): HTMLElement => {
    const isFolder = node.kind === "folder";
    const isOpen = expanded.has(node.path);
    const doc = state.docs.find((d) => d.path === node.path);
    const classes = ["tree-row", isFolder ? "folder" : "file"];
    if (!isFolder && !isTextFile(node.path)) classes.push("inert");
    if (state.active === node.path) classes.push("active");

    const row = el("button", {
      type: "button",
      class: classes.join(" "),
      role: "treeitem",
      style: `--depth: ${depth}`,
      title: node.path,
      "data-path": node.path,
    });
    if (isFolder) {
      row.setAttribute("aria-expanded", String(isOpen));
      row.append(el("span", { class: `twisty ${isOpen ? "open" : ""}` }, iconNode(icons.chevron)));
    } else {
      row.append(el("span", { class: "twisty" }));
    }
    row.append(iconNode(isFolder ? icons.folder : icons.file), el("span", { class: "tree-name" }, node.name));
    if (state.workspace?.main === node.path) row.append(el("span", { class: "badge", title: "Main file: this is what the preview and PDF show" }, "main"));
    if (doc && isDirty(doc)) row.append(el("span", { class: "dirty-dot", title: "Unsaved changes" }));

    row.addEventListener("click", () => {
      if (isFolder) {
        selectedFolder = node.path;
        if (isOpen) expanded.delete(node.path);
        else expanded.add(node.path);
        saveExpanded();
        render(store.get());
      } else {
        selectedFolder = dirname(node.path);
        if (isTextFile(node.path)) void actions.openDoc(node.path);
      }
    });
    row.addEventListener("contextmenu", (event) => openMenu(event, node, row));
    row.addEventListener("keydown", (event) => {
      if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) openMenu(event, node, row);
    });

    const item = el("div", { class: "tree-item" }, row);
    if (isFolder && isOpen) {
      const group = el("div", { role: "group" });
      for (const child of node.children) group.append(renderNode(child, depth + 1, state));
      item.append(group);
    }
    return item;
  };

  const render = (state: AppState): void => {
    const scroll = body.scrollTop;
    body.replaceChildren();
    if (!state.workspace || !state.tree) {
      const open = el("button", { type: "button", class: "button primary" }, "Open folder");
      open.addEventListener("click", () => void actions.openFolderDialog());
      body.append(el("div", { class: "empty" }, el("p", {}, "Open a folder to see its files."), open));
      title.textContent = "Files";
      return;
    }
    title.textContent = state.workspace.name;
    title.title = state.workspace.root;
    for (const child of state.tree.root.children) body.append(renderNode(child, 0, state));
    if (state.tree.root.children.length === 0) {
      body.append(el("p", { class: "empty" }, "This folder is empty. Right-click here to create a file."));
    }
    if (state.tree.truncated) body.append(el("p", { class: "empty" }, "Too many files: the list is shortened."));
    body.scrollTop = scroll;
  };

  body.addEventListener("contextmenu", (event) => {
    if (!store.get().workspace) return;
    event.preventDefault();
    selectedFolder = "";
    showContextMenu(event.clientX, event.clientY, folderMenu(""));
  });

  store.subscribe((state, previous) => {
    if (
      state === previous ||
      state.tree !== previous.tree ||
      state.workspace !== previous.workspace ||
      state.active !== previous.active ||
      state.docs !== previous.docs
    ) {
      // Reveal the active file.
      if (state.active && state.active !== previous.active) {
        let folder = dirname(state.active);
        while (folder !== "") {
          expanded.add(folder);
          folder = dirname(folder);
        }
      }
      render(state);
    }
  });
}
