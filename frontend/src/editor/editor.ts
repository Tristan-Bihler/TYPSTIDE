// Editor pane: tab bar plus one CodeMirror view whose state is swapped per open file,
// so every file keeps its own undo history and selection.

import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { bracketMatching, indentOnInput, syntaxHighlighting } from "@codemirror/language";
import { lintGutter, setDiagnostics, type Diagnostic } from "@codemirror/lint";
import { Compartment, EditorSelection, EditorState, type TransactionSpec } from "@codemirror/state";
import {
  drawSelection,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  type KeyBinding,
} from "@codemirror/view";

import type { Problem, Suggestion } from "../api/types";
import { setSuggestions, suggestionLayer } from "../suggestions/layer";
import { isDirty, type AppState, type Store } from "../state/store";
import { basename, el } from "../ui/dom";
import { iconNode, icons } from "../ui/icons";
import { typstHighlight, typstLanguage } from "./typst";

export interface EditorCallbacks {
  onChange(path: string, content: string): void;
  onCursor(line: number, column: number): void;
  onSave(): void;
  onActivate(path: string): void;
  onClose(path: string): void;
  onReview(): void;
  /** Right-click inside the text; return true when a custom menu was shown. */
  onContextMenu(event: MouseEvent): boolean;
  /** "Ignore" on a finding in the active file. */
  onIgnore(path: string, suggestion: Suggestion): void;
  /** "Add to dictionary" on a spelling finding. */
  onAddWord(suggestion: Suggestion): void;
}

/** Convert 1-based line/column to a document offset, clamped to the document. */
export function toOffset(state: EditorState, line: number, column: number): number {
  const lineInfo = state.doc.line(Math.min(Math.max(line, 1), state.doc.lines));
  return Math.min(lineInfo.from + Math.max(column - 1, 0), lineInfo.to);
}

export class EditorPane {
  private readonly view: EditorView;
  private readonly states = new Map<string, EditorState>();
  private readonly tabs: HTMLElement;
  private readonly empty: HTMLElement;
  private activePath: string | null = null;
  /** Snippet shortcuts (Mod-b, …); loaded after the editor exists, so reconfigurable. */
  private readonly shortcuts = new Compartment();
  private shortcutBindings: KeyBinding[] = [];

  constructor(
    host: HTMLElement,
    store: Store<AppState>,
    private readonly callbacks: EditorCallbacks,
  ) {
    this.tabs = el("div", { class: "tabs", role: "tablist", "aria-label": "Open files" });
    const surface = el("div", { class: "editor-surface" });
    this.empty = el(
      "div",
      { class: "editor-empty" },
      el("p", {}, "Open a file from the list on the left, or create one with New file."),
    );
    host.append(this.tabs, surface, this.empty);
    this.view = new EditorView({ parent: surface, state: this.createState("") });
    store.subscribe((state, previous) => {
      if (state === previous || state.docs !== previous.docs || state.active !== previous.active || state.workspace !== previous.workspace) {
        this.renderTabs(state);
      }
    });
  }

  private createState(content: string): EditorState {
    return EditorState.create({
      doc: content,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        drawSelection(),
        history(),
        indentOnInput(),
        bracketMatching(),
        typstLanguage,
        syntaxHighlighting(typstHighlight),
        lintGutter(),
        suggestionLayer({
          ignore: (suggestion) => {
            if (this.activePath !== null) this.callbacks.onIgnore(this.activePath, suggestion);
          },
          addToDictionary: (suggestion) => this.callbacks.onAddWord(suggestion),
        }),
        EditorView.lineWrapping,
        EditorState.tabSize.of(2),
        this.shortcuts.of(keymap.of(this.shortcutBindings)),
        keymap.of([
          { key: "Mod-s", preventDefault: true, run: () => (this.callbacks.onSave(), true) },
          { key: "Mod-Shift-k", preventDefault: true, run: () => (this.callbacks.onReview(), true) },
          ...defaultKeymap,
          ...historyKeymap,
          indentWithTab,
        ]),
        EditorView.updateListener.of((update) => {
          if (this.activePath === null) return;
          if (update.docChanged) this.callbacks.onChange(this.activePath, update.state.doc.toString());
          if (update.docChanged || update.selectionSet) {
            const head = update.state.selection.main.head;
            const line = update.state.doc.lineAt(head);
            this.callbacks.onCursor(line.number, head - line.from + 1);
          }
        }),
        EditorView.contentAttributes.of({ "aria-label": "Document source", spellcheck: "false" }),
        EditorView.domEventHandlers({
          contextmenu: (event) => {
            if (this.callbacks.onContextMenu(event)) event.preventDefault();
          },
        }),
      ],
    });
  }

  /** Replace the snippet shortcuts in every open file. */
  setShortcuts(bindings: KeyBinding[]): void {
    this.shortcutBindings = bindings;
    const effects = this.shortcuts.reconfigure(keymap.of(bindings));
    for (const [path, state] of this.states) {
      if (path !== this.activePath) this.states.set(path, state.update({ effects }).state);
    }
    this.view.dispatch({ effects });
  }

  /** The active file's state, or null when no file is open. */
  activeState(): EditorState | null {
    return this.activePath === null ? null : this.view.state;
  }

  /** Apply a change to the active file as one undo step and focus the editor. */
  apply(spec: TransactionSpec): boolean {
    if (this.activePath === null) return false;
    this.view.dispatch(spec);
    this.view.focus();
    return true;
  }

  open(path: string, content: string): void {
    if (!this.states.has(path)) this.states.set(path, this.createState(content));
  }

  show(path: string | null): void {
    if (this.activePath !== null) this.states.set(this.activePath, this.view.state);
    this.activePath = path;
    const state = path === null ? undefined : this.states.get(path);
    this.empty.hidden = state !== undefined;
    this.view.dom.hidden = state === undefined;
    if (state === undefined) return;
    this.view.setState(state);
    const head = state.selection.main.head;
    const line = state.doc.lineAt(head);
    this.callbacks.onCursor(line.number, head - line.from + 1);
  }

  close(path: string): void {
    this.states.delete(path);
    if (this.activePath === path) this.activePath = null;
  }

  closeAll(): void {
    this.states.clear();
    this.activePath = null;
    this.show(null);
  }

  rename(oldPath: string, newPath: string): void {
    const state = this.activePath === oldPath ? this.view.state : this.states.get(oldPath);
    if (state === undefined) return;
    this.states.delete(oldPath);
    this.states.set(newPath, state);
    if (this.activePath === oldPath) this.activePath = newPath;
  }

  setProblems(problems: Problem[]): void {
    if (this.activePath === null) return;
    const state = this.view.state;
    const diagnostics: Diagnostic[] = problems
      .filter((p) => p.file === this.activePath && p.line > 0)
      .map((p) => {
        const from = toOffset(state, p.line, p.column);
        const lineEnd = state.doc.lineAt(from).to;
        const word = /^[\w#.-]+/.exec(state.sliceDoc(from, lineEnd))?.[0].length ?? 1;
        return {
          from,
          to: Math.min(from + word, lineEnd),
          severity: p.severity === "error" ? "error" : "warning",
          message: p.message,
          source: p.source,
        };
      });
    this.view.dispatch(setDiagnostics(state, diagnostics));
  }

  /** Replace the findings of one source in `path` (offsets must match its current text). */
  setSuggestions(path: string, source: Suggestion["source"], suggestions: Suggestion[]): void {
    const effects = setSuggestions.of({ source, suggestions });
    if (path === this.activePath) {
      this.view.dispatch({ effects });
      return;
    }
    const state = this.states.get(path);
    if (state !== undefined) this.states.set(path, state.update({ effects }).state);
  }

  /** The text of an open file (the editor's current state). */
  content(path: string): string | null {
    if (path === this.activePath) return this.view.state.doc.toString();
    return this.states.get(path)?.doc.toString() ?? null;
  }

  jumpTo(line: number, column: number): void {
    const offset = toOffset(this.view.state, line, column);
    this.view.dispatch({
      selection: EditorSelection.cursor(offset),
      effects: EditorView.scrollIntoView(offset, { y: "center" }),
    });
    this.view.focus();
  }

  focus(): void {
    this.view.focus();
  }

  private renderTabs(state: AppState): void {
    this.tabs.replaceChildren();
    for (const doc of state.docs) {
      const active = doc.path === state.active;
      const isMain = state.workspace?.main === doc.path;
      const label = el("span", { class: "tab-label" }, basename(doc.path));
      const tab = el(
        "div",
        {
          class: `tab${active ? " active" : ""}${isDirty(doc) ? " dirty" : ""}`,
          role: "tab",
          tabindex: active ? "0" : "-1",
          "aria-selected": String(active),
          title: isMain ? `${doc.path} (main file)` : doc.path,
          "data-path": doc.path,
        },
        label,
      );
      if (isMain) tab.append(el("span", { class: "badge" }, "main"));
      const close = el(
        "button",
        { type: "button", class: "tab-close", title: "Close", "aria-label": `Close ${basename(doc.path)}` },
        el("span", { class: "dirty-dot" }),
        iconNode(icons.close),
      );
      close.addEventListener("click", (event) => {
        event.stopPropagation();
        this.callbacks.onClose(doc.path);
      });
      tab.append(close);
      tab.addEventListener("click", () => this.callbacks.onActivate(doc.path));
      tab.addEventListener("auxclick", (event) => {
        if (event.button === 1) this.callbacks.onClose(doc.path);
      });
      tab.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") this.callbacks.onActivate(doc.path);
      });
      this.tabs.append(tab);
    }
  }
}
