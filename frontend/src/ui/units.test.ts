import { describe, expect, it } from "vitest";

import { parseServerMessage } from "../api/live";
import type { Problem } from "../api/types";
import { compileLabel } from "../layout/statusbar";
import { svgSize } from "../preview/preview";
import { groupByFile } from "../problems/panel";
import { initialState, type AppState } from "../state/store";
import { basename, dirname } from "./dom";

const problem = (file: string, line: number, severity: Problem["severity"] = "error"): Problem => ({
  file,
  line,
  column: 1,
  severity,
  message: "m",
  source: "typst",
});

describe("paths", () => {
  it("splits workspace-relative paths", () => {
    expect(basename("kapitel/01.typ")).toBe("01.typ");
    expect(dirname("kapitel/01.typ")).toBe("kapitel");
    expect(dirname("main.typ")).toBe("");
  });
});

describe("groupByFile", () => {
  it("groups by file and sorts by line", () => {
    const groups = groupByFile([problem("b.typ", 9), problem("a.typ", 3), problem("b.typ", 2)]);
    expect([...groups.keys()]).toEqual(["b.typ", "a.typ"]);
    expect(groups.get("b.typ")?.map((p) => p.line)).toEqual([2, 9]);
  });
});

describe("svgSize", () => {
  it("reads A4 from Typst SVG output", () => {
    const size = svgSize('<svg viewBox="0 0 595.28 841.89" width="595.275590551pt" height="841.88976378pt">');
    expect(Math.round(size.width)).toBe(794);
    expect(Math.round(size.height)).toBe(1123);
  });
});

describe("parseServerMessage", () => {
  it("accepts known message types and ignores everything else", () => {
    expect(parseServerMessage('{"type":"problems","problems":[]}')?.type).toBe("problems");
    expect(parseServerMessage('{"type":"evil"}')).toBeNull();
    expect(parseServerMessage("not json")).toBeNull();
  });
});

describe("compileLabel", () => {
  const state = (patch: Partial<AppState>): AppState => ({ ...initialState, connected: true, ...patch });

  it("describes each compile state in plain words", () => {
    expect(compileLabel(state({ compile: { state: "ok", main: "main.typ", durationMs: 12.4 } }))).toBe(
      "Compiled in 12 ms",
    );
    expect(
      compileLabel(
        state({
          compile: { state: "error", main: "main.typ", durationMs: 3 },
          problems: [problem("a.typ", 1), problem("a.typ", 2, "warning")],
        }),
      ),
    ).toBe("1 error");
    expect(compileLabel(state({ compile: { state: "no_main", main: null, durationMs: null } }))).toBe("No main file");
    expect(compileLabel({ ...initialState, connected: false })).toBe("Reconnecting to the app…");
  });
});
