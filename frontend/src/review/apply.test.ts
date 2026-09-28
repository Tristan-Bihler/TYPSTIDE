import { EditorState } from "@codemirror/state";
import { describe, expect, it } from "vitest";

import type { Suggestion } from "../api/types";
import { applyAccepted } from "./apply";

const doc = "Vorher. Ein 😀 Fehlr, sehr sehr klar. Nachher.";
const from = doc.indexOf("Ein");
const to = doc.indexOf(" Nachher");
const reviewed = { path: "k.typ", from, to, text: doc.slice(from, to) };

function suggestion(original: string, replacement: string): Suggestion {
  const start = doc.indexOf(original); // JS indexOf counts UTF-16 units, like the backend
  return { id: original, source: "claude", start, end: start + original.length, original, replacement, reason: "", category: "style" };
}

describe("applyAccepted", () => {
  it("applies accepted changes in one transaction despite an emoji before them", () => {
    const state = EditorState.create({ doc });
    const spec = applyAccepted(state, "k.typ", reviewed, [suggestion("sehr sehr", "sehr"), suggestion("Fehlr", "Fehler")]);
    expect(typeof spec).not.toBe("string");
    if (typeof spec === "string") return;
    expect(state.update(spec).state.doc.toString()).toBe("Vorher. Ein 😀 Fehler, sehr klar. Nachher.");
  });

  it("refuses when the text changed or another file is active", () => {
    const changed = EditorState.create({ doc: doc.replace("klar", "deutlich") });
    expect(applyAccepted(changed, "k.typ", reviewed, [])).toMatch(/changed/);
    expect(applyAccepted(EditorState.create({ doc }), "other.typ", reviewed, [])).toMatch(/Open k\.typ/);
  });
});
