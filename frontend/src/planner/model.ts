// Pure plan operations (no DOM, no Cytoscape), mirroring backend/src/typst_writer/domain/planner.py.
// The backend validates every save; these keep the UI from offering what it would refuse.

import type { Plan, Step, StepStatus } from "../api/types";

export const STATUS_LABELS: Record<StepStatus, string> = {
  todo: "To do",
  doing: "In progress",
  done: "Done",
};

const PLAN_PATH = /^plans\/([a-z0-9][a-z0-9-]{0,59})\.plan\.json$/;
const COLUMN_WIDTH = 240;
const ROW_HEIGHT = 110;
const MAX_ID = 34;

/** "plans/arbeit.plan.json" -> "arbeit"; null for any other path. */
export function planName(path: string): string | null {
  return PLAN_PATH.exec(path)?.[1] ?? null;
}

const TRANSLITERATE: Record<string, string> = { ä: "ae", ö: "oe", ü: "ue", ß: "ss" };

/** Same rule as typst_text.slugify: 'Überblick (Teil 2)' -> 'ueberblick-teil-2'. */
export function slugify(text: string, maxLength: number): string {
  const ascii = text
    .toLowerCase()
    .replaceAll(/[äöüß]/g, (c) => TRANSLITERATE[c] ?? c)
    .normalize("NFKD")
    .replaceAll(/[^\x00-\x7f]/g, "");
  return ascii.replaceAll(/[^a-z0-9]+/g, "-").replaceAll(/^-+|-+$/g, "").slice(0, maxLength).replace(/-+$/, "");
}

/** A step id from its title, unique among `taken` ('test', 'test-2', …). */
export function newStepId(title: string, taken: Set<string>): string {
  const base = slugify(title, MAX_ID) || "step";
  let candidate = base;
  for (let n = 2; taken.has(candidate); n++) candidate = `${base}-${n}`;
  return candidate;
}

/** Ids of every step that depends on `id`, directly or through others. */
export function dependents(plan: Plan, id: string): Set<string> {
  const found = new Set<string>();
  const queue = [id];
  while (queue.length > 0) {
    const current = queue.pop() as string;
    for (const step of plan.steps) {
      if (step.depends_on.includes(current) && !found.has(step.id)) {
        found.add(step.id);
        queue.push(step.id);
      }
    }
  }
  return found;
}

/** Whether `step` may depend on `dependency` without creating a circle. */
export function canDependOn(plan: Plan, step: string, dependency: string): boolean {
  return step !== dependency && !dependents(plan, step).has(dependency);
}

export function updateStep(plan: Plan, id: string, patch: Partial<Omit<Step, "id">>): Plan {
  return { ...plan, steps: plan.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)) };
}

/** Add or remove "`step` depends on `dependency`". Null when it would create a circle. */
export function toggleDependency(plan: Plan, step: string, dependency: string): Plan | null {
  const target = plan.steps.find((s) => s.id === step);
  if (target === undefined) return null;
  if (target.depends_on.includes(dependency)) {
    return updateStep(plan, step, { depends_on: target.depends_on.filter((d) => d !== dependency) });
  }
  if (!canDependOn(plan, step, dependency)) return null;
  return updateStep(plan, step, { depends_on: [...target.depends_on, dependency] });
}

/** Where a new step goes: right of `after`, else below everything. */
export function newPosition(plan: Plan, after: Step | null): { x: number; y: number } {
  const placed = plan.steps.filter((s) => s.x !== null && s.y !== null);
  if (after?.x != null && after.y != null) {
    const x = after.x + COLUMN_WIDTH;
    let y = after.y;
    while (placed.some((s) => Math.abs((s.x as number) - x) < COLUMN_WIDTH / 2 && Math.abs((s.y as number) - y) < ROW_HEIGHT / 2)) {
      y += ROW_HEIGHT;
    }
    return { x, y };
  }
  if (placed.length === 0) return { x: 0, y: 0 };
  return { x: Math.min(...placed.map((s) => s.x as number)), y: Math.max(...placed.map((s) => s.y as number)) + ROW_HEIGHT };
}

/** Add a step titled `title`; with `after`, the new step depends on it. */
export function addStep(plan: Plan, title: string, after: Step | null): { plan: Plan; step: Step } {
  const id = newStepId(title, new Set(plan.steps.map((s) => s.id)));
  const step: Step = {
    id,
    title,
    status: "todo",
    notes: "",
    depends_on: after === null ? [] : [after.id],
    ...newPosition(plan, after),
  };
  return { plan: { ...plan, steps: [...plan.steps, step] }, step };
}

export function removeStep(plan: Plan, id: string): Plan {
  return {
    ...plan,
    steps: plan.steps.filter((s) => s.id !== id).map((s) => ({ ...s, depends_on: s.depends_on.filter((d) => d !== id) })),
  };
}

/** Step ids so that every step comes after its dependencies (file order otherwise). */
export function topologicalOrder(plan: Plan): string[] {
  const remaining = new Map(plan.steps.map((s) => [s.id, new Set(s.depends_on)]));
  const order: string[] = [];
  while (remaining.size > 0) {
    let ready = plan.steps.filter((s) => remaining.get(s.id)?.size === 0).map((s) => s.id);
    if (ready.length === 0) ready = [remaining.keys().next().value as string]; // only for a broken plan
    for (const id of ready) {
      remaining.delete(id);
      order.push(id);
      for (const waiting of remaining.values()) waiting.delete(id);
    }
  }
  return order;
}

/** What can be worked on now: not done, every dependency done; in progress first. */
export function nextSteps(plan: Plan): Step[] {
  const done = new Set(plan.steps.filter((s) => s.status === "done").map((s) => s.id));
  const rank = new Map(topologicalOrder(plan).map((id, i) => [id, i]));
  return plan.steps
    .filter((s) => s.status !== "done" && s.depends_on.every((d) => done.has(d)))
    .sort((a, b) => Number(a.status !== "doing") - Number(b.status !== "doing") || (rank.get(a.id) ?? 0) - (rank.get(b.id) ?? 0));
}

/** Steps that still wait, each with the steps it waits for. */
export function waiting(plan: Plan): { step: Step; waitsFor: Step[] }[] {
  const byId = new Map(plan.steps.map((s) => [s.id, s]));
  return plan.steps
    .filter((s) => s.status !== "done")
    .map((step) => ({
      step,
      waitsFor: step.depends_on.map((d) => byId.get(d)).filter((d): d is Step => d !== undefined && d.status !== "done"),
    }))
    .filter((w) => w.waitsFor.length > 0);
}

export interface NodeData {
  id: string;
  label: string;
  status: StepStatus;
}

export interface EdgeData {
  id: string;
  source: string;
  target: string;
}

/** Cytoscape elements: a node per step (at its position), an edge from each dependency. */
export function toElements(plan: Plan): { nodes: { data: NodeData; position: { x: number; y: number } }[]; edges: { data: EdgeData }[] } {
  return {
    nodes: plan.steps.map((s) => ({
      data: { id: s.id, label: s.status === "done" ? `✓ ${s.title}` : s.title, status: s.status },
      position: { x: s.x ?? 0, y: s.y ?? 0 },
    })),
    edges: plan.steps.flatMap((s) => s.depends_on.map((d) => ({ data: { id: `${d}->${s.id}`, source: d, target: s.id } }))),
  };
}

/** Positions from the canvas back into the plan (rounded to whole pixels). */
export function withPositions(plan: Plan, positions: Map<string, { x: number; y: number }>): Plan {
  return {
    ...plan,
    steps: plan.steps.map((s) => {
      const p = positions.get(s.id);
      return p === undefined ? s : { ...s, x: Math.round(p.x), y: Math.round(p.y) };
    }),
  };
}
