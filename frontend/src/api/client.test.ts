import { describe, expect, it } from "vitest";

import { ApiError, getHealth } from "./client";

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
