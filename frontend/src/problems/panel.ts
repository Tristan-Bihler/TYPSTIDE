// Problems panel: compile errors and warnings (grammar and AI issues in later phases),
// grouped by file. Click to jump to the location.

import type { Problem } from "../api/types";
import type { Actions } from "../state/actions";
import type { AppState, Store } from "../state/store";
import { el } from "../ui/dom";
import { iconNode, icons } from "../ui/icons";

export function groupByFile(problems: Problem[]): Map<string, Problem[]> {
  const groups = new Map<string, Problem[]>();
  for (const problem of problems) {
    const list = groups.get(problem.file) ?? [];
    list.push(problem);
    groups.set(problem.file, list);
  }
  for (const list of groups.values()) list.sort((a, b) => a.line - b.line || a.column - b.column);
  return groups;
}

export function mountProblems(host: HTMLElement, store: Store<AppState>, actions: Actions): void {
  const count = el("span", { class: "count" });
  const title = el("h2", { class: "panel-title" }, "Problems", count);
  const body = el("div", { class: "panel-body problem-list" });
  host.append(title, body);

  store.subscribe((state, previous) => {
    if (state !== previous && state.problems === previous.problems) return;
    count.textContent = state.problems.length > 0 ? String(state.problems.length) : "";
    count.classList.toggle("has-errors", state.problems.some((p) => p.severity === "error"));
    body.replaceChildren();
    if (state.problems.length === 0) {
      body.append(el("p", { class: "empty" }, "No problems."));
      return;
    }
    for (const [file, problems] of groupByFile(state.problems)) {
      body.append(el("h3", { class: "problem-file" }, file === "" ? "General" : file));
      for (const problem of problems) {
        const where = problem.line > 0 ? `${problem.line}:${problem.column}` : "";
        const row = el(
          "button",
          { type: "button", class: `problem ${problem.severity}`, title: problem.message },
          iconNode(problem.severity === "error" ? icons.error : icons.warning),
          el("span", { class: "problem-message" }, problem.message),
          el("span", { class: "problem-where" }, where),
        );
        if (file === "") row.disabled = true;
        row.addEventListener("click", () => void actions.jumpTo(problem));
        body.append(row);
      }
    }
  });
}
