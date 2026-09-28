import { ChangeSet, EditorState } from "@codemirror/state";
import { describe, expect, it } from "vitest";

import type { Suggestion } from "../api/types";
import { ignoreKey, mapMarks, markAt, marksOf, setSuggestions, suggestionLayer, toMarks } from "./layer";
import { suggestionProblems } from "./problems";

function finding(start: number, end: number, original: string, extra: Partial<Suggestion> = {}): Suggestion {
  return {
    id: `${start}`,
    source: "rule",
    start,
    end,
    original,
    replacement: original,
    reason: "Möglicher Tippfehler gefunden.",
    category: "spelling",
    fixes: [],
    rule: "GERMAN_SPELLER_RULE",
    ...extra,
  };
}

describe("marks", () => {
  const doc = "Ein Fehlr und ein ein Satz.";
  const marks = toMarks([finding(4, 9, "Fehlr"), finding(14, 21, "ein ein"), finding(20, 99, "bad")], doc.length);

  it("skips findings that do not fit the document", () => {
    expect(marks.map((m) => m.suggestion.original)).toEqual(["Fehlr", "ein ein"]);
  });

  it("move with edits before them and vanish when their text is edited", () => {
    const insertBefore = ChangeSet.of({ from: 0, insert: "😀 " }, doc.length);
    expect(mapMarks(marks, insertBefore).map((m) => [m.from, m.to])).toEqual([
      [7, 12],
      [17, 24],
    ]);
    const editInside = ChangeSet.of({ from: 6, to: 7, insert: "h" }, doc.length);
    expect(mapMarks(marks, editInside).map((m) => m.suggestion.original)).toEqual(["ein ein"]);
  });

  it("are found by position, including their edges", () => {
    expect(markAt(marks, 4)?.suggestion.original).toBe("Fehlr");
    expect(markAt(marks, 9)?.suggestion.original).toBe("Fehlr");
    expect(markAt(marks, 11)).toBeNull();
  });

  it("share an ignore key when rule and text match", () => {
    expect(ignoreKey(finding(0, 5, "Fehlr"))).toBe(ignoreKey(finding(30, 35, "Fehlr")));
    expect(ignoreKey(finding(0, 5, "Fehlr"))).not.toBe(ignoreKey(finding(0, 5, "Fehlr", { rule: "DE_CASE" })));
  });
});

describe("suggestionProblems", () => {
  it("reports 1-based line and column with the proposed fix", () => {
    const content = "= Titel\n\nEin 😀 Fehlr.";
    const start = content.indexOf("Fehlr");
    const [problem] = suggestionProblems("a.typ", content, [finding(start, start + 5, "Fehlr", { fixes: ["Fehler"] })]);
    expect(problem).toEqual({
      file: "a.typ",
      line: 3,
      column: 8,
      severity: "grammar",
      message: "Möglicher Tippfehler gefunden. (Fehlr → Fehler)",
      source: "ltex",
    });
  });
});

describe("suggestion layer", () => {
  it("replaces each source's findings independently", () => {
    const doc = "Ein Fehlr, weil er hat keine Zeit.";
    let state = EditorState.create({ doc, extensions: suggestionLayer({ ignore: () => {}, addToDictionary: () => {} }) });
    const rule = finding(4, 9, "Fehlr");
    const local = finding(11, 33, "weil er hat keine Zeit", { source: "local_ai", category: "grammar", rule: "", id: "l" });
    state = state.update({ effects: setSuggestions.of({ source: "rule", suggestions: [rule] }) }).state;
    state = state.update({ effects: setSuggestions.of({ source: "local_ai", suggestions: [local] }) }).state;
    expect(marksOf(state).map((m) => m.suggestion.source).sort()).toEqual(["local_ai", "rule"]);
    state = state.update({ effects: setSuggestions.of({ source: "rule", suggestions: [] }) }).state;
    expect(marksOf(state).map((m) => m.suggestion.original)).toEqual(["weil er hat keine Zeit"]);
  });

  it("keeps ignore keys apart per source", () => {
    const rule = finding(0, 5, "Fehlr", { category: "grammar" });
    expect(ignoreKey(rule)).not.toBe(ignoreKey({ ...rule, source: "local_ai" }));
  });
});
