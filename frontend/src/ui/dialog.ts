// Modal dialogs built on <dialog>. Every function resolves to null when cancelled.

import { el } from "./dom";

export interface Choice<T extends string> {
  label: string;
  value: T;
  kind?: "primary" | "danger";
}

function showDialog<T>(
  build: (dialog: HTMLDialogElement, close: (value: T | null) => void) => void,
): Promise<T | null> {
  return new Promise((resolve) => {
    const dialog = el("dialog", { class: "dialog" });
    let result: T | null = null;
    const close = (value: T | null): void => {
      result = value;
      dialog.close();
    };
    dialog.addEventListener("close", () => {
      dialog.remove();
      resolve(result);
    });
    build(dialog, close);
    document.body.append(dialog);
    dialog.showModal();
  });
}

function buttonRow<T extends string>(
  choices: Choice<T>[],
  close: (value: T | null) => void,
): HTMLElement {
  const row = el("div", { class: "dialog-buttons" });
  const cancel = el("button", { type: "button", class: "button" }, "Cancel");
  cancel.addEventListener("click", () => close(null));
  row.append(cancel);
  for (const choice of choices) {
    const button = el("button", { type: "button", class: `button ${choice.kind ?? ""}` }, choice.label);
    button.addEventListener("click", () => close(choice.value));
    row.append(button);
  }
  return row;
}

export function chooseAction<T extends string>(
  title: string,
  message: string,
  choices: Choice<T>[],
): Promise<T | null> {
  return showDialog<T>((dialog, close) => {
    dialog.append(el("h2", {}, title), el("p", {}, message), buttonRow(choices, close));
  });
}

export async function confirmAction(
  title: string,
  message: string,
  confirmLabel: string,
  kind: "primary" | "danger" = "primary",
): Promise<boolean> {
  const result = await chooseAction(title, message, [{ label: confirmLabel, value: "ok", kind }]);
  return result === "ok";
}

export function showMessage(title: string, message: string): Promise<null> {
  return showDialog<never>((dialog, close) => {
    const ok = el("button", { type: "button", class: "button primary" }, "OK");
    ok.addEventListener("click", () => close(null));
    dialog.append(el("h2", {}, title), el("p", { class: "dialog-message" }, message), el("div", { class: "dialog-buttons" }, ok));
  });
}

export interface PromptOptions {
  title: string;
  label: string;
  value: string;
  confirmLabel: string;
  /** Selected on open, e.g. the file name without ".typ". */
  selectEnd?: number;
  /** Returns an error message, or null when the value is acceptable. */
  validate?: (value: string) => string | null;
}

export function promptText(options: PromptOptions): Promise<string | null> {
  return showDialog<string>((dialog, close) => {
    const input = el("input", { type: "text", class: "text-input", spellcheck: "false" });
    input.value = options.value;
    const error = el("p", { class: "dialog-error", role: "alert" });
    const form = el("form", { method: "dialog" });
    const submit = el("button", { type: "submit", class: "button primary" }, options.confirmLabel);
    const cancel = el("button", { type: "button", class: "button" }, "Cancel");
    cancel.addEventListener("click", () => close(null));
    const check = (): boolean => {
      const message = options.validate?.(input.value.trim()) ?? null;
      error.textContent = message ?? "";
      submit.disabled = message !== null;
      return message === null;
    };
    input.addEventListener("input", check);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (check()) close(input.value.trim());
    });
    form.append(
      el("label", { class: "dialog-label" }, options.label, input),
      error,
      el("div", { class: "dialog-buttons" }, cancel, submit),
    );
    dialog.append(el("h2", {}, options.title), form);
    queueMicrotask(() => {
      input.focus();
      input.setSelectionRange(0, options.selectEnd ?? input.value.length);
      check();
    });
  });
}
