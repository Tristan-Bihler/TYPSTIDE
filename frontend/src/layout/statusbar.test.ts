import { describe, expect, it } from "vitest";

import type { CheckerStatus, Problem } from "../api/types";
import { initialState, type AppState } from "../state/store";
import { checkerLabel } from "./statusbar";

function state(checker: CheckerStatus | null, findings: Problem[] | undefined = undefined): AppState {
  return { ...initialState, checker, active: "a.typ", findings: findings === undefined ? {} : { "a.typ": findings } };
}

const issue: Problem = { file: "a.typ", line: 1, column: 1, severity: "grammar", message: "x", source: "ltex" };

describe("checkerLabel", () => {
  it("offers the install while LTeX+ is missing", () => {
    expect(checkerLabel(state({ state: "not_installed", reason: "needs LTeX+", progress: null }))).toEqual({
      text: "Install spelling check",
      title: "needs LTeX+",
      install: true,
    });
  });

  it("shows install progress and the findings of the active file", () => {
    expect(checkerLabel(state({ state: "installing", reason: "", progress: 0.426 })).text).toBe("Installing spelling check… 42 %");
    const ready: CheckerStatus = { state: "ready", reason: "", progress: null };
    expect(checkerLabel(state(ready)).text).toBe("Spelling check on");
    expect(checkerLabel(state(ready, [])).text).toBe("No spelling issues");
    expect(checkerLabel(state(ready, [issue, issue])).text).toBe("2 spelling issues");
  });
});
