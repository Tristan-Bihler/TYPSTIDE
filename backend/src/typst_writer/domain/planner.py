"""Planner: a task broken into steps with dependencies (`plans/<name>.plan.json`).

The plan is validated as a whole: step ids are unique, dependencies refer to existing
steps, never to the step itself, and never form a cycle (a cycle is reported as a
readable path). `next_steps` lists what can be worked on now: steps not done whose
dependencies are all done.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from typst_writer.domain.typst_text import slugify

Status = Literal["todo", "doing", "done"]
STEP_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,39}$"
MAX_STEPS = 500
MAX_NOTES = 20_000
MAX_COORDINATE = 1_000_000.0
COLUMN_WIDTH = 240.0  # canvas pixels between dependency levels (auto layout)
ROW_HEIGHT = 110.0


def _one_line(value: str) -> str:
    value = value.strip()
    if any(c in value for c in "\r\n\t"):
        raise ValueError("must be a single line")
    return value


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=STEP_ID_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    status: Status = "todo"
    notes: str = Field(default="", max_length=MAX_NOTES)  # Typst markup
    depends_on: list[str] = Field(default_factory=list, max_length=MAX_STEPS)
    x: float | None = Field(default=None, ge=-MAX_COORDINATE, le=MAX_COORDINATE)
    y: float | None = Field(default=None, ge=-MAX_COORDINATE, le=MAX_COORDINATE)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = _one_line(value)
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("depends_on")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("lists a step twice")
        return value


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=200)
    steps: list[Step] = Field(default_factory=list, max_length=MAX_STEPS)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = _one_line(value)
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _graph(self) -> "Plan":
        ids = [s.id for s in self.steps]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"Step ids must be unique: {', '.join(duplicates)}.")
        known = set(ids)
        for step in self.steps:
            if step.id in step.depends_on:
                raise ValueError(f"Step '{step.id}' cannot depend on itself.")
            unknown = [d for d in step.depends_on if d not in known]
            if unknown:
                raise ValueError(
                    f"Step '{step.id}' depends on unknown steps: {', '.join(unknown)}."
                )
        cycle = find_cycle(self.steps)
        if cycle is not None:
            raise ValueError(f"These steps depend on each other in a circle: {' → '.join(cycle)}.")
        return self

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)


def find_cycle(steps: list[Step]) -> list[str] | None:
    """A dependency cycle as a path (`a → b → a`), or None."""
    depends = {s.id: s.depends_on for s in steps}
    state: dict[str, int] = {}  # 1 = on the current path, 2 = finished
    path: list[str] = []

    def visit(step_id: str) -> list[str] | None:
        state[step_id] = 1
        path.append(step_id)
        for dependency in depends.get(step_id, []):
            if state.get(dependency) == 1:
                return [*path[path.index(dependency) :], dependency]
            if dependency in depends and state.get(dependency) is None:
                found = visit(dependency)
                if found is not None:
                    return found
        path.pop()
        state[step_id] = 2
        return None

    for step in steps:
        if state.get(step.id) is None:
            found = visit(step.id)
            if found is not None:
                return found
    return None


def topological_order(plan: Plan) -> list[str]:
    """Step ids so that every step comes after its dependencies (file order otherwise)."""
    remaining = {s.id: set(s.depends_on) for s in plan.steps}
    order: list[str] = []
    while remaining:
        ready = [s.id for s in plan.steps if s.id in remaining and not remaining[s.id]]
        if not ready:  # only possible for an unvalidated plan with a cycle
            ready = [next(iter(remaining))]
        for step_id in ready:
            del remaining[step_id]
            order.append(step_id)
            for waiting in remaining.values():
                waiting.discard(step_id)
    return order


def next_steps(plan: Plan) -> list[Step]:
    """Steps that can be worked on now: not done, every dependency done. Steps already
    in progress come first, then the rest in dependency order."""
    done = {s.id for s in plan.steps if s.status == "done"}
    rank = {step_id: i for i, step_id in enumerate(topological_order(plan))}
    free = [s for s in plan.steps if s.status != "done" and all(d in done for d in s.depends_on)]
    return sorted(free, key=lambda s: (s.status != "doing", rank[s.id]))


def blocked(plan: Plan) -> list[tuple[Step, list[str]]]:
    """Steps that still wait, each with the ids of the steps it waits for."""
    done = {s.id for s in plan.steps if s.status == "done"}
    waiting = []
    for step in plan.steps:
        open_dependencies = [d for d in step.depends_on if d not in done]
        if step.status != "done" and open_dependencies:
            waiting.append((step, open_dependencies))
    return waiting


def depth(plan: Plan) -> dict[str, int]:
    """Dependency level of every step: 0 without dependencies, else 1 + the deepest."""
    levels: dict[str, int] = {}
    by_id = {s.id: s for s in plan.steps}
    for step_id in topological_order(plan):
        dependencies = by_id[step_id].depends_on
        levels[step_id] = 1 + max((levels[d] for d in dependencies), default=-1)
    return levels


def auto_layout(plan: Plan) -> Plan:
    """Give steps without a position one: a column per dependency level, stacked below
    the steps already in that column."""
    if all(s.x is not None and s.y is not None for s in plan.steps):
        return plan
    levels = depth(plan)
    used: dict[int, int] = {}
    for step in plan.steps:
        if step.x is not None and step.y is not None:
            column = levels[step.id]
            used[column] = max(used.get(column, 0), int(step.y // ROW_HEIGHT) + 1)
    steps = []
    order = {step_id: i for i, step_id in enumerate(topological_order(plan))}
    for step in sorted(plan.steps, key=lambda s: order[s.id]):
        if step.x is None or step.y is None:
            column = levels[step.id]
            row = used.get(column, 0)
            used[column] = row + 1
            step = step.model_copy(update={"x": column * COLUMN_WIDTH, "y": row * ROW_HEIGHT})
        steps.append(step)
    by_id = {s.id: s for s in steps}
    return plan.model_copy(update={"steps": [by_id[s.id] for s in plan.steps]})


def new_step_id(title: str, taken: set[str]) -> str:
    """'Literatur sichten (Teil 2)' -> 'literatur-sichten-teil-2', unique among `taken`."""
    base = slugify(title, max_length=34) or "step"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate
