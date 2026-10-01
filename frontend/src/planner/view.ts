// The planner: replaces the editor while a plan is open (the preview stays visible).
// Every change is saved at once (drags after a short pause) together with the revision it
// was based on; if the plan changed elsewhere meanwhile, it is reloaded instead.

import { ApiError, api } from "../api/client";
import type { Plan, PlanDocument } from "../api/types";
import type { AppState, Store } from "../state/store";
import { promptText, showMessage } from "../ui/dialog";
import { el } from "../ui/dom";
import { iconNode, icons } from "../ui/icons";
import { PlanCanvas } from "./canvas";
import { addStep, toggleDependency, withPositions } from "./model";

const DRAG_SAVE_MS = 600;

export interface PlannerContext {
  store: Store<AppState>;
  host: HTMLElement;
  /** The planner closed itself (Close button, plan deleted). */
  onClosed(): void;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export class PlannerView {
  private doc: PlanDocument | null = null;
  /** The plan as shown; ahead of `doc.plan` while a change is being saved. */
  private plan: Plan | null = null;
  private selected: string | null = null;
  private dirty = false;
  private inFlight: Promise<void> | null = null;
  private saveTimer = 0;
  private readonly canvas: PlanCanvas;
  private readonly title: HTMLInputElement;
  private readonly summary: HTMLElement;
  private readonly empty: HTMLElement;
  private readonly unsubscribe: () => void;
  private readonly media = window.matchMedia("(prefers-color-scheme: dark)");
  private readonly restyle = (): void => {
    requestAnimationFrame(() => this.canvas.restyle());
  };
  private readonly resizeObserver: ResizeObserver;

  constructor(private readonly ctx: PlannerContext) {
    this.title = el("input", { type: "text", class: "plan-title", "aria-label": "Plan title", maxlength: "200", spellcheck: "false" });
    this.title.addEventListener("change", () => this.renameTo(this.title.value));
    this.title.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this.title.blur();
    });
    this.summary = el("span", { class: "plan-summary" });

    const add = el("button", { type: "button", class: "button primary", title: "Add a step after the selected one" }, "Add step");
    add.addEventListener("click", () => void this.addStep());
    const zoomOut = el("button", { type: "button", class: "tool icon-only", title: "Zoom out", "aria-label": "Zoom out" }, "−");
    zoomOut.addEventListener("click", () => this.canvas.zoomBy(1 / 1.25));
    const zoomIn = el("button", { type: "button", class: "tool icon-only", title: "Zoom in", "aria-label": "Zoom in" }, "+");
    zoomIn.addEventListener("click", () => this.canvas.zoomBy(1.25));
    const fit = el("button", { type: "button", class: "tool", title: "Show the whole plan" }, "Fit");
    fit.addEventListener("click", () => this.canvas.fit());
    const close = el("button", { type: "button", class: "tool icon-only", title: "Close the planner", "aria-label": "Close the planner" }, iconNode(icons.close));
    close.addEventListener("click", () => void this.close().then(() => this.ctx.onClosed()));

    const header = el(
      "div",
      { class: "planner-header" },
      el("div", { class: "planner-heading" }, this.title, this.summary),
      el("div", { class: "planner-tools" }, add, el("span", { class: "tool-divider", role: "presentation" }), zoomOut, zoomIn, fit, close),
    );

    const canvasHost = el("div", { class: "plan-canvas", "aria-label": "Plan canvas" });
    const addFirst = el("button", { type: "button", class: "button primary" }, "Add the first step");
    addFirst.addEventListener("click", () => void this.addStep());
    this.empty = el(
      "div",
      { class: "plan-empty" },
      el("p", {}, "Break the task into steps. Each step can wait for others; the arrows show what comes first."),
      addFirst,
    );
    const hint = el("p", { class: "plan-hint" }, "Drag to arrange. Shift-click a step, then another: the second waits for the first.");
    const stage = el("div", { class: "plan-stage" }, canvasHost, this.empty, hint);
    ctx.host.replaceChildren(header, el("div", { class: "planner-body" }, stage));

    this.canvas = new PlanCanvas(canvasHost, {
      onSelect: (id) => this.select(id),
      onMoved: (positions) => {
        if (this.plan !== null) this.change(withPositions(this.plan, positions), DRAG_SAVE_MS);
      },
      onLink: (from, to) => this.link(from, to),
    });
    this.resizeObserver = new ResizeObserver(() => this.canvas.resize());
    this.resizeObserver.observe(canvasHost);
    this.unsubscribe = ctx.store.subscribe((state, previous) => {
      if (state.ui.theme !== previous.ui.theme) this.restyle();
    });
    this.media.addEventListener("change", this.restyle);
  }

  get name(): string | null {
    return this.doc?.name ?? null;
  }

  async open(name: string): Promise<void> {
    await this.close();
    this.doc = await api.readPlan(name);
    this.plan = this.doc.plan;
    this.selected = null;
    this.render();
    this.canvas.fit();
  }

  /** The plan file may have changed elsewhere: reload it unless a change is pending. */
  async refresh(): Promise<void> {
    if (this.doc === null || this.dirty || this.inFlight !== null) return;
    const name = this.doc.name;
    try {
      const fresh = await api.readPlan(name);
      if (this.doc?.name !== name || this.dirty || this.inFlight !== null || fresh.revision === this.doc.revision) return;
      this.doc = fresh;
      this.plan = fresh.plan;
      if (this.selected !== null && !fresh.plan.steps.some((s) => s.id === this.selected)) this.selected = null;
      this.render();
    } catch {
      // Gone or invalid: saving will tell, and the list of plans shows why.
    }
  }

  /** Save what is pending and forget the plan. */
  async close(): Promise<void> {
    await this.flush();
    this.doc = null;
    this.plan = null;
    this.selected = null;
  }

  destroy(): void {
    window.clearTimeout(this.saveTimer);
    this.unsubscribe();
    this.media.removeEventListener("change", this.restyle);
    this.resizeObserver.disconnect();
    this.canvas.destroy();
  }

  // --- changes and saving ----------------------------------------------------------

  private change(plan: Plan, delay = 0): void {
    this.plan = plan;
    this.dirty = true;
    this.render();
    window.clearTimeout(this.saveTimer);
    this.saveTimer = window.setTimeout(() => void this.flush(), delay);
  }

  /** Save the shown plan if it changed (one request at a time). */
  async flush(): Promise<void> {
    window.clearTimeout(this.saveTimer);
    while (this.inFlight !== null) await this.inFlight;
    if (!this.dirty || this.doc === null || this.plan === null) return;
    const { name, revision } = this.doc;
    const sent = this.plan;
    this.dirty = false;
    this.inFlight = (async () => {
      try {
        const saved = await api.savePlan(name, sent, revision);
        if (this.doc?.name !== name) return;
        this.doc = saved;
        if (!this.dirty) {
          this.plan = saved.plan;
          this.render();
        }
      } catch (error) {
        await this.saveFailed(name, error);
      } finally {
        this.inFlight = null;
      }
    })();
    await this.inFlight;
  }

  private async saveFailed(name: string, error: unknown): Promise<void> {
    if (error instanceof ApiError && error.code === "not_found") {
      await showMessage("The plan is gone", `plans/${name}.plan.json was deleted or renamed, so the planner closes.`);
      this.doc = null;
      this.plan = null;
      this.ctx.onClosed();
      return;
    }
    if (error instanceof ApiError && (error.code === "plan_conflict" || error.code === "invalid_plan")) {
      this.dirty = false;
      try {
        await this.open(name);
      } catch {
        // shown below
      }
      await showMessage(error.code === "plan_conflict" ? "The plan changed elsewhere" : "The change was not saved", errorText(error));
      return;
    }
    this.dirty = true; // try again with the next change
    await showMessage("Could not save the plan", errorText(error));
  }

  // --- actions -----------------------------------------------------------------------

  private renameTo(raw: string): void {
    const title = raw.trim();
    if (this.plan === null) return;
    if (title === "" || title === this.plan.title) {
      this.title.value = this.plan.title;
      return;
    }
    this.change({ ...this.plan, title });
  }

  private select(id: string | null): void {
    this.selected = id;
    this.canvas.select(id);
  }

  private async addStep(): Promise<void> {
    if (this.plan === null) return;
    const after = this.plan.steps.find((s) => s.id === this.selected) ?? null;
    const title = await promptText({
      title: "New step",
      label: after === null ? "What needs to be done?" : `What comes after “${after.title}”?`,
      value: "",
      confirmLabel: "Add step",
      validate: (value) => (value === "" ? "Give the step a title." : value.length > 200 ? "At most 200 characters." : null),
    });
    if (title === null || this.plan === null) return;
    const { plan, step } = addStep(this.plan, title, after);
    this.selected = step.id;
    this.change(plan);
    this.canvas.reveal(step.id);
  }

  private link(from: string, to: string): void {
    if (this.plan === null) return;
    const next = toggleDependency(this.plan, to, from);
    if (next === null) {
      const name = (id: string): string => this.plan?.steps.find((s) => s.id === id)?.title ?? id;
      void showMessage("That would make a circle", `“${name(from)}” already waits for “${name(to)}”, so “${name(to)}” cannot wait for it.`);
      return;
    }
    this.change(next);
  }

  // --- rendering ---------------------------------------------------------------------

  private render(): void {
    const plan = this.plan;
    if (plan === null || this.doc === null) return;
    if (document.activeElement !== this.title) this.title.value = plan.title;
    const done = plan.steps.filter((s) => s.status === "done").length;
    this.summary.textContent = plan.steps.length === 0 ? "No steps yet" : `${done}/${plan.steps.length} done`;
    this.summary.title = this.doc.path;
    this.empty.hidden = plan.steps.length > 0;
    this.canvas.render(plan, this.selected);
  }
}
