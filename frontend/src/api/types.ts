// Mirrors backend/src/typst_writer/api/schemas.py and domain/models.py.

export type Severity = "error" | "warning" | "grammar" | "ai";

export interface Problem {
  file: string; // workspace-relative; "" when the problem has no location
  line: number; // 1-based; 0 if unknown
  column: number; // 1-based; 0 if unknown
  severity: Severity;
  message: string;
  source: string;
}

export interface WorkspaceInfo {
  root: string;
  name: string;
  main: string | null;
}

export interface TreeNode {
  name: string;
  path: string;
  kind: "file" | "folder";
  children: TreeNode[];
}

export interface Tree {
  root: TreeNode;
  truncated: boolean;
}

export interface DirListing {
  path: string;
  parent: string | null;
  dirs: string[];
}

export interface FileContent {
  path: string;
  content: string;
}

export interface EntryPath {
  path: string;
}

// --- WebSocket ---------------------------------------------------------------------

export type ClientMessage =
  | { type: "doc_changed"; path: string; content: string }
  | { type: "doc_closed"; path: string }
  | { type: "refresh" };

export type CompileState = "compiling" | "ok" | "error" | "no_main" | "no_workspace";

export interface CompileStatus {
  type: "compile_status";
  state: CompileState;
  main: string | null;
  duration_ms: number | null;
}

export interface PageUpdate {
  index: number;
  hash: string;
  svg: string | null; // null: unchanged since the previous message
}

export type ServerMessage =
  | CompileStatus
  | { type: "preview_pages"; pages: PageUpdate[] }
  | { type: "problems"; problems: Problem[] }
  | { type: "workspace_changed"; workspace: WorkspaceInfo | null; reopened: boolean };

// --- insert toolbar ----------------------------------------------------------------

export type SnippetKind = "wrap" | "line_prefix" | "block" | "dialog";
export type DialogKind = "table" | "figure" | "equation" | "reference" | "bibliography" | "chart";

export interface Snippet {
  id: string;
  label: string;
  group: string;
  kind: SnippetKind;
  template: string;
  placeholder: string;
  dialog: DialogKind | null;
  shortcut: string | null;
  title: string;
  in_toolbar: boolean;
  required_packages: string[];
}

export type TargetKind = "heading" | "figure" | "table" | "equation" | "label" | "citation";

export interface ReferenceTarget {
  key: string;
  kind: TargetKind;
  file: string;
  line: number;
  description: string;
}

export interface WorkspaceIndex {
  targets: ReferenceTarget[];
  images: string[];
  bibliographies: string[];
  has_bibliography_call: boolean;
}
