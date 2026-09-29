// Insert toolbar ("Typst functions"), built from snippets.toml via GET /api/snippets.

import { api } from "../api/client";
import type { Snippet } from "../api/types";
import type { EditorPane } from "../editor/editor";
import { applySnippet } from "../editor/snippetOps";
import type { AppState, Store } from "../state/store";
import { showContextMenu } from "../ui/contextMenu";
import { el } from "../ui/dom";
import { openSnippetDialog } from "./dialogs";
import { mountFormatControls } from "./formatControls";

export interface InsertContext {
  store: Store<AppState>;
  editor: EditorPane;
  /** Unsaved buffers, so dialogs see labels that are not saved yet. */
  overlays(): Record<string, string>;
  /** Open a file in a tab (the format controls change the main file). */
  openDoc(path: string): Promise<void>;
  /** A short note in the status bar. */
  notify(text: string): void;
}

function groupLabel(group: string): string {
  return group.charAt(0).toUpperCase() + group.slice(1);
}

function shortcutHint(shortcut: string | null): string {
  if (shortcut === null) return "";
  const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";
  return ` (${shortcut.replace("Mod-", mod).toUpperCase().replace("CTRL+", "Ctrl+")})`;
}

export function runSnippet(snippet: Snippet, ctx: InsertContext): void {
  const state = ctx.editor.activeState();
  if (state === null) return;
  if (snippet.kind === "dialog") {
    void openSnippetDialog(snippet, ctx);
    return;
  }
  ctx.editor.apply(applySnippet(state, snippet));
}

export async function mountInsertToolbar(host: HTMLElement, ctx: InsertContext): Promise<void> {
  const formatHost = el("div", { class: "format-host" });
  host.append(formatHost);
  // Loads the font list (slow the first time), so it does not hold up the snippet buttons.
  mountFormatControls(formatHost, ctx).catch(() => formatHost.remove());
  const snippets = await api.snippets();
  const groups = new Map<string, Snippet[]>();
  for (const snippet of snippets.filter((s) => s.in_toolbar)) {
    groups.set(snippet.group, [...(groups.get(snippet.group) ?? []), snippet]);
  }

  const buttons: HTMLButtonElement[] = [];
  for (const [group, members] of groups) {
    const first = members[0];
    if (first === undefined) continue;
    let button: HTMLButtonElement;
    if (members.length === 1) {
      const title = (first.title || first.label) + shortcutHint(first.shortcut);
      button = el("button", { type: "button", class: "tool", title, "data-snippet": first.id }, el("span", {}, first.label));
      button.addEventListener("click", () => runSnippet(first, ctx));
    } else {
      const label = groupLabel(group);
      button = el(
        "button",
        { type: "button", class: "tool dropdown", "aria-haspopup": "menu", title: label, "data-group": group },
        el("span", {}, label),
        el("span", { class: "caret", "aria-hidden": "true" }),
      );
      button.addEventListener("click", () => {
        const rect = button.getBoundingClientRect();
        showContextMenu(
          rect.left,
          rect.bottom + 2,
          members.map((snippet) => ({ label: snippet.label, action: () => runSnippet(snippet, ctx) })),
        );
      });
    }
    buttons.push(button);
    host.append(button);
  }

  ctx.editor.setShortcuts(
    snippets
      .filter((s): s is Snippet & { shortcut: string } => s.shortcut !== null)
      .map((s) => ({ key: s.shortcut, preventDefault: true, run: () => (runSnippet(s, ctx), true) })),
  );

  ctx.store.subscribe((state) => {
    for (const button of buttons) button.disabled = state.active === null;
  });
}
