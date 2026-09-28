import { describe, expect, it } from "vitest";

import { movedPath, nameError, withTypExtension } from "./names";

describe("nameError", () => {
  it.each(["main.typ", "01-Einleitung.typ", "Übung (1).typ", "a b.TYP"])("accepts %s", (name) => {
    expect(nameError(name, "file")).toBeNull();
  });

  it.each(["", "notes.txt", ".hidden.typ", "a/b.typ", "a\\b.typ", "what?.typ", "x:y.typ", "CON.typ", "trail.typ."])(
    "rejects %s",
    (name) => {
      expect(nameError(name, "file")).not.toBeNull();
    },
  );

  it("does not require an extension for folders", () => {
    expect(nameError("kapitel", "folder")).toBeNull();
  });
});

describe("withTypExtension", () => {
  it("adds .typ to bare names only", () => {
    expect(withTypExtension("kapitel-1")).toBe("kapitel-1.typ");
    expect(withTypExtension("kapitel-1.typ")).toBe("kapitel-1.typ");
    expect(withTypExtension("notes.txt")).toBe("notes.txt");
  });
});

describe("movedPath", () => {
  it("maps the entry itself and anything inside a moved folder", () => {
    expect(movedPath("a.typ", "a.typ", "b.typ")).toBe("b.typ");
    expect(movedPath("kap/1.typ", "kap", "kapitel")).toBe("kapitel/1.typ");
    expect(movedPath("kapitel2/1.typ", "kap", "x")).toBeNull();
  });
});
