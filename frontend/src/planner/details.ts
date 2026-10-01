// Side panel for the selected step: title, status, what it waits for, notes in Typst
// (rendered below by the backend, shown as <img> like the preview) and Delete.

import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { syntaxHighlighting } from "@codemirror/language";
import { EditorState, Transaction, type Extension } from "@codemirror/state";
import { EditorView, keymap, placeholder } from "@codemirror/view";

import { api } from "../api/client";
import type { Plan, Step, StepStatus } from "../api/types";
import { typstHighlight, typstLanguage } from "../editor/typst";
import { confirmAction } from "../ui/dialog";
import { el } from "../ui/dom";
import { iconNode, icons } from "../ui/icons";
import { canDependOn, STATUS_LABELS } from "./model";

const TEXT_SAVE_MS = 600;
const RENDER_MS = 400;

export interface DetailsCallbacks {
  change(id: string, patch: Partial<Omit<Step, "id">>, delay?: number): void;
  toggleDependency(id: string, dependency: string): void;
  remove(id: string): void;
  close(): void;
}

let uniqueName = 0;

export class StepDetails {
  readonly element: HTMLElement;
  private step: Step | null = null;
  private readonly title: HTMLInputElement;
  private readonly statuses = new Map<StepStatus, HTMLInputElement>();
  private readonly dependencies: HTMLElement;
  private readonly notes: EditorView;
  private readonly noteExtensions: Extension[];
  private readonly rendered: HTMLElement;
  private readonly noteProblems: HTMLElement;
  private renderTimer = 0;
  private renderAbort: AbortController | null = null;
  private renderedSource: string | null = null;
  private urls: string[] = [];
  /** Set while the notes are replaced from the plan (not typed). */
  private applying = false;

  constructor(private readonly callbacks: DetailsCallbacks) {
    this.title = el("input", { type: "text", class: "text-input step-title", maxlength: "200", "aria-label": "Step title" });
    this.title.addEventListener("input", () => {
      const title = this.title.value.trim();
      if (this.step !== null && title !== "") this.callbacks.change(this.step.id, { title }, TEXT_SAVE_MS);
    });
    this.title.addEventListener("blur", () => {
      if (this.step !== null && this.title.value.trim() === "") this.title.value = this.step.title;
    });

    const group = `step-status-${++uniqueName}`;
    const status = el("div", { class: "segmented step-status", role: "radiogroup", "aria-label": "Status" });
    for (const value of ["todo", "doing", "done"] as const) {
      const input = el("input", { type: "radio", name: group, value });
      input.addEventListener("change", () => {
        if (this.step !== null && input.checked) this.callbacks.change(this.step.id, { status: value });
      });
      this.statuses.set(value, input);
      status.append(el("label", { class: "segment" }, input, el("span", {}, STATUS_LABELS[value])));
    }

    this.dependencies = el("div", { class: "step-dependencies", role: "group", "aria-label": "Waits for" });

    this.noteExtensions = [
      history(),
      typstLanguage,
      syntaxHighlighting(typstHighlight),
      EditorView.lineWrapping,
      placeholder("Notes, links, open questions… (Typst markup)"),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.contentAttributes.of({ "aria-label": "Notes", spellcheck: "true" }),
      EditorView.updateListener.of((update) => {
        if (!update.docChanged || this.step === null || this.applying) return;
        const notes = update.state.doc.toString();
        this.callbacks.change(this.step.id, { notes }, TEXT_SAVE_MS);
        this.scheduleRender(notes);
      }),
    ];
    this.notes = new EditorView({ state: EditorState.create({ extensions: this.noteExtensions }) });
    this.rendered = el("div", { class: "note-rendered", "aria-label": "Notes, rendered" });
    this.noteProblems = el("p", { class: "note-problems", role: "status" });

    const remove = el("button", { type: "button", class: "button step-delete" }, "Delete step");
    remove.addEventListener("click", () => void this.confirmRemove());
    const close = el("button", { type: "button", class: "tool icon-only", title: "Close the details", "aria-label": "Close the details" }, iconNode(icons.close));
    close.addEventListener("click", () => this.callbacks.close());

    const field = (label: string, control: HTMLElement): HTMLElement =>
      el("div", { class: "step-field" }, el("span", { class: "step-label" }, label), control);
    this.element = el(
      "aside",
      { class: "step-details", "aria-label": "Step details" },
      el("div", { class: "step-details-head" }, this.title, close),
      field("Status", status),
      field("Waits for", this.dependencies),
      field("Notes", el("div", { class: "step-notes" }, this.notes.dom)),
      this.rendered,
      this.noteProblems,
      el("div", { class: "step-details-foot" }, remove),
    );
    this.element.hidden = true;
  }

  /** Show `id` of `plan` (or hide); keeps whatever is being typed. */
  show(plan: Plan, id: string | null): void {
    const step = plan.steps.find((s) => s.id === id) ?? null;
    const switched = step?.id !== this.step?.id;
    this.step = step;
    this.element.hidden = step === null;
    if (step === null) return;
    if (switched || document.activeElement !== this.title) this.title.value = step.title;
    for (const [value, input] of this.statuses) input.checked = value === step.status;
    this.renderDependencies(plan, step);
    if (switched) {
      // A fresh state per step: undo never brings back another step's notes.
      this.notes.setState(EditorState.create({ doc: step.notes, extensions: this.noteExtensions }));
    } else if (!this.notes.hasFocus) {
      const current = this.notes.state.doc.toString();
      if (current !== step.notes) {
        this.applying = true;
        this.notes.dispatch({
          changes: { from: 0, to: current.length, insert: step.notes },
          annotations: Transaction.addToHistory.of(false),
        });
        this.applying = false;
      }
    }
    if (switched) {
      this.renderedSource = null;
      this.scheduleRender(step.notes, 0);
    }
  }

  focusTitle(): void {
    this.title.focus();
    this.title.select();
  }

  destroy(): void {
    window.clearTimeout(this.renderTimer);
    this.renderAbort?.abort();
    for (const url of this.urls) URL.revokeObjectURL(url);
    this.notes.destroy();
  }

  private renderDependencies(plan: Plan, step: Step): void {
    const others = plan.steps.filter((s) => s.id !== step.id);
    this.dependencies.replaceChildren();
    if (others.length === 0) {
      this.dependencies.append(el("p", { class: "step-hint" }, "No other steps yet."));
      return;
    }
    for (const other of others) {
      const box = el("input", { type: "checkbox" });
      box.checked = step.depends_on.includes(other.id);
      const allowed = box.checked || canDependOn(plan, step.id, other.id);
      box.disabled = !allowed;
      box.addEventListener("change", () => this.callbacks.toggleDependency(step.id, other.id));
      const label = el("label", { class: `step-dependency${allowed ? "" : " blocked"}` }, box, el("span", {}, other.title));
      if (!allowed) label.title = `“${other.title}” already waits for this step.`;
      if (other.status === "done") label.classList.add("done");
      this.dependencies.append(label);
    }
  }

  private async confirmRemove(): Promise<void> {
    const step = this.step;
    if (step === null) return;
    const ok = await confirmAction("Delete step?", `Delete “${step.title}” and its notes? Steps that wait for it no longer do.`, "Delete", "danger");
    if (ok) this.callbacks.remove(step.id);
  }

  // --- rendered notes ----------------------------------------------------------------

  private scheduleRender(source: string, delay = RENDER_MS): void {
    window.clearTimeout(this.renderTimer);
    this.renderTimer = window.setTimeout(() => void this.renderNotes(source), delay);
  }

  private async renderNotes(source: string): Promise<void> {
    if (source === this.renderedSource) return;
    this.renderAbort?.abort();
    if (source.trim() === "") {
      this.renderedSource = source;
      this.showPages([]);
      this.noteProblems.textContent = "";
      return;
    }
    const abort = new AbortController();
    this.renderAbort = abort;
    try {
      const result = await api.renderNote(source, abort.signal);
      if (abort.signal.aborted) return;
      this.renderedSource = source;
      const problem = result.problems.find((p) => p.severity === "error");
      // Keep the last good rendering while the notes have an error.
      if (result.ok) this.showPages(result.pages);
      this.noteProblems.textContent = problem === undefined ? "" : problem.line > 0 ? `Line ${problem.line}: ${problem.message}` : problem.message;
    } catch (error) {
      if (abort.signal.aborted) return;
      this.noteProblems.textContent = error instanceof Error ? error.message : String(error);
    }
  }

  private showPages(pages: string[]): void {
    for (const url of this.urls) URL.revokeObjectURL(url);
    this.urls = pages.map((svg) => URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" })));
    this.rendered.replaceChildren(...this.urls.map((url) => el("img", { src: url, alt: "Rendered notes", draggable: "false" })));
    this.rendered.hidden = pages.length === 0;
  }
}
