// App state store: one plain object, shallow updates, synchronous subscribers.

import type { AIOverview, CompileState, Problem, Tree, WorkspaceInfo } from "../api/types";

export type Language = "de-DE" | "en-US";

export interface OpenDoc {
  path: string;
  saved: string; // content on disk
  content: string; // content in the editor
}

export interface AppState {
  workspace: WorkspaceInfo | null;
  tree: Tree | null;
  docs: OpenDoc[];
  active: string | null;
  problems: Problem[];
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
