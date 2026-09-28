// Status bar: cursor, language, compile status; AI selector in the right corner.

import type { Actions } from "../state/actions";
import type { AppState, Language, Store } from "../state/store";
import { el } from "../ui/dom";
import { mountAiSelector } from "../ai-selector/widget";

export function compileLabel(state: AppState): string {
  if (!state.connected) return "Reconnecting to the app…";
  const { compile } = state;
  const errors = state.problems.filter((p) => p.severity === "error").length;
  switch (compile.state) {
    case "no_workspace":
      return "No folder open";
    case "no_main":
      return "No main file";
    case "compiling":
      return "Compiling…";
    case "error":
      return errors === 1 ? "1 error" : `${errors} errors`;
    case "ok":
      return compile.durationMs === null ? "Compiled" : `Compiled in ${Math.round(compile.durationMs)} ms`;
  }
}

export function mountStatusbar(host: HTMLElement, store: Store<AppState>, actions: Actions): void {
  const cursor = el("span", { class: "status-item" });
  const language = el("select", { class: "status-select", "aria-label": "Document language", title: "Language for spelling and grammar checks" });
  for (const code of ["de-DE", "en-US"] satisfies Language[]) {
    language.append(el("option", { value: code }, code));
  }
  language.addEventListener("change", () => actions.setLanguage(language.value as Language));
  const compile = el("span", { class: "status-item compile-status", role: "status" });
  const left = el("div", { class: "status-left" }, cursor, language, compile);
  const right = el("div", { class: "status-right" });
  host.append(left, right);
  mountAiSelector(right);

  store.subscribe((state) => {
    cursor.textContent = state.active ? `Ln ${state.cursor.line}, Col ${state.cursor.column}` : "";
    language.value = state.language;
    compile.textContent = compileLabel(state);
    compile.dataset["state"] = state.connected ? state.compile.state : "offline";
  });
}
