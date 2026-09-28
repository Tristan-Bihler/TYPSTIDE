// Typed REST client for /api. Mirrors backend/src/typst_writer/api/rest.py.

import type {
  AIOverview,
  AISettings,
  CheckerStatus,
  CompletionItem,
  DirListing,
  EntryPath,
  FileContent,
  GrammarOverview,
  GrammarSettings,
  OpenTabs,
  Problem,
  ReviewRequest,
  ReviewResult,
  Snippet,
  Tree,
  UiSettings,
  WorkspaceIndex,
  WorkspaceInfo,
} from "./types";

export interface HealthResponse {
  status: "ok";
  typst_version: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code: string = "unknown",
    readonly problems: Problem[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isHealthResponse(value: unknown): value is HealthResponse {
  return isRecord(value) && value["status"] === "ok" && typeof value["typst_version"] === "string";
}

async function toApiError(response: Response, what: string): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // not JSON
  }
  if (isRecord(body) && typeof body["detail"] === "string") {
    const code = typeof body["code"] === "string" ? body["code"] : "unknown";
    const problems = Array.isArray(body["problems"]) ? (body["problems"] as Problem[]) : [];
    return new ApiError(response.status, body["detail"], code, problems);
  }
  return new ApiError(response.status, `${what} failed: ${response.status}`);
}

export async function getHealth(fetchFn: Fetch = fetch): Promise<HealthResponse> {
  const response = await fetchFn("/api/health");
  if (!response.ok) {
    throw new ApiError(response.status, `GET /api/health failed: ${response.status}`);
  }
  const body: unknown = await response.json();
  if (!isHealthResponse(body)) {
    throw new ApiError(response.status, "GET /api/health returned an unexpected body");
  }
  return body;
}

/** Sent with every request; the backend refuses changing requests without it, so no other
 * web page can make the app act (a custom header needs a CORS preflight). */
export const APP_HEADERS: Record<string, string> = { "X-Typst-Writer": "1" };

async function request<T>(method: string, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const init: RequestInit = { method, headers: { ...APP_HEADERS } };
  if (signal !== undefined) init.signal = signal;
  if (body !== undefined) {
    init.headers = { ...APP_HEADERS, "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(url, init);
  if (!response.ok) throw await toApiError(response, `${method} ${url}`);
  return (await response.json()) as T;
}

const q = (path: string): string => `?path=${encodeURIComponent(path)}`;

export const api = {
  workspace: (): Promise<WorkspaceInfo | null> => request("GET", "/api/workspace"),
  openWorkspace: (path: string): Promise<WorkspaceInfo> =>
    request("POST", "/api/workspace/open", { path }),
  browse: (path: string | null): Promise<DirListing> =>
    request("GET", `/api/workspace/browse${path === null ? "" : q(path)}`),
  tree: (): Promise<Tree> => request("GET", "/api/workspace/tree"),
  setMain: (path: string | null): Promise<WorkspaceInfo> =>
    request("PUT", "/api/workspace/main", { path }),
  readFile: (path: string): Promise<FileContent> => request("GET", `/api/workspace/file${q(path)}`),
  saveFile: (path: string, content: string): Promise<EntryPath> =>
    request("PUT", "/api/workspace/file", { path, content }),
  createFile: (parent: string, name: string, overwrite = false): Promise<EntryPath> =>
    request("POST", "/api/workspace/file", { parent, name, overwrite }),
  createFolder: (parent: string, name: string): Promise<EntryPath> =>
    request("POST", "/api/workspace/folder", { parent, name }),
  rename: (path: string, newName: string, overwrite = false): Promise<EntryPath> =>
    request("POST", "/api/workspace/rename", { path, new_name: newName, overwrite }),
  delete: (path: string): Promise<EntryPath> => request("DELETE", `/api/workspace/entry${q(path)}`),
  snippets: (): Promise<Snippet[]> => request("GET", "/api/snippets"),
  renderSnippet: (
    id: string,
    params: Record<string, unknown>,
    overlays: Record<string, string>,
  ): Promise<{ code: string }> =>
    request("POST", `/api/snippets/${encodeURIComponent(id)}/render`, { params, overlays }),
  references: (overlays: Record<string, string>): Promise<WorkspaceIndex> =>
    request("POST", "/api/workspace/references", { overlays }),
  aiStatus: (refresh = false): Promise<AIOverview> =>
    request("GET", `/api/ai/status${refresh ? "?refresh=true" : ""}`),
  setAiSettings: (settings: AISettings): Promise<AIOverview> => request("PUT", "/api/ai/settings", settings),
  review: (body: ReviewRequest, signal: AbortSignal): Promise<ReviewResult> =>
    request("POST", "/api/review", body, signal),
  uiSettings: (): Promise<UiSettings> => request("GET", "/api/settings/ui"),
  saveUiSettings: (settings: UiSettings): Promise<UiSettings> => request("PUT", "/api/settings/ui", settings),
  openTabs: (): Promise<OpenTabs> => request("GET", "/api/workspace/tabs"),
  saveOpenTabs: (tabs: OpenTabs): Promise<OpenTabs> => request("PUT", "/api/workspace/tabs", tabs),
  completionStatus: (): Promise<CheckerStatus> => request("GET", "/api/completion"),
  installCompletion: (): Promise<CheckerStatus> => request("POST", "/api/completion/install"),
  complete: (path: string, content: string, offset: number, signal: AbortSignal): Promise<CompletionItem[]> =>
    request("POST", "/api/complete", { path, content, offset }, signal),
  grammar: (): Promise<GrammarOverview> => request("GET", "/api/grammar"),
  installGrammar: (): Promise<GrammarOverview> => request("POST", "/api/grammar/install"),
  setGrammarLanguage: (language: GrammarSettings["language"]): Promise<GrammarOverview> =>
    request("PUT", "/api/grammar/settings", { language }),
  addToDictionary: (language: GrammarSettings["language"], word: string): Promise<GrammarOverview> =>
    request("POST", "/api/grammar/dictionary", { language, word }),
  removeFromDictionary: (language: GrammarSettings["language"], word: string): Promise<GrammarOverview> =>
    request(
      "DELETE",
      `/api/grammar/dictionary?${new URLSearchParams({ language, word }).toString()}`,
    ),

  async exportPdf(overlays: Record<string, string>): Promise<{ blob: Blob; filename: string }> {
    const response = await fetch("/api/export/pdf", {
      method: "POST",
      headers: { ...APP_HEADERS, "Content-Type": "application/json" },
      body: JSON.stringify({ overlays }),
    });
    if (!response.ok) throw await toApiError(response, "Export PDF");
    const disposition = response.headers.get("content-disposition") ?? "";
    const match = /filename\*=UTF-8''([^;]+)/.exec(disposition);
    const filename = match?.[1] !== undefined ? decodeURIComponent(match[1]) : "document.pdf";
    return { blob: await response.blob(), filename };
  },
};
