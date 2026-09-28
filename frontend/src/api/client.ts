// Typed REST client. Mirrors backend/src/typst_writer/api/schemas.py.

export interface HealthResponse {
  status: "ok";
  typst_version: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return v["status"] === "ok" && typeof v["typst_version"] === "string";
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
