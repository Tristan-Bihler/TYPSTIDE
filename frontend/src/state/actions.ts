// Everything the UI can ask the app to do. Implemented by app.ts.

import type { Problem } from "../api/types";
import type { Language } from "./store";

export type EntryKind = "file" | "folder";

export interface Actions {
  openFolderDialog(): Promise<void>;
  openDoc(path: string): Promise<void>;
  activate(path: string): void;
  closeDoc(path: string): Promise<void>;
  saveAll(): Promise<void>;
  newFile(parent: string): Promise<void>;
  newFolder(parent: string): Promise<void>;
  rename(path: string, kind: EntryKind): Promise<void>;
  remove(path: string, kind: EntryKind): Promise<void>;
  setMain(path: string): Promise<void>;
  exportPdf(): Promise<void>;
  jumpTo(problem: Problem): Promise<void>;
  setLanguage(language: Language): void;
  installGrammar(): Promise<void>;
}

/** File types the editor opens (mirrors TEXT_EXTENSIONS in services/workspace.py). */
export const TEXT_EXTENSIONS = [".typ", ".bib", ".yml", ".yaml", ".csv", ".txt", ".toml", ".json", ".md"];

export function isTextFile(path: string): boolean {
  const lower = path.toLowerCase();
  return TEXT_EXTENSIONS.some((ext) => lower.endsWith(ext));
}
