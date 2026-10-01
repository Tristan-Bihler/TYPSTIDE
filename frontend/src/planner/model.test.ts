import { describe, expect, it } from "vitest";

import type { Plan, Step } from "../api/types";
import {
  addStep,
  canDependOn,
  newStepId,
  nextSteps,
  planName,
  removeStep,
  toElements,
  toggleDependency,
  topologicalOrder,
  waiting,
  withPositions,
} from "./model";

function step(id: string, dependsOn: string[] = [], status: Step["status"] = "todo", x: number | null = null, y: number | null = null): Step {
  return { id, title: id.toUpperCase(), status, notes: "", depends_on: dependsOn, x, y };
}

function plan(...steps: Step[]): Plan {
  return { version: 1, title: "Arbeit", steps };
}

const ids = (steps: Step[]): string[] => steps.map((s) => s.id);

describe("plan names and step ids", () => {
  it("recognises plan files only in the plans folder", () => {
    expect(planName("plans/arbeit.plan.json")).toBe("arbeit");
    expect(planName("plans/a-2.plan.json")).toBe("a-2");
    expect(planName("other/arbeit.plan.json")).toBeNull();
    expect(planName("plans/sub/arbeit.plan.json")).toBeNull();
    expect(planName("plans/Arbeit.plan.json")).toBeNull();
    expect(planName("plans/arbeit.json")).toBeNull();
  });

  it("makes ids like the backend", () => {
    expect(newStepId("Literatur sichten (Teil 2)", new Set())).toBe("literatur-sichten-teil-2");
    expect(newStepId("Überblick über Größen", new Set())).toBe("ueberblick-ueber-groessen");
    expect(newStepId("Café", new Set())).toBe("cafe");
    expect(newStepId("???", new Set())).toBe("step");
    expect(newStepId("Test", new Set(["test", "test-2"]))).toBe("test-3");
    const long = newStepId("x".repeat(80), new Set());
    expect(long.length).toBeLessThanOrEqual(34);
    expect(long).toMatch(/^[a-z0-9][a-z0-9-]{0,39}$/);
  });
});

describe("dependencies", () => {
  it("refuses circles", () => {
    const chain = plan(step("a"), step("b", ["a"]), step("c", ["b"]));
    expect(canDependOn(chain, "a", "c")).toBe(false);
    expect(canDependOn(chain, "a", "a")).toBe(false);
    expect(canDependOn(chain, "c", "a")).toBe(true);
    expect(toggleDependency(chain, "a", "c")).toBeNull();
  });

  it("adds and removes a dependency", () => {
    const p = plan(step("a"), step("b"));
    const linked = toggleDependency(p, "b", "a");
    expect(linked?.steps[1]?.depends_on).toEqual(["a"]);
    expect(toggleDependency(linked as Plan, "b", "a")?.steps[1]?.depends_on).toEqual([]);
  });

  it("removing a step frees the steps that waited for it", () => {
    const p = removeStep(plan(step("a"), step("b", ["a"])), "a");
    expect(p.steps).toEqual([step("b")]);
  });
});

describe("next steps", () => {
  it("an empty plan has nothing next", () => {
    expect(nextSteps(plan())).toEqual([]);
    expect(waiting(plan())).toEqual([]);
  });

  it("a chain frees one step at a time", () => {
    const chain = plan(step("c", ["b"]), step("b", ["a"]), step("a"));
    expect(ids(nextSteps(chain))).toEqual(["a"]);
    expect(waiting(chain).map((w) => [w.step.id, ids(w.waitsFor)])).toEqual([
      ["c", ["b"]],
      ["b", ["a"]],
    ]);
    const after = plan(step("c", ["b"]), step("b", ["a"]), step("a", [], "done"));
    expect(ids(nextSteps(after))).toEqual(["b"]);
  });

  it("a diamond needs both sides done; in progress comes first", () => {
    const diamond = plan(step("start", [], "done"), step("links", ["start"]), step("rechts", ["start"], "doing"), step("ende", ["links", "rechts"]));
    expect(ids(nextSteps(diamond))).toEqual(["rechts", "links"]);
    expect(waiting(diamond).map((w) => ids(w.waitsFor))).toEqual([["links", "rechts"]]);
  });

  it("orders free steps by dependencies, then file order", () => {
    const p = plan(step("d", ["b"]), step("a"), step("b", ["a"]), step("c"));
    expect(topologicalOrder(p)).toEqual(["a", "c", "b", "d"]);
  });

  it("nothing is next when everything is done", () => {
    const p = plan(step("a", [], "done"), step("b", ["a"], "done"));
    expect(nextSteps(p)).toEqual([]);
    expect(waiting(p)).toEqual([]);
  });
});

describe("canvas mapping", () => {
  it("maps steps to nodes and dependencies to edges", () => {
    const p = plan(step("a", [], "done", 0, 0), step("b", ["a"], "doing", 240, 0));
    const { nodes, edges } = toElements(p);
    expect(nodes).toEqual([
      { data: { id: "a", label: "✓ A", status: "done" }, position: { x: 0, y: 0 } },
      { data: { id: "b", label: "B", status: "doing" }, position: { x: 240, y: 0 } },
    ]);
    expect(edges).toEqual([{ data: { id: "a->b", source: "a", target: "b" } }]);
  });

  it("takes rounded positions back from the canvas", () => {
    const p = withPositions(plan(step("a", [], "todo", 0, 0), step("b")), new Map([["a", { x: 10.4, y: -3.6 }]]));
    expect(p.steps.map((s) => [s.x, s.y])).toEqual([
      [10, -4],
      [null, null],
    ]);
  });

  it("puts a new step right of the one it follows, avoiding overlaps", () => {
    const p = plan(step("a", [], "todo", 0, 0), step("b", [], "todo", 240, 0));
    const { plan: next, step: added } = addStep(p, "Neu", p.steps[0] as Step);
    expect(added).toMatchObject({ id: "neu", depends_on: ["a"], x: 240, y: 110 });
    expect(next.steps).toHaveLength(3);
    const free = addStep(p, "Frei", null).step;
    expect(free).toMatchObject({ depends_on: [], x: 0, y: 110 });
    expect(addStep(plan(), "Erster", null).step).toMatchObject({ x: 0, y: 0 });
  });
});
