import { EditorSelection, EditorState } from "@codemirror/state";
import { describe, expect, it } from "vitest";

import { slugify, suggestLabel, labelError } from "../state/labels";
import { insertBlock, insertInline, linePrefix, wrap } from "./snippetOps";

/** State from text where "|" marks the cursor and "[...]" a selection. */
function stateOf(marked: string): EditorState {
  const from = marked.search(/[|[]/);
  if (marked[from] === "|") {
    return EditorState.create({ doc: marked.replace("|", ""), selection: EditorSelection.cursor(from) });
  }
  const to = marked.indexOf("]") - 1;
  return EditorState.create({ doc: marked.replace("[", "").replace("]", ""), selection: EditorSelection.range(from, to) });
}

function run(state: EditorState, spec: ReturnType<typeof wrap>): { doc: string; selected: string } {
  const next = state.update(spec).state;
  const { from, to } = next.selection.main;
  return { doc: next.doc.toString(), selected: next.sliceDoc(from, to) };
}

describe("wrap", () => {
  it("wraps the selection and keeps it selected", () => {
    expect(run(stateOf("ein [Wort] hier"), wrap(stateOf("ein [Wort] hier"), "*{selection}*", "text"))).toEqual({
      doc: "ein *Wort* hier",
      selected: "Wort",
    });
  });

  it("inserts and selects the placeholder without a selection", () => {
    const s = stateOf("Satz|");
    expect(run(s, wrap(s, "#footnote[{selection}]", "footnote text"))).toEqual({
      doc: "Satz#footnote[footnote text]",
      selected: "footnote text",
    });
  });
});

describe("linePrefix", () => {
  const apply = (marked: string, prefix: string): string => {
    const s = stateOf(marked);
    return run(s, linePrefix(s, prefix)).doc;
  };

  it("adds, replaces and toggles heading and list markers", () => {
    expect(apply("Titel|", "== ")).toBe("== Titel");
    expect(apply("= Ti|tel", "=== ")).toBe("=== Titel");
    expect(apply("== Ti|tel", "== ")).toBe("Titel");
    expect(apply("- Punkt|", "+ ")).toBe("+ Punkt");
  });

  it("applies to every selected line and keeps indentation", () => {
    expect(apply("[a\n  - b\nc]", "- ")).toBe("- a\n  - b\n- c");
    expect(apply("[- a\n- b]", "- ")).toBe("a\nb");
  });
});

describe("insertBlock / insertInline", () => {
  it("uses an empty line or starts a new one", () => {
    const empty = stateOf("Text\n|\nMehr");
    expect(run(empty, insertBlock(empty, "#outline()")).doc).toBe("Text\n#outline()\nMehr");
    const full = stateOf("Te|xt\nMehr");
    expect(run(full, insertBlock(full, "#pagebreak()")).doc).toBe("Text\n#pagebreak()\nMehr");
  });

  it("replaces the selection inline", () => {
    const s = stateOf("siehe [x] oben");
    expect(run(s, insertInline(s, "@tab:a")).doc).toBe("siehe @tab:a oben");
  });
});

describe("labels", () => {
  it("mirrors the backend slug rules", () => {
    expect(slugify("Messwerte (Übersicht) für März")).toBe("messwerte-uebersicht-fuer-maerz");
    expect(suggestLabel("tab", "Messwerte", new Set(["tab:messwerte"]))).toBe("tab:messwerte-2");
    expect(suggestLabel("fig", "", new Set())).toBe("fig:fig");
  });

  it("validates labels", () => {
    expect(labelError("", new Set())).toBeNull();
    expect(labelError("tab:größe_2.b", new Set())).toBeNull();
    expect(labelError("tab werte", new Set())).not.toBeNull();
    expect(labelError("tab:a", new Set(["tab:a"]))).toContain("already used");
  });
});
