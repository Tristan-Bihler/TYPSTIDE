"""Planner data model, next-step logic and layout."""

from typing import Any

import pytest
from pydantic import ValidationError

from typst_writer.domain.planner import (
    COLUMN_WIDTH,
    ROW_HEIGHT,
    Plan,
    auto_layout,
    blocked,
    find_cycle,
    new_step_id,
    next_steps,
    topological_order,
)


def plan(*steps: dict[str, Any]) -> Plan:
    return Plan.model_validate({"title": "Arbeit", "steps": list(steps)})


def step(step_id: str, *deps: str, status: str = "todo", **more: object) -> dict[str, Any]:
    return {
        "id": step_id,
        "title": step_id.title(),
        "status": status,
        "depends_on": list(deps),
        **more,
    }


# --- validation ------------------------------------------------------------------------


def test_a_valid_plan_round_trips_through_json() -> None:
    original = plan(
        step("literatur", status="done", notes="Siehe *Knuth*."), step("gliederung", "literatur")
    )
    assert Plan.model_validate_json(original.model_dump_json()) == original
    assert original.step("gliederung") is not None
    assert original.step("nope") is None


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([step("a"), step("a")], "unique: a"),
        ([step("a", "b")], "unknown steps: b"),
        ([step("a", "a")], "cannot depend on itself"),
        ([step("a", "c"), step("b", "a"), step("c", "b")], "a → c → b → a"),
        ([step("a", "b", "b"), step("b")], "lists a step twice"),
    ],
)
def test_broken_dependencies_are_refused_with_a_reason(
    steps: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        plan(*steps)


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "Großbuchstaben"},
        {"id": "-start"},
        {"id": "x" * 41},
        {"title": ""},
        {"title": "   "},
        {"title": "zwei\nzeilen"},
        {"title": "t" * 201},
        {"status": "later"},
        {"notes": "n" * 20_001},
        {"x": 1e9},
        {"extra": 1},
    ],
)
def test_step_fields_are_checked(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        plan({**step("a"), **bad})


def test_plan_limits() -> None:
    with pytest.raises(ValidationError):
        Plan.model_validate({"title": "x", "steps": [step(f"s{i}") for i in range(501)]})
    with pytest.raises(ValidationError):
        Plan.model_validate({"title": "x", "version": 2, "steps": []})
    with pytest.raises(ValidationError):
        Plan.model_validate({"title": "x", "steps": [], "secret": True})


def test_find_cycle_without_a_cycle() -> None:
    assert find_cycle(plan(step("a"), step("b", "a")).steps) is None


# --- next steps ------------------------------------------------------------------------


def ids(steps: list[Any]) -> list[str]:
    return [s.id for s in steps]


def test_next_steps_of_an_empty_plan() -> None:
    assert next_steps(plan()) == []
    assert blocked(plan()) == []


def test_a_chain_frees_one_step_at_a_time() -> None:
    chain = plan(step("c", "b"), step("b", "a"), step("a"))
    assert ids(next_steps(chain)) == ["a"]
    assert [(s.id, waiting) for s, waiting in blocked(chain)] == [("c", ["b"]), ("b", ["a"])]
    chain = plan(step("c", "b"), step("b", "a"), step("a", status="done"))
    assert ids(next_steps(chain)) == ["b"]


def test_a_diamond_needs_both_sides_done() -> None:
    diamond = [step("start", status="done"), step("links", "start"), step("rechts", "start")]
    assert ids(next_steps(plan(*diamond, step("ende", "links", "rechts")))) == ["links", "rechts"]
    half = [
        step("start", status="done"),
        step("links", "start", status="done"),
        step("rechts", "start"),
    ]
    assert ids(next_steps(plan(*half, step("ende", "links", "rechts")))) == ["rechts"]


def test_steps_in_progress_come_first_then_dependency_order() -> None:
    p = plan(step("spaeter", "frueh"), step("frueh"), step("frei"), step("dran", status="doing"))
    assert ids(next_steps(p)) == ["dran", "frueh", "frei"]


def test_nothing_is_next_when_everything_is_done() -> None:
    p = plan(step("a", status="done"), step("b", "a", status="done"))
    assert next_steps(p) == [] and blocked(p) == []


def test_topological_order_keeps_file_order_where_free() -> None:
    p = plan(step("d", "b"), step("a"), step("b", "a"), step("c"))
    assert topological_order(p) == ["a", "c", "b", "d"]


# --- layout and ids ---------------------------------------------------------------


def test_auto_layout_places_only_steps_without_a_position() -> None:
    p = plan(step("a", x=500, y=40), step("b", "a"), step("c"), step("d", "b", "c"))
    placed = {s.id: (s.x, s.y) for s in auto_layout(p).steps}
    assert placed["a"] == (500, 40)  # kept
    assert placed["c"] == (0, ROW_HEIGHT)  # level 0, below "a"'s row
    assert placed["b"] == (COLUMN_WIDTH, 0)
    assert placed["d"] == (2 * COLUMN_WIDTH, 0)
    assert [s.id for s in auto_layout(p).steps] == ["a", "b", "c", "d"]  # file order kept
    complete = auto_layout(p)
    assert auto_layout(complete) is complete


def test_new_step_ids_come_from_titles() -> None:
    assert new_step_id("Literatur sichten (Teil 2)", set()) == "literatur-sichten-teil-2"
    assert new_step_id("Überblick über Größen", set()) == "ueberblick-ueber-groessen"
    assert new_step_id("???", set()) == "step"
    assert new_step_id("Test", {"test", "test-2"}) == "test-3"
    long = new_step_id("x" * 80, set())
    assert len(long) <= 34
    p = plan(step(new_step_id("Ä" * 50, set())))  # always a valid id
    assert p.steps[0].id
