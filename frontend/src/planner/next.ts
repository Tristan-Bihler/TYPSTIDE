// "Next" view: what can be worked on now (in progress first), then what still waits.

import type { Plan, StepStatus } from "../api/types";
import { el } from "../ui/dom";
import { nextSteps, STATUS_LABELS, waiting } from "./model";

export interface NextCallbacks {
  select(id: string): void;
  setStatus(id: string, status: StepStatus): void;
}

export function renderNext(host: HTMLElement, plan: Plan, selected: string | null, callbacks: NextCallbacks): void {
  const now = nextSteps(plan);
  const later = waiting(plan);
  const done = plan.steps.filter((s) => s.status === "done").length;

  const item = (id: string, title: string, extra: HTMLElement[]): HTMLElement => {
    const open = el("button", { type: "button", class: "next-title", title: "Show the details" }, title);
    open.addEventListener("click", () => callbacks.select(id));
    return el("li", { class: `next-item${id === selected ? " selected" : ""}`, "data-step": id }, open, ...extra);
  };
  const action = (id: string, label: string, status: StepStatus): HTMLElement => {
    const button = el("button", { type: "button", class: "button" }, label);
    button.addEventListener("click", () => callbacks.setStatus(id, status));
    return button;
  };

  const nowList = el("ol", { class: "next-list", "aria-label": "Can start now" });
  for (const step of now) {
    const extra = [
      el("span", { class: `next-status ${step.status}` }, STATUS_LABELS[step.status]),
      step.status === "doing" ? action(step.id, "Mark done", "done") : action(step.id, "Start", "doing"),
    ];
    nowList.append(item(step.id, step.title, extra));
  }
  const laterList = el("ul", { class: "next-list waiting", "aria-label": "Waiting" });
  for (const { step, waitsFor } of later) {
    const reason = el("span", { class: "next-waits" }, `Waits for ${waitsFor.map((s) => `“${s.title}”`).join(", ")}`);
    laterList.append(item(step.id, step.title, [reason]));
  }

  const nowEmpty =
    plan.steps.length === 0 ? "No steps yet. Add the first one." : done === plan.steps.length ? "Every step is done." : "Nothing can start: every open step waits for another.";
  host.replaceChildren(
    el("h3", { class: "next-heading" }, "Can start now"),
    now.length > 0 ? nowList : el("p", { class: "next-empty" }, nowEmpty),
  );
  if (later.length > 0) host.append(el("h3", { class: "next-heading" }, "Waiting"), laterList);
  if (done > 0) host.append(el("p", { class: "next-done" }, done === 1 ? "1 step is done." : `${done} steps are done.`));
}
