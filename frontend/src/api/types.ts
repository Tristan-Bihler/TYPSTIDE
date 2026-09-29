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
  | { type: "doc_changed"; path: string; content: string; version: number }
  | { type: "doc_opened"; path: string; content: string; version: number }
  | { type: "typing_paused"; path: string; version: number; cursor: number }
  | { type: "preview_click"; page: number; y: number }
  | { type: "cursor_moved"; path: string; offset: number }
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
  | { type: "workspace_changed"; workspace: WorkspaceInfo | null; reopened: boolean }
  | SuggestionsMessage
  | { type: "checker_status"; status: CheckerStatus }
  | { type: "completer_status"; status: CheckerStatus }
  | { type: "local_check_status"; pending: number }
  | { type: "jump"; path: string; offset: number } // answer to preview_click (UTF-16 offset)
  | { type: "preview_position"; path: string; offset: number; page: number; y: number }
  | WordCount;

export interface WordCount {
  type: "word_count";
  total: number; // main file + every included chapter
  files: Record<string, number>;
}

// --- autocomplete (Tinymist) --------------------------------------------------------

export interface CompletionItem {
  label: string;
  detail: string;
  kind: string; // editor icon: function, variable, constant, keyword, type, label, ...
  insert: string; // plain text, or an LSP snippet when `snippet`
  snippet: boolean;
  start: number; // UTF-16 range it replaces
  end: number;
}

// --- format controls (font, size, line spacing) ---------------------------------

export interface FormatOptions {
  fonts: { family: string; builtin: boolean }[];
  sizes: number[];
  default_size: number;
  default_font: string;
  line_spacing: { label: string; leading: string; default: boolean }[];
}

export type FormatChange = { kind: "font" | "size" | "line_spacing"; value: string };

export interface TextEdit {
  start: number; // UTF-16, like the editor
  end: number;
  insert: string;
}

export interface CurrentFormat {
  font: string | null;
  size: string | null; // e.g. "14pt"
  leading: string | null; // e.g. "1.05em"
}

// --- look and editor behaviour ---------------------------------------------------------

export type Theme = "system" | "light" | "dark";

export interface UiSettings {
  theme: Theme;
  autosave: boolean;
  autosave_delay_ms: number;
  preview_follows_cursor: boolean;
}

export interface OpenTabs {
  tabs: { path: string; cursor: number }[];
  active: string | null;
}

export interface SuggestionsMessage {
  type: "suggestions";
  path: string;
  version: number | null; // the doc version that was checked
  source: Suggestion["source"];
  suggestions: Suggestion[];
}

// --- spelling and grammar ------------------------------------------------------------

export type CheckerState = "not_installed" | "installing" | "starting" | "ready" | "failed";

export interface CheckerStatus {
  state: CheckerState;
  reason: string;
  progress: number | null; // 0..1 while installing
}

export interface GrammarSettings {
  language: "de-DE" | "en-US";
  dictionary: Partial<Record<"de-DE" | "en-US", string[]>>;
}

export interface GrammarOverview {
  status: CheckerStatus;
  settings: GrammarSettings;
}

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

// --- AI -----------------------------------------------------------------------------

export interface AIStatus {
  available: boolean;
  reason: string;
  models: string[];
}

export interface AISettings {
  local_model: string | null;
  claude_model: string | null;
}

export interface AIOverview {
  local: AIStatus;
  claude: AIStatus;
  settings: AISettings;
}

export type ReviewMode = "check" | "improve" | "shorten" | "explain";

export interface ReviewRequest {
  selection: string;
  selection_start: number;
  context_before: string;
  context_after: string;
  mode: ReviewMode;
  language: "de-DE" | "en-US";
}

export interface Suggestion {
  id: string;
  source: "rule" | "local_ai" | "claude";
  start: number; // UTF-16 document offsets, like CodeMirror
  end: number;
  original: string;
  replacement: string;
  reason: string;
  category: string; // rule checks: "spelling" | "grammar"
  fixes?: string[]; // rule checks: every offered replacement
  rule?: string; // rule checks: the LanguageTool rule id
}

export interface ReviewResult {
  revised_text: string;
  explanation: string;
  changes: Suggestion[];
  dropped: number;
}
