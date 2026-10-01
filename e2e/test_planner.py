"""The Planner extension in the browser: switch, plans, steps, Next, canvas, notes,
export and include, conflicts."""

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect

from e2e.ui_helpers import expand_folder

SAMPLE: dict[str, Any] = {
    "version": 1,
    "title": "Messreihe",
    "steps": [
        {"id": "aufbau", "title": "Aufbau", "status": "todo", "x": 0, "y": 0},
        {"id": "messen", "title": "Messen", "status": "todo", "x": 240, "y": 0},
    ],
}


def write_plan(workspace: Path, plan: dict[str, Any], page: Page, name: str = "messreihe") -> Path:
    """Write a plan file and reload, so the file tree shows it."""
    path = workspace / "plans" / f"{name}.plan.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(plan), encoding="utf-8")
    page.reload()
    page.locator(".page img").first.wait_for()
    return path


def read_plan(path: Path) -> dict[str, Any]:
    plan: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return plan


def turn_on(page: Page) -> None:
    page.keyboard.press("Control+,")
    dialog = page.locator("dialog.settings-dialog")
    dialog.get_by_role("checkbox", name="Planner").check()
    dialog.get_by_role("button", name="Done").click()
    expect(page.get_by_role("button", name="Plans")).to_be_visible()


def open_plan_from_tree(page: Page, name: str = "messreihe") -> None:
    expand_folder(page, "plans")
    page.get_by_role("treeitem", name=f"{name}.plan.json").click()
    expect(page.locator(".planner")).to_be_visible()


def node_point(page: Page, step_id: str) -> tuple[float, float]:
    """Screen position of a step's box (Cytoscape keeps its instance on the container)."""
    page.wait_for_function(
        "(id) => document.querySelector('.plan-canvas')?._cyreg?.cy.getElementById(id).nonempty()",
        arg=step_id,
    )
    point: dict[str, float] = page.evaluate(
        """(id) => {
            const host = document.querySelector('.plan-canvas');
            const p = host._cyreg.cy.getElementById(id).renderedPosition();
            const r = host.getBoundingClientRect();
            return { x: r.left + p.x, y: r.top + p.y };
        }""",
        step_id,
    )
    return point["x"], point["y"]


def test_planner_is_off_by_default(page: Page, workspace: Path) -> None:
    write_plan(workspace, SAMPLE, page)
    expect(page.get_by_role("button", name="Plans")).to_be_hidden()
    expand_folder(page, "plans")
    page.get_by_role("treeitem", name="messreihe.plan.json").click()
    expect(page.get_by_role("tab", name="messreihe.plan.json")).to_be_visible()
    expect(page.locator(".planner")).to_be_hidden()


def test_create_a_plan_add_steps_and_follow_next(page: Page, workspace: Path) -> None:
    turn_on(page)
    page.get_by_role("button", name="Plans").click()
    page.get_by_role("menuitem", name="New plan…").click()
    page.get_by_label("What is the task?").fill("Bachelorarbeit schreiben")
    page.get_by_role("button", name="Create plan").click()
    planner = page.locator(".planner")
    expect(planner.get_by_label("Plan title")).to_have_value("Bachelorarbeit schreiben")

    planner.get_by_role("button", name="Add the first step").click()
    page.locator("dialog").get_by_role("textbox").fill("Literatur sichten")
    page.locator("dialog").get_by_role("button", name="Add step").click()
    for title in ["Gliederung", "Messaufbau"]:  # each follows the selected (new) step
        planner.get_by_role("button", name="Add step").click()
        page.locator("dialog").get_by_role("textbox").fill(title)
        page.locator("dialog").get_by_role("button", name="Add step").click()
    details = page.locator(".step-details")
    expect(details.get_by_label("Step title")).to_have_value("Messaufbau")

    # Messaufbau waits for Literatur sichten instead of Gliederung.
    details.get_by_role("checkbox", name="Literatur sichten").check()
    details.get_by_role("checkbox", name="Gliederung").uncheck()
    # Literatur sichten cannot wait for Messaufbau: that would be a circle.
    details.get_by_role("button", name="Close the details").click()

    planner.locator(".segment", has_text="Next").click()
    next_list = planner.get_by_role("list", name="Can start now")
    expect(next_list.get_by_role("listitem")).to_have_count(1)
    expect(next_list).to_contain_text("Literatur sichten")
    waiting = planner.get_by_role("list", name="Waiting")
    expect(waiting.get_by_role("listitem")).to_have_count(2)

    next_list.get_by_role("button", name="Start").click()
    expect(next_list).to_contain_text("In progress")
    next_list.get_by_role("button", name="Mark done").click()
    expect(next_list.get_by_role("listitem")).to_have_count(2)
    expect(next_list).to_contain_text("Gliederung")
    expect(next_list).to_contain_text("Messaufbau")
    expect(planner).to_contain_text("1 step is done.")

    path = workspace / "plans" / "bachelorarbeit-schreiben.plan.json"
    page.wait_for_timeout(300)
    steps = {s["id"]: s for s in read_plan(path)["steps"]}
    assert steps["literatur-sichten"]["status"] == "done"
    assert steps["messaufbau"]["depends_on"] == ["literatur-sichten"]
    assert steps["gliederung"]["depends_on"] == ["literatur-sichten"]

    # A circle is not offered.
    planner.locator(".next-item", has_text="Gliederung").get_by_role("button").first.click()
    gliederung = page.locator(".step-details")
    expect(gliederung.get_by_role("checkbox", name="Literatur sichten")).to_be_checked()
    planner.locator(".segment", has_text="Canvas").click()
    planner.locator(".next-item").first.wait_for(state="hidden")


def test_drag_and_shift_click_on_the_canvas(page: Page, workspace: Path) -> None:
    path = write_plan(workspace, SAMPLE, page)
    turn_on(page)
    open_plan_from_tree(page)

    x, y = node_point(page, "messen")
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 40, y + 60, steps=8)
    page.mouse.up()
    page.wait_for_timeout(1200)  # saved 600 ms after the drag
    moved = {s["id"]: s for s in read_plan(path)["steps"]}["messen"]
    assert moved["y"] > 20

    ax, ay = node_point(page, "aufbau")
    mx, my = node_point(page, "messen")
    page.keyboard.down("Shift")
    page.mouse.click(ax, ay)
    page.mouse.click(mx, my)
    page.keyboard.up("Shift")
    page.wait_for_timeout(500)
    assert {s["id"]: s for s in read_plan(path)["steps"]}["messen"]["depends_on"] == ["aufbau"]

    # The other way round would be a circle.
    page.keyboard.down("Shift")
    page.mouse.click(mx, my)
    page.mouse.click(ax, ay)
    page.keyboard.up("Shift")
    expect(page.get_by_role("heading", name="That would make a circle")).to_be_visible()
    page.get_by_role("button", name="OK").click()


def test_notes_are_rendered_with_typst(page: Page, workspace: Path) -> None:
    write_plan(workspace, SAMPLE, page)
    turn_on(page)
    open_plan_from_tree(page)
    planner = page.locator(".planner")
    planner.locator(".segment", has_text="Next").click()
    planner.locator(".next-item", has_text="Aufbau").get_by_role("button", name="Aufbau").click()
    notes = page.locator(".step-details").get_by_label("Notes", exact=True)
    notes.click()
    page.keyboard.type("Waage mit $m = 1$ kg *kalibrieren*.")
    expect(page.locator(".note-rendered img")).to_be_visible()
    page.keyboard.type(" #unbekannt")
    expect(page.locator(".note-problems")).to_contain_text("Line 1")
    page.wait_for_timeout(800)
    steps = read_plan(workspace / "plans" / "messreihe.plan.json")["steps"]
    assert steps[0]["notes"] == "Waage mit $m = 1$ kg *kalibrieren*. #unbekannt"


def test_export_as_figure_and_include_it(page: Page, workspace: Path) -> None:
    write_plan(workspace, SAMPLE, page)
    turn_on(page)
    page.get_by_role("treeitem", name="main.typ").click()
    open_plan_from_tree(page)
    planner = page.locator(".planner")
    planner.get_by_role("button", name="Export", exact=True).click()
    page.get_by_role("menuitem", name="Typst figure (plans/messreihe.typ)").click()
    dialog = page.locator("dialog.include-dialog")
    expect(dialog).to_contain_text('#figure(include "/plans/messreihe.typ"')
    dialog.get_by_role("button", name="Insert into main.typ").click()

    expect(page.locator(".planner")).to_be_hidden()
    source = page.get_by_role("textbox", name="Document source")
    expect(source).to_contain_text("<fig:plan-messreihe>")
    expect(page.get_by_text("Compiled in")).to_be_visible()
    expect(page.locator(".problems")).to_contain_text("No problems")
    assert (workspace / "plans" / "messreihe.typ").is_file()

    # Changing the plan updates the included figure.
    open_plan_from_tree(page)
    planner.locator(".segment", has_text="Next").click()
    planner.locator(".next-item", has_text="Messen").get_by_role("button", name="Messen").click()
    title = page.locator(".step-details").get_by_label("Step title")
    title.fill("Messen und auswerten")
    page.wait_for_timeout(1200)
    assert "Messen und auswerten" in (workspace / "plans" / "messreihe.typ").read_text("utf-8")

    planner.get_by_role("button", name="Export", exact=True).click()
    page.get_by_role("menuitem", name="PlantUML diagram (plans/messreihe.puml)").click()
    expect(page.get_by_text("Saved plans/messreihe.puml")).to_be_visible()
    assert "@startuml" in (workspace / "plans" / "messreihe.puml").read_text("utf-8")


def test_a_change_made_elsewhere_is_not_overwritten(page: Page, workspace: Path) -> None:
    path = write_plan(workspace, SAMPLE, page)
    turn_on(page)
    open_plan_from_tree(page)
    path.write_text(json.dumps({**SAMPLE, "title": "Von außen geändert"}), encoding="utf-8")
    planner = page.locator(".planner")
    planner.locator(".segment", has_text="Next").click()
    planner.locator(".next-item", has_text="Aufbau").get_by_role("button", name="Start").click()
    expect(page.get_by_role("heading", name="The plan changed elsewhere")).to_be_visible()
    page.get_by_role("button", name="OK").click()
    expect(planner.get_by_label("Plan title")).to_have_value("Von außen geändert")
    assert read_plan(path)["title"] == "Von außen geändert"
    assert read_plan(path)["steps"][0]["status"] == "todo"


def test_turning_the_planner_off_closes_it(page: Page, workspace: Path) -> None:
    write_plan(workspace, SAMPLE, page)
    turn_on(page)
    open_plan_from_tree(page)
    page.keyboard.press("Control+,")
    dialog = page.locator("dialog.settings-dialog")
    dialog.get_by_role("checkbox", name="Planner").uncheck()
    dialog.get_by_role("button", name="Done").click()
    expect(page.locator(".planner")).to_be_hidden()
    expect(page.get_by_role("button", name="Plans")).to_be_hidden()
