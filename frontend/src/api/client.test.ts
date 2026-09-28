import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, getHealth } from "./client";

function fakeFetch(status: number, body: unknown): (input: string) => Promise<Response> {
  return (input) => {
    expect(input).toBe("/api/health");
    return Promise.resolve(new Response(JSON.stringify(body), { status }));
  };
}

describe("getHealth", () => {
  it("returns the parsed health response", async () => {
    const health = await getHealth(fakeFetch(200, { status: "ok", typst_version: "0.15.0" }));
    expect(health.typst_version).toBe("0.15.0");
  });

  it("rejects non-OK responses", async () => {
    await expect(getHealth(fakeFetch(500, {}))).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects malformed bodies", async () => {
    await expect(getHealth(fakeFetch(200, { status: "ok" }))).rejects.toThrow(/unexpected body/);
  });
});

describe("requests", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("carry the app header the backend requires for changes", async () => {
    const seen: RequestInit[] = [];
    vi.stubGlobal("fetch", (_url: string, init: RequestInit) => {
      seen.push(init);
      return Promise.resolve(new Response(JSON.stringify({ state: "ready" }), { status: 200 }));
    });
    await api.installCompletion();
    await api.saveFile("main.typ", "x");
    expect(seen.map((init) => (init.headers as Record<string, string>)["X-Typst-Writer"])).toEqual(["1", "1"]);
  });
});
