import { describe, expect, it } from "vitest";

import { wordError } from "./words";

describe("wordError", () => {
  it("accepts one new word and explains every refusal", () => {
    expect(wordError("Messplatz", [])).toBeNull();
    expect(wordError("", [])).toMatch(/Type a word/);
    expect(wordError("zwei Wörter", [])).toMatch(/no spaces/);
    expect(wordError("x".repeat(101), [])).toMatch(/100 characters/);
    expect(wordError("Messplatz", ["Messplatz"])).toMatch(/already/);
  });
});
