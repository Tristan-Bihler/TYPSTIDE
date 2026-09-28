// App controller: implements every user action and routes live messages to the UI.

import { ApiError, api } from "./api/client";
import { LiveConnection } from "./api/live";
import type { Problem, ServerMessage, Suggestion, SuggestionsMessage } from "./api/types";
import { EditorPane } from "./editor/editor";
import { pickFolder } from "./filetree/folderPicker";
import { mountFileTree } from "./filetree/tree";
import { buildShell } from "./layout/layout";
import { mountStatusbar } from "./layout/statusbar";
import { PreviewPane } from "./preview/preview";
import { mountProblems } from "./problems/panel";
import { isTextFile, type Actions, type EntryKind } from "./state/actions";
import { movedPath, nameError, withTypExtension } from "./state/names";
import { initialState, isDirty, Store, type AppState, type Language, type OpenDoc } from "./state/store";
import { mountTopbar } from "./topbar/fileActions";
import { mountInsertToolbar } from "./topbar/insertToolbar";
import { reviewBlocker, reviewSelection } from "./review/review";
import { applyTheme, openSettings } from "./settings/dialog";
import { ignoreKey } from "./suggestions/layer";
import { suggestionProblems } from "./suggestions/problems";
import { showContextMenu } from "./ui/contextMenu";
import { chooseAction, confirmAction, promptText, showMessage } from "./ui/dialog";
import { basename } from "./ui/dom";

// Keep in sync with [timing] in config.toml.
const DOC_CHANGED_DEBOUNCE_MS = 300;
const TYPING_PAUSED_MS = 1500;
const SAVE_TABS_MS = 1000;
const SAVED_NOTICE_MS = 2000;

interface Checked {
  content: string;
  suggestions: Suggestion[];
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export class App implements Actions {
  readonly store = new Store<AppState>(initialState);
  private readonly editor: EditorPane;
  private readonly preview: PreviewPane;
  private readonly live: LiveConnection;
  private readonly timers = new Map<string, number>();
  /** Findings hidden with "Ignore", per file (for this session). */
  private readonly ignored = new Map<string, Set<string>>();
  /** The last findings per file and source, with the text they were found in. */
  private readonly checked = new Map<string, Map<Suggestion["source"], Checked>>();
  /** Per file: sends typing_paused after a pause (local AI check). */
  private readonly pauseTimers = new Map<string, number>();
  /** Per file: autosave after the configured delay. */
  private readonly autosaveTimers = new Map<string, number>();
  /** Files whose autosave failed: paused until they are saved by hand. */
  private readonly autosaveBlocked = new Set<string>();
  /** Open tabs are remembered only after the saved ones were restored. */
  private tabsRestored = false;
  private saveTabsTimer = 0;
  private noticeTimer = 0;

  constructor(root: HTMLElement) {
    const shell = buildShell(root);
    const insertHost = mountTopbar(shell.topbar, this.store, this);
    mountFileTree(shell.files, this.store, this);
    mountProblems(shell.problems, this.store, this);
    mountStatusbar(shell.statusbar, this.store, this);
    this.preview = new PreviewPane(shell.preview, this.store);
    this.editor = new EditorPane(shell.editor, this.store, {
      onChange: (path, content) => this.contentChanged(path, content),
      onCursor: (line, column) => this.store.set({ cursor: { line, column } }),
      onSave: () => void this.saveAll(),
      onActivate: (path) => this.activate(path),
      onClose: (path) => void this.closeDoc(path),
      onReview: () => void reviewSelection({ store: this.store, editor: this.editor }),
      onContextMenu: (event) => this.editorMenu(event),
      onIgnore: (path, suggestion) => this.ignore(path, suggestion),
      onAddWord: (suggestion) => void this.addWord(suggestion),
    });
    this.editor.show(null);
    mountInsertToolbar(insertHost, {
      store: this.store,
      editor: this.editor,
      overlays: () => this.overlays(),
    }).catch((error: unknown) => {
      void showMessage("Could not load the insert toolbar", errorText(error));
    });

    this.live = new LiveConnection({
      onMessage: (message) => this.receive(message),
      onOpen: () => this.resendBuffers(),
      onConnectionChange: (connected) => this.store.set({ connected }),
    });

    window.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void this.saveAll();
      }
      if ((event.ctrlKey || event.metaKey) && event.key === ",") {
        event.preventDefault();
        this.openSettings();
      }
    });
    // Remember the open tabs (and cursors) of this folder for the next start.
    this.store.subscribe((state, previous) => {
      if (state.docs.length !== previous.docs.length || state.active !== previous.active || state.cursor !== previous.cursor) {
        this.scheduleSaveTabs();
      }
    });
    window.addEventListener("beforeunload", (event) => {
      if (this.store.get().docs.some(isDirty)) event.preventDefault();
    });
  }

  /** Right-click with a selection: offer the Claude review (disabled with a reason when off). */
  private editorMenu(event: MouseEvent): boolean {
    const state = this.editor.activeState();
    if (state === null || state.selection.main.empty || event.shiftKey) return false;
    const blocker = reviewBlocker(this.store.get());
    const { from, to } = state.selection.main;
    const text = state.sliceDoc(from, to);
    const review = {
      label: "Review with Claude…   Ctrl+Shift+K",
      action: () => void reviewSelection({ store: this.store, editor: this.editor }),
      ...(blocker === null ? {} : { disabledReason: blocker }),
    };
    showContextMenu(event.clientX, event.clientY, [
      review,
      "separator",
      { label: "Copy", action: () => void navigator.clipboard.writeText(text) },
      {
        label: "Cut",
        action: () => {
          void navigator.clipboard.writeText(text);
          this.editor.apply({ changes: { from, to, insert: "" }, userEvent: "delete.cut" });
        },
      },
    ]);
    return true;
  }

  /** Unsaved buffers by path (for export and the insert dialogs). */
  overlays(): Record<string, string> {
    return Object.fromEntries(this.store.get().docs.filter(isDirty).map((d) => [d.path, d.content]));
  }

  openSettings(): void {
    openSettings({ store: this.store, actions: this });
  }

  start(): void {
    api
      .uiSettings()
      .then((ui) => {
        this.store.set({ ui });
        applyTheme(ui.theme);
      })
      .catch(() => {
        // Defaults stay (theme follows the system).
      });
    this.live.connect();
    api
      .grammar()
      .then((grammar) => this.store.set({ language: grammar.settings.language, checker: grammar.status }))
      .catch(() => {
        // Backend not reachable yet; the checker status arrives with the live connection.
      });
  }

  // --- live messages ---------------------------------------------------------------

  private receive(message: ServerMessage): void {
    switch (message.type) {
      case "workspace_changed": {
        const previous = this.store.get().workspace;
        const otherFolder = previous?.root !== message.workspace?.root;
        if (message.reopened && otherFolder) this.resetDocs();
        this.store.set({ workspace: message.workspace });
        void this.reloadTree();
        if (message.reopened && otherFolder && message.workspace !== null) void this.restoreTabs();
        break;
      }
      case "preview_pages":
        this.preview.apply(message.pages);
        break;
      case "problems":
        this.store.set({ problems: message.problems });
        this.editor.setProblems(message.problems);
        break;
      case "compile_status":
        this.store.set({
          compile: { state: message.state, main: message.main, durationMs: message.duration_ms },
        });
        break;
      case "suggestions":
        this.showFindings(message);
        break;
      case "checker_status":
        this.store.set({ checker: message.status });
        break;
      case "word_count":
        this.store.set({ wordCount: message });
        break;
      case "local_check_status":
        this.store.set({ localPending: message.pending });
        break;
    }
  }

  // --- spelling and grammar ----------------------------------------------------------

  private showFindings(message: SuggestionsMessage): void {
    const doc = this.store.get().docs.find((d) => d.path === message.path);
    // Findings for text that has changed since are dropped; the next check replaces them.
    if (doc === undefined || message.version !== doc.version) return;
    const bySource = this.checked.get(doc.path) ?? new Map<Suggestion["source"], Checked>();
    bySource.set(message.source, { content: doc.content, suggestions: message.suggestions });
    this.checked.set(doc.path, bySource);
    const ignored = this.ignored.get(doc.path);
    this.editor.setSuggestions(
      doc.path,
      message.source,
      message.suggestions.filter((s) => !ignored?.has(ignoreKey(s))),
    );
    this.updateProblems(doc.path);
  }

  /** Problems panel entries of `path` from every source, minus ignored findings. */
  private updateProblems(path: string): void {
    const ignored = this.ignored.get(path);
    const problems = [...(this.checked.get(path)?.values() ?? [])].flatMap(({ content, suggestions }) =>
      suggestionProblems(
        path,
        content,
        suggestions.filter((s) => !ignored?.has(ignoreKey(s))),
      ),
    );
    this.store.set({ findings: { ...this.store.get().findings, [path]: problems } });
  }

  private ignore(path: string, suggestion: Suggestion): void {
    const keys = this.ignored.get(path) ?? new Set<string>();
    keys.add(ignoreKey(suggestion));
    this.ignored.set(path, keys);
    this.updateProblems(path);
  }

  private async addWord(suggestion: Suggestion): Promise<void> {
    try {
      // The backend checks all open files again, so the word disappears everywhere.
      await api.addToDictionary(this.store.get().language, suggestion.original);
    } catch (error) {
      await showMessage("Could not add the word", errorText(error));
    }
  }

  async installGrammar(): Promise<void> {
    const ok = await confirmAction(
      "Install the spelling check?",
      "Spelling and grammar checks use LTeX+. It is downloaded once (about 320 MB) and then works offline. Nothing is sent anywhere while you write.",
      "Download and install",
    );
    if (!ok) return;
    try {
      this.store.set({ checker: (await api.installGrammar()).status });
    } catch (error) {
      await showMessage("Could not install the spelling check", errorText(error));
    }
  }

  private resendBuffers(): void {
    for (const doc of this.store.get().docs) {
      const message = { path: doc.path, content: doc.content, version: doc.version };
      this.live.send(isDirty(doc) ? { type: "doc_changed", ...message } : { type: "doc_opened", ...message });
    }
    this.live.send({ type: "refresh" });
  }

  private async reloadTree(): Promise<void> {
    if (this.store.get().workspace === null) {
      this.store.set({ tree: null });
      return;
    }
    try {
      this.store.set({ tree: await api.tree() });
    } catch (error) {
      if (!(error instanceof ApiError && error.code === "no_workspace")) throw error;
    }
  }

  // --- documents -------------------------------------------------------------------

  private updateDoc(path: string, patch: Partial<OpenDoc>): void {
    this.store.set({
      docs: this.store.get().docs.map((d) => (d.path === path ? { ...d, ...patch } : d)),
    });
  }

  private contentChanged(path: string, content: string): void {
    const version = (this.store.get().docs.find((d) => d.path === path)?.version ?? 0) + 1;
    this.updateDoc(path, { content, version });
    window.clearTimeout(this.timers.get(path));
    this.timers.set(
      path,
      window.setTimeout(() => this.live.send({ type: "doc_changed", path, content, version }), DOC_CHANGED_DEBOUNCE_MS),
    );
    this.scheduleAutosave(path);
    // After a longer pause the local AI may check the edited paragraphs (backend decides).
    window.clearTimeout(this.pauseTimers.get(path));
    this.pauseTimers.set(
      path,
      window.setTimeout(() => {
        const state = this.editor.activeState();
        const cursor = this.store.get().active === path && state !== null ? state.selection.main.head : 0;
        this.live.send({ type: "typing_paused", path, version, cursor });
      }, TYPING_PAUSED_MS),
    );
  }

  private resetDocs(): void {
    const timers = [...this.timers.values(), ...this.pauseTimers.values(), ...this.autosaveTimers.values()];
    for (const timer of timers) window.clearTimeout(timer);
    this.timers.clear();
    this.pauseTimers.clear();
    this.autosaveTimers.clear();
    this.autosaveBlocked.clear();
    this.tabsRestored = false;
    this.editor.closeAll();
    this.preview.clear();
    this.ignored.clear();
    this.checked.clear();
    this.store.set({ docs: [], active: null, problems: [], findings: {} });
  }

  async openDoc(path: string): Promise<void> {
    if (!this.store.get().docs.some((d) => d.path === path)) {
      try {
        const file = await api.readFile(path);
        this.editor.open(path, file.content);
        this.store.set({ docs: [...this.store.get().docs, { path, saved: file.content, content: file.content, version: 1 }] });
        this.live.send({ type: "doc_opened", path, content: file.content, version: 1 });
      } catch (error) {
        await showMessage("Could not open the file", errorText(error));
        return;
      }
    }
    this.activate(path);
  }

  activate(path: string): void {
    this.store.set({ active: path });
    this.editor.show(path);
    this.editor.setProblems(this.store.get().problems);
    this.editor.focus();
  }

  private forget(path: string): void {
    window.clearTimeout(this.timers.get(path));
    this.timers.delete(path);
    window.clearTimeout(this.pauseTimers.get(path));
    this.pauseTimers.delete(path);
    window.clearTimeout(this.autosaveTimers.get(path));
    this.autosaveTimers.delete(path);
    this.autosaveBlocked.delete(path);
    this.live.send({ type: "doc_closed", path });
    this.editor.close(path);
    this.ignored.delete(path);
    this.checked.delete(path);
    const { [path]: _closed, ...findings } = this.store.get().findings;
    this.store.set({ findings });
    const { docs, active } = this.store.get();
    const index = docs.findIndex((d) => d.path === path);
    const remaining = docs.filter((d) => d.path !== path);
    this.store.set({ docs: remaining });
    if (active === path) {
      const next = remaining[Math.min(index, remaining.length - 1)];
      if (next) this.activate(next.path);
      else {
        this.store.set({ active: null });
        this.editor.show(null);
      }
    }
  }

  async closeDoc(path: string): Promise<void> {
    const doc = this.store.get().docs.find((d) => d.path === path);
    if (!doc) return;
    if (isDirty(doc)) {
      const choice = await chooseAction("Save changes?", `${basename(path)} has unsaved changes.`, [
        { label: "Don't save", value: "discard" },
        { label: "Save", value: "save", kind: "primary" },
      ]);
      if (choice === null) return;
      if (choice === "save" && !(await this.save(doc))) return;
    }
    this.forget(path);
  }

  private async save(doc: OpenDoc): Promise<boolean> {
    try {
      await api.saveFile(doc.path, doc.content);
      this.updateDoc(doc.path, { saved: doc.content });
      this.autosaveBlocked.delete(doc.path);
      return true;
    } catch (error) {
      await showMessage(`Could not save ${basename(doc.path)}`, errorText(error));
      return false;
    }
  }

  async saveAll(): Promise<void> {
    for (const doc of this.store.get().docs.filter(isDirty)) {
      if (!(await this.save(doc))) return;
    }
  }

  // --- autosave --------------------------------------------------------------------

  private scheduleAutosave(path: string): void {
    window.clearTimeout(this.autosaveTimers.get(path));
    const { ui } = this.store.get();
    if (!ui.autosave || this.autosaveBlocked.has(path)) return;
    this.autosaveTimers.set(path, window.setTimeout(() => void this.autosave(path), ui.autosave_delay_ms));
  }

  private async autosave(path: string): Promise<void> {
    this.autosaveTimers.delete(path);
    const doc = this.store.get().docs.find((d) => d.path === path);
    if (doc === undefined || !isDirty(doc) || !this.store.get().ui.autosave) return;
    try {
      await api.saveFile(doc.path, doc.content);
    } catch (error) {
      // Tell once, then stop trying for this file until it is saved by hand (Ctrl+S).
      this.autosaveBlocked.add(path);
      await showMessage(
        `Could not save ${basename(path)} automatically`,
        `${errorText(error)} Automatic saving is paused for this file; press Ctrl+S to try again.`,
      );
      return;
    }
    this.updateDoc(path, { saved: doc.content });
    this.store.set({ saveNotice: "saved" });
    window.clearTimeout(this.noticeTimer);
    this.noticeTimer = window.setTimeout(() => this.store.set({ saveNotice: null }), SAVED_NOTICE_MS);
  }

  // --- remembered tabs -------------------------------------------------------------

  private async restoreTabs(): Promise<void> {
    try {
      const saved = await api.openTabs();
      for (const tab of saved.tabs) {
        await this.openDoc(tab.path);
        this.editor.setCursor(tab.path, tab.cursor);
      }
      if (saved.active !== null) this.activate(saved.active);
    } catch {
      // Nothing to restore (or the folder was closed meanwhile).
    } finally {
      this.tabsRestored = true;
    }
  }

  private scheduleSaveTabs(): void {
    if (!this.tabsRestored || this.store.get().workspace === null) return;
    window.clearTimeout(this.saveTabsTimer);
    this.saveTabsTimer = window.setTimeout(() => {
      const { docs, active } = this.store.get();
      const tabs = docs.map((d) => ({ path: d.path, cursor: this.editor.cursor(d.path) ?? 0 }));
      api.saveOpenTabs({ tabs, active }).catch(() => {
        // Not important enough to interrupt the user.
      });
    }, SAVE_TABS_MS);
  }

  // --- workspace -------------------------------------------------------------------

  async openFolderDialog(): Promise<void> {
    const state = this.store.get();
    if (state.docs.some(isDirty)) {
      const choice = await chooseAction("Save changes first?", "Some open files have unsaved changes.", [
        { label: "Don't save", value: "discard" },
        { label: "Save", value: "save", kind: "primary" },
      ]);
      if (choice === null) return;
      if (choice === "save") await this.saveAll();
    }
    const folder = await pickFolder(state.workspace?.root ?? null);
    if (folder === null) return;
    try {
      await api.openWorkspace(folder);
    } catch (error) {
      await showMessage("Could not open the folder", errorText(error));
    }
  }

  private async createWithOverwrite(create: (overwrite: boolean) => Promise<{ path: string }>, name: string): Promise<string | null> {
    try {
      return (await create(false)).path;
    } catch (error) {
      if (!(error instanceof ApiError && error.code === "exists")) throw error;
    }
    const replace = await confirmAction("Replace file?", `${name} already exists. Replace it with an empty file?`, "Replace", "danger");
    return replace ? (await create(true)).path : null;
  }

  async newFile(parent: string): Promise<void> {
    const raw = await promptText({
      title: "New file",
      label: "File name",
      value: "untitled.typ",
      selectEnd: "untitled".length,
      confirmLabel: "Create",
      validate: (value) => nameError(withTypExtension(value), "file"),
    });
    if (raw === null) return;
    const name = withTypExtension(raw);
    try {
      const path = await this.createWithOverwrite((overwrite) => api.createFile(parent, name, overwrite), name);
      if (path === null) return;
      if (this.store.get().workspace?.main == null) await api.setMain(path);
      await this.reloadTree();
      await this.openDoc(path);
    } catch (error) {
      await showMessage("Could not create the file", errorText(error));
    }
  }

  async newFolder(parent: string): Promise<void> {
    const name = await promptText({
      title: "New folder",
      label: "Folder name",
      value: "",
      confirmLabel: "Create",
      validate: (value) => nameError(value, "folder"),
    });
    if (name === null) return;
    try {
      await api.createFolder(parent, name);
      await this.reloadTree();
    } catch (error) {
      await showMessage("Could not create the folder", errorText(error));
    }
  }

  async rename(path: string, kind: EntryKind): Promise<void> {
    const current = basename(path);
    const dot = current.lastIndexOf(".");
    const newName = await promptText({
      title: kind === "file" ? "Rename file" : "Rename folder",
      label: "New name",
      value: current,
      selectEnd: kind === "file" && dot > 0 ? dot : current.length,
      confirmLabel: "Rename",
      validate: (value) => nameError(value, kind === "file" && current.endsWith(".typ") ? "file" : "folder"),
    });
    if (newName === null || newName === current) return;
    try {
      const target = await this.createWithOverwrite((overwrite) => api.rename(path, newName, overwrite), newName);
      if (target === null) return;
      this.movedDocs(path, target);
      await this.reloadTree();
    } catch (error) {
      await showMessage("Could not rename", errorText(error));
    }
  }

  private movedDocs(from: string, to: string): void {
    const state = this.store.get();
    const docs = state.docs.map((doc) => {
      const moved = movedPath(doc.path, from, to);
      if (moved === null) return doc;
      this.editor.rename(doc.path, moved);
      this.live.send({ type: "doc_closed", path: doc.path });
      const message = { path: moved, content: doc.content, version: doc.version };
      this.live.send(isDirty(doc) ? { type: "doc_changed", ...message } : { type: "doc_opened", ...message });
      return { ...doc, path: moved };
    });
    const active = state.active === null ? null : (movedPath(state.active, from, to) ?? state.active);
    const findings = Object.fromEntries(Object.entries(state.findings).filter(([path]) => movedPath(path, from, to) === null));
    this.store.set({ docs, active, findings });
  }

  async remove(path: string, kind: EntryKind): Promise<void> {
    const affected = this.store.get().docs.filter((d) => movedPath(d.path, path, path) !== null);
    const unsaved = affected.some(isDirty) ? " Unsaved changes in open files are lost too." : "";
    const what = kind === "folder" ? `the folder ${basename(path)} and everything in it` : basename(path);
    const ok = await confirmAction("Delete?", `Delete ${what}? This cannot be undone.${unsaved}`, "Delete", "danger");
    if (!ok) return;
    try {
      await api.delete(path);
      for (const doc of affected) this.forget(doc.path);
      await this.reloadTree();
    } catch (error) {
      await showMessage("Could not delete", errorText(error));
    }
  }

  async setMain(path: string): Promise<void> {
    try {
      this.store.set({ workspace: await api.setMain(path) });
    } catch (error) {
      await showMessage("Could not set the main file", errorText(error));
    }
  }

  async exportPdf(): Promise<void> {
    const overlays = this.overlays();
    try {
      const { blob, filename } = await api.exportPdf(overlays);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (error) {
      if (error instanceof ApiError && error.code === "compile_failed") {
        this.store.set({ problems: error.problems });
        await showMessage("Export failed", "The document has errors. Fix the ones listed under Problems, then export again.");
      } else {
        await showMessage("Export failed", errorText(error));
      }
    }
  }

  async jumpTo(problem: Problem): Promise<void> {
    if (problem.file === "" || !isTextFile(problem.file)) return;
    await this.openDoc(problem.file);
    if (problem.line > 0) this.editor.jumpTo(problem.line, problem.column);
  }

  setLanguage(language: Language): void {
    const previous = this.store.get().language;
    this.store.set({ language });
    // The backend saves it and checks every open file again.
    api.setGrammarLanguage(language).catch(async (error: unknown) => {
      this.store.set({ language: previous });
      await showMessage("Could not change the language", errorText(error));
    });
  }
}

