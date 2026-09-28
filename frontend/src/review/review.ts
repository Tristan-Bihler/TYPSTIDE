// Selection review with Claude: mode picker → progress (cancellable) → diff view with
// Accept/Reject per change → Apply as one undo step.

import { api } from "../api/client";
import type { ReviewMode, ReviewResult, Suggestion } from "../api/types";
import type { EditorPane } from "../editor/editor";
import type { AppState, Store } from "../state/store";
import { showMessage } from "../ui/dialog";
import { el } from "../ui/dom";
import { applyAccepted, type ReviewedRange } from "./apply";

const CONTEXT_CHARS = 2000;

const MODES: { mode: ReviewMode; label: string; description: string }[] = [
  { mode: "check", label: "Check", description: "Fix spelling, grammar and punctuation only." },
  { mode: "improve", label: "Improve", description: "Clearer wording and better flow, same meaning." },
  { mode: "shorten", label: "Shorten", description: "Say the same with fewer words." },
  { mode: "explain", label: "Explain", description: "No changes, just what could be better and why." },
];

export interface ReviewContext {
  store: Store<AppState>;
  editor: EditorPane;
}

/** Why a review cannot start right now, or null if it can. */
export function reviewBlocker(state: AppState): string | null {
  const ai = state.ai;
  if (ai === null) return "Checking whether Claude is available…";
  if (!ai.claude.available) return ai.claude.reason;
  if (ai.settings.claude_model === null) return "Choose a Claude model at the bottom right first.";
  return null;
}

function modal(title: string, className = ""): { dialog: HTMLDialogElement; done: Promise<void> } {
  const dialog = el("dialog", { class: `dialog ${className}` }, el("h2", {}, title));
  const done = new Promise<void>((resolve) =>
    dialog.addEventListener("close", () => {
      dialog.remove();
      resolve();
    }),
  );
  document.body.append(dialog);
  return { dialog, done };
}

function pickMode(model: string): Promise<ReviewMode | null> {
  const { dialog, done } = modal("Review with Claude", "mode-picker");
  let chosen: ReviewMode | null = null;
  const list = el("div", { class: "mode-list" });
  for (const { mode, label, description } of MODES) {
    const button = el(
      "button",
      { type: "button", class: "mode-option", "data-mode": mode },
      el("span", { class: "mode-label" }, label),
      el("span", { class: "mode-description" }, description),
    );
    button.addEventListener("click", () => {
      chosen = mode;
      dialog.close();
    });
    list.append(button);
  }
  const cancel = el("button", { type: "button", class: "button" }, "Cancel");
  cancel.addEventListener("click", () => dialog.close());
  dialog.append(
    el("p", { class: "dialog-hint" }, `Model: ${model}. Only the selected text is sent.`),
    list,
    el("div", { class: "dialog-buttons" }, cancel),
  );
  dialog.showModal();
  (list.firstElementChild as HTMLElement | null)?.focus();
  return done.then(() => chosen);
}

async function runWithProgress(model: string, run: (signal: AbortSignal) => Promise<ReviewResult>): Promise<ReviewResult | null> {
  const controller = new AbortController();
  const { dialog } = modal("Claude is reviewing…", "progress-dialog");
  const cancel = el("button", { type: "button", class: "button" }, "Cancel");
  cancel.addEventListener("click", () => controller.abort());
  dialog.addEventListener("cancel", () => controller.abort());
  dialog.append(
    el("div", { class: "progress-bar", role: "progressbar", "aria-label": "Waiting for Claude" }),
    el("p", { class: "dialog-hint" }, `${model} usually answers within a few seconds to a minute.`),
    el("div", { class: "dialog-buttons" }, cancel),
  );
  dialog.showModal();
  try {
    return await run(controller.signal);
  } catch (error: unknown) {
    if (controller.signal.aborted) return null;
    await showMessage("The review did not work", error instanceof Error ? error.message : String(error));
    return null;
  } finally {
    dialog.close();
  }
}

function changeRow(change: Suggestion, onToggle: () => void): { row: HTMLElement; accepted: () => boolean } {
  let accepted = true;
  const accept = el("button", { type: "button", class: "button small", "aria-pressed": "true" }, "Accept");
  const reject = el("button", { type: "button", class: "button small", "aria-pressed": "false" }, "Reject");
  const row = el(
    "li",
    { class: "change accepted", "data-change": change.id },
    el(
      "div",
      { class: "change-text" },
      el("del", {}, change.original),
      el("span", { class: "change-arrow", "aria-hidden": "true" }, "→"),
      el("ins", {}, change.replacement || "(remove)"),
    ),
    el("p", { class: "change-reason" }, change.reason),
    el("div", { class: "change-actions", role: "group", "aria-label": "Decision" }, accept, reject),
  );
  const set = (value: boolean): void => {
    accepted = value;
    accept.setAttribute("aria-pressed", String(value));
    reject.setAttribute("aria-pressed", String(!value));
    row.classList.toggle("accepted", value);
    row.classList.toggle("rejected", !value);
    onToggle();
  };
  accept.addEventListener("click", () => set(true));
  reject.addEventListener("click", () => set(false));
  return { row, accepted: () => accepted };
}

function showDiff(result: ReviewResult, reviewed: ReviewedRange, ctx: ReviewContext): void {
  const { dialog } = modal("Suggested changes", "diff-dialog");
  const apply = el("button", { type: "button", class: "button primary" }, "");
  const rows = result.changes.map((change) => changeRow(change, () => update()));
  const update = (): void => {
    const count = rows.filter((r) => r.accepted()).length;
    apply.textContent = count === 1 ? "Apply 1 change" : `Apply ${count} changes`;
    apply.disabled = count === 0;
  };
  const all = el("button", { type: "button", class: "button" }, "Accept all");
  all.addEventListener("click", () => {
    for (const row of rows) row.row.querySelector<HTMLButtonElement>("button")?.click();
  });
  const cancel = el("button", { type: "button", class: "button" }, "Discard");
  cancel.addEventListener("click", () => dialog.close());
  apply.addEventListener("click", () => {
    const accepted = result.changes.filter((_, i) => rows[i]?.accepted());
    const state = ctx.editor.activeState();
    const spec = state === null ? "Open the file again to apply the changes." : applyAccepted(state, ctx.store.get().active, reviewed, accepted);
    dialog.close();
    if (typeof spec === "string") void showMessage("Could not apply the changes", spec);
    else ctx.editor.apply(spec);
  });
  const note =
    result.dropped > 0
      ? el(
          "p",
          { class: "dialog-hint" },
          `${result.dropped} suggestion${result.dropped === 1 ? " was" : "s were"} left out: they would have changed Typst markup or did not match the text.`,
        )
      : null;
  dialog.append(el("ol", { class: "change-list" }, ...rows.map((r) => r.row)));
  if (note) dialog.append(note);
  dialog.append(el("div", { class: "dialog-buttons" }, cancel, all, apply));
  dialog.addEventListener("close", () => ctx.editor.focus());
  update();
  dialog.showModal();
  apply.focus();
}

export async function reviewSelection(ctx: ReviewContext): Promise<void> {
  const state = ctx.editor.activeState();
  const app = ctx.store.get();
  const blocker = reviewBlocker(app);
  if (blocker !== null) {
    await showMessage("Claude review is not available", blocker);
    return;
  }
  if (state === null || app.active === null) return;
  const { from, to } = state.selection.main;
  if (from === to) {
    await showMessage("Nothing selected", "Select the text Claude should review, then try again.");
    return;
  }
  const model = app.ai?.settings.claude_model ?? "";
  const mode = await pickMode(model);
  if (mode === null) {
    ctx.editor.focus();
    return;
  }
  const reviewed: ReviewedRange = { path: app.active, from, to, text: state.sliceDoc(from, to) };
  const result = await runWithProgress(model, (signal) =>
    api.review(
      {
        selection: reviewed.text,
        selection_start: from,
        context_before: state.sliceDoc(Math.max(0, from - CONTEXT_CHARS), from),
        context_after: state.sliceDoc(to, to + CONTEXT_CHARS),
        mode,
        language: app.language,
      },
      signal,
    ),
  );
  if (result === null) {
    ctx.editor.focus();
    return;
  }
  if (mode === "explain") {
    await showMessage("Claude's explanation", result.explanation || "Claude had nothing to add.");
  } else if (result.changes.length === 0) {
    const dropped = result.dropped > 0 ? ` (${result.dropped} unsafe suggestion${result.dropped === 1 ? " was" : "s were"} left out)` : "";
    await showMessage("No changes suggested", `Claude found nothing to change${dropped}.`);
  } else {
    showDiff(result, reviewed, ctx);
    return;
  }
  ctx.editor.focus();
}
