import { describe, expect, it } from "vitest";

import { blockStart, clickToPt } from "./follow";

describe("blockStart", () => {
  const text = "= Titel\nErster Absatz\nzweite Zeile.\n\nZweiter Absatz.\n  \nDritter.";

  it("finds the paragraph around the cursor", () => {
    expect(blockStart(text, text.indexOf("zweite"))).toBe(text.indexOf("Erster"));
    expect(blockStart(text, text.indexOf("Zweiter") + 3)).toBe(text.indexOf("Zweiter"));
    expect(blockStart(text, text.length)).toBe(text.indexOf("Dritter"));
  });

  it("treats a heading line as its own block", () => {
    expect(blockStart(text, 3)).toBe(0);
    expect(blockStart(text, 0)).toBe(0);
  });

  it("clamps offsets", () => {
    expect(blockStart(text, -5)).toBe(0);
    expect(blockStart("", 10)).toBe(0);
  });
});

describe("clickToPt", () => {
  it("scales the click to the page height in pt", () => {
    expect(clickToPt(150, { top: 100, height: 200 }, 800)).toBe(200);
    expect(clickToPt(50, { top: 100, height: 200 }, 800)).toBe(0);
    expect(clickToPt(400, { top: 100, height: 200 }, 800)).toBe(800);
    expect(clickToPt(400, { top: 100, height: 0 }, 800)).toBe(0);
  });
});
