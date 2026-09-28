// App controller: implements every user action and routes live messages to the UI.

import { ApiError, api } from "./api/client";
import { LiveConnection } from "./api/live";
import type { Problem, ServerMessage } from "./api/types";
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
import { chooseAction, confirmAction, promptText, showMessage } from "./ui/dialog";
import { basename, storage } from "./ui/dom";

// Keep in sync with [timing] doc_changed_debounce_ms in config.toml.
const DOC_CHANGED_DEBOUNCE_MS = 300;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export class App implements Actions {
  readonly store = new Store<AppState>({
    ...initialState,
    language: storage.get("language") === "en-US" ? "en-US" : "de-DE",
  });
  private readonly editor: EditorPane;
  private readonly preview: PreviewPane;
  private readonly live: LiveConnection;
  private readonly timers = new Map<string, number>();

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
    });
    window.addEventListener("beforeunload", (event) => {
      if (this.store.get().docs.some(isDirty)) event.preventDefault();
    });
  }

  /** Unsaved buffers by path (for export and the insert dialogs). */
  overlays(): Record<string, string> {
    return Object.fromEntries(this.store.get().docs.filter(isDirty).map((d) => [d.path, d.content]));
  }

  start(): void {
    this.live.connect();
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
    }
  }

  private resendBuffers(): void {
    for (const doc of this.store.get().docs) {
      if (isDirty(doc)) this.live.send({ type: "doc_changed", path: doc.path, content: doc.content });
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
    this.updateDoc(path, { content });
    window.clearTimeout(this.timers.get(path));
    this.timers.set(
      path,
      window.setTimeout(() => this.live.send({ type: "doc_changed", path, content }), DOC_CHANGED_DEBOUNCE_MS),
    );
  }

  private resetDocs(): void {
    for (const timer of this.timers.values()) window.clearTimeout(timer);
    this.timers.clear();
    this.editor.closeAll();
    this.preview.clear();
    this.store.set({ docs: [], active: null, problems: [] });
  }

  async openDoc(path: string): Promise<void> {
    if (!this.store.get().docs.some((d) => d.path === path)) {
      try {
        const file = await api.readFile(path);
        this.editor.open(path, file.content);
        this.store.set({ docs: [...this.store.get().docs, { path, saved: file.content, content: file.content }] });
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
    this.live.send({ type: "doc_closed", path });
    this.editor.close(path);
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
      if (isDirty(doc)) this.live.send({ type: "doc_changed", path: moved, content: doc.content });
      return { ...doc, path: moved };
    });
    const active = state.active === null ? null : (movedPath(state.active, from, to) ?? state.active);
    this.store.set({ docs, active });
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
    storage.set("language", language);
    this.store.set({ language });
  }
}

