// Status bar: cursor, language, spelling check, compile status; AI selector in the right
// corner.

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

/** Text and tooltip of the spelling-check item. */
export function checkerLabel(state: AppState): { text: string; title: string; install: boolean } {
  const status = state.checker;
  if (status === null) return { text: "", title: "", install: false };
  switch (status.state) {
    case "not_installed":
      return { text: "Install spelling check", title: status.reason, install: true };
    case "installing": {
      const percent = status.progress === null ? "" : ` ${Math.floor(status.progress * 100)} %`;
      return { text: `Installing spelling check…${percent}`, title: status.reason, install: false };
    }
    case "starting":
      return { text: "Spelling check starting…", title: status.reason, install: false };
    case "failed":
      return { text: "Spelling check off", title: status.reason, install: false };
    case "ready": {
      const found = state.active === null ? undefined : state.findings[state.active]?.filter((p) => p.severity === "grammar");
      const title = "Spelling and grammar (LTeX+, offline). Hover an underline or press Ctrl+. for fixes.";
      if (found === undefined) return { text: "Spelling check on", title, install: false };
      const text = found.length === 0 ? "No spelling issues" : found.length === 1 ? "1 spelling issue" : `${found.length} spelling issues`;
      return { text, title, install: false };
    }
  }
}

export function mountStatusbar(host: HTMLElement, store: Store<AppState>, actions: Actions): void {
  const cursor = el("span", { class: "status-item" });
  const language = el("select", { class: "status-select", "aria-label": "Document language", title: "Language for spelling and grammar checks" });
  for (const code of ["de-DE", "en-US"] satisfies Language[]) {
    language.append(el("option", { value: code }, code));
  }
  language.addEventListener("change", () => actions.setLanguage(language.value as Language));
  const checker = el("span", { class: "status-item checker-status" });
  const install = el("button", { type: "button", class: "status-button" }, "Install spelling check");
  install.addEventListener("click", () => void actions.installGrammar());
  const compile = el("span", { class: "status-item compile-status", role: "status" });
  const left = el("div", { class: "status-left" }, cursor, language, checker, install, compile);
  const right = el("div", { class: "status-right" });
  host.append(left, right);
  mountAiSelector(right, store);

  store.subscribe((state) => {
    cursor.textContent = state.active ? `Ln ${state.cursor.line}, Col ${state.cursor.column}` : "";
    language.value = state.language;
    const spelling = checkerLabel(state);
    checker.hidden = spelling.install || spelling.text === "";
    checker.textContent = spelling.text;
    checker.title = spelling.title;
    checker.dataset["state"] = state.checker?.state ?? "";
    install.hidden = !spelling.install;
    install.title = spelling.title;
    compile.textContent = compileLabel(state);
    compile.dataset["state"] = state.connected ? state.compile.state : "offline";
  });
}
