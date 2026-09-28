// App state store: one plain object, shallow updates, synchronous subscribers.

import type { AIOverview, CheckerStatus, CompileState, Problem, Tree, UiSettings, WordCount, WorkspaceInfo } from "../api/types";

export type Language = "de-DE" | "en-US";

export interface OpenDoc {
  path: string;
  saved: string; // content on disk
  content: string; // content in the editor
  version: number; // increases with every edit; checks report the version they saw
}

export interface AppState {
  workspace: WorkspaceInfo | null;
  tree: Tree | null;
  docs: OpenDoc[];
  active: string | null;
  problems: Problem[]; // from the last compile
  findings: Record<string, Problem[]>; // spelling/grammar per open file
  checker: CheckerStatus | null;
  completer: CheckerStatus | null; // autocomplete (Tinymist)
  localPending: number; // paragraphs the local AI still has to check
  ui: UiSettings;
  wordCount: WordCount | null;
  saveNotice: "saved" | null; // shown briefly after an autosave
  compile: { state: CompileState; main: string | null; durationMs: number | null };
  connected: boolean;
  cursor: { line: number; column: number };
  language: Language;
  ai: AIOverview | null;
}

export const initialState: AppState = {
  workspace: null,
  tree: null,
  docs: [],
  active: null,
  problems: [],
  findings: {},
  checker: null,
  completer: null,
  localPending: 0,
  ui: { theme: "system", autosave: true, autosave_delay_ms: 2000, preview_follows_cursor: true },
  wordCount: null,
  saveNotice: null,
  compile: { state: "no_workspace", main: null, durationMs: null },
  connected: false,
  cursor: { line: 1, column: 1 },
  language: "de-DE",
  ai: null,
};

type Listener<T> = (state: T, previous: T) => void;

export class Store<T extends object> {
  private readonly listeners = new Set<Listener<T>>();

  constructor(private state: T) {}

  get(): T {
    return this.state;
  }

  set(patch: Partial<T>): void {
    const previous = this.state;
    this.state = { ...previous, ...patch };
    for (const listener of this.listeners) listener(this.state, previous);
  }

  /** Calls `listener` now and on every change. Returns an unsubscribe function. */
  subscribe(listener: Listener<T>): () => void {
    this.listeners.add(listener);
    listener(this.state, this.state);
    return () => this.listeners.delete(listener);
  }
}

export function isDirty(doc: OpenDoc): boolean {
  return doc.content !== doc.saved;
}

/** Compile problems plus spelling/grammar findings of the open files. */
export function allProblems(state: AppState): Problem[] {
  return [...state.problems, ...Object.values(state.findings).flat()];
}
