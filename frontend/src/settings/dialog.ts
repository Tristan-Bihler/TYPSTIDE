// Settings dialog (gear in the top bar, Ctrl+,): appearance, editor behaviour, language
// tools. Changes apply and are saved at once; "Done" only closes the dialog.

import { api } from "../api/client";
import type { Theme, UiSettings } from "../api/types";
import type { Actions } from "../state/actions";
import type { AppState, Store } from "../state/store";
import { showMessage } from "../ui/dialog";
import { el } from "../ui/dom";

const THEMES: { value: Theme; label: string }[] = [
  { value: "system", label: "Like the system" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];
const DELAYS = [1000, 2000, 5000, 10000];

export function applyTheme(theme: Theme): void {
  if (theme === "system") delete document.documentElement.dataset["theme"];
  else document.documentElement.dataset["theme"] = theme;
}

/** One labelled setting: the label (and an optional hint) left, the control right. */
function row(label: string, control: HTMLElement, hint = ""): HTMLElement {
  const id = `setting-${label.toLowerCase().replaceAll(/[^a-z]+/g, "-")}`;
  control.id ||= id;
  const text = el("div", { class: "setting-text" }, el("label", { for: control.id }, label));
  if (hint) text.append(el("p", { class: "setting-hint" }, hint));
  return el("div", { class: "setting-row" }, text, control);
}

function section(title: string, ...rows: HTMLElement[]): HTMLElement {
  return el("section", { class: "settings-section" }, el("h3", {}, title), ...rows);
}

function checkbox(checked: boolean): HTMLInputElement {
  const box = el("input", { type: "checkbox", class: "setting-check" });
  box.checked = checked;
  return box;
}

export interface SettingsContext {
  store: Store<AppState>;
  actions: Actions;
  /** Extra sections added by later features (word list, autocomplete). */
  sections?: (() => HTMLElement)[];
}

export function openSettings(ctx: SettingsContext): void {
  if (document.querySelector("dialog.settings-dialog")) return;
  const { store } = ctx;
  const save = (patch: Partial<UiSettings>): void => {
    const next = { ...store.get().ui, ...patch };
    store.set({ ui: next });
    applyTheme(next.theme);
    api.saveUiSettings(next).catch(async (error: unknown) => {
      await showMessage("Could not save the setting", error instanceof Error ? error.message : String(error));
    });
  };
  const ui = store.get().ui;

  // Appearance: a segmented choice (radio buttons, so arrow keys work).
  const themes = el("div", { class: "segmented", role: "radiogroup", "aria-label": "Theme", id: "setting-theme" });
  for (const { value, label } of THEMES) {
    const input = el("input", { type: "radio", name: "theme", value });
    input.checked = ui.theme === value;
    input.addEventListener("change", () => save({ theme: value }));
    themes.append(el("label", { class: "segment" }, input, el("span", {}, label)));
  }

  // Editor behaviour.
  const autosave = checkbox(ui.autosave);
  const delay = el("select", { class: "setting-select", "aria-label": "Save after" });
  for (const ms of DELAYS) delay.append(el("option", { value: String(ms) }, `${ms / 1000} s`));
  delay.value = String(DELAYS.includes(ui.autosave_delay_ms) ? ui.autosave_delay_ms : 2000);
  delay.disabled = !ui.autosave;
  autosave.addEventListener("change", () => {
    delay.disabled = !autosave.checked;
    save({ autosave: autosave.checked });
  });
  delay.addEventListener("change", () => save({ autosave_delay_ms: Number(delay.value) }));
  const follow = checkbox(ui.preview_follows_cursor);
  follow.addEventListener("change", () => save({ preview_follows_cursor: follow.checked }));

  // Spelling check status (install from here too).
  const spelling = el("span", { class: "setting-status" });
  const install = el("button", { type: "button", class: "button" }, "Install (about 320 MB)");
  install.addEventListener("click", () => void ctx.actions.installGrammar());
  const spellingControl = el("div", { class: "setting-control" }, spelling, install);
  const unsubscribe = store.subscribe((state) => {
    const status = state.checker;
    spelling.textContent =
      status === null
        ? "Checking…"
        : {
            not_installed: "Not installed",
            installing: "Installing…",
            starting: "Starting…",
            ready: "Ready (offline)",
            failed: "Off",
          }[status.state];
    spelling.title = status?.reason ?? "";
    install.hidden = status?.state !== "not_installed";
  });

  const done = el("button", { type: "button", class: "button primary" }, "Done");
  const dialog = el(
    "dialog",
    { class: "dialog settings-dialog", "aria-labelledby": "settings-title" },
    el("h2", { id: "settings-title" }, "Settings"),
    el(
      "div",
      { class: "settings-body" },
      section("Appearance", row("Theme", themes)),
      section(
        "Editor",
        row("Save automatically", autosave, "Changed files are saved a moment after you stop typing."),
        row("Save after", delay),
        row("Preview follows the cursor", follow, "Scrolls the preview to the paragraph you are editing."),
      ),
      section("Spelling and grammar", row("LTeX+", spellingControl, "Checks German and English on this computer.")),
      ...(ctx.sections ?? []).map((build) => build()),
    ),
    el("div", { class: "dialog-buttons" }, done),
  );
  done.addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    unsubscribe();
    dialog.remove();
  });
  document.body.append(dialog);
  dialog.showModal();
  (themes.querySelector<HTMLInputElement>("input:checked") ?? done).focus();
}
