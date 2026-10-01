"""Planner REST endpoints: switch, plan files, conflicts, paths, exports, notes."""

from pathlib import Path
from typing import Any

import pytest
from httpx import Response
from starlette.testclient import TestClient

from helpers import app_client

UI = {"theme": "system", "autosave": True, "autosave_delay_ms": 2000}


def enable(client: TestClient, on: bool = True) -> None:
    response = client.put(
        "/api/settings/ui", json={**UI, "preview_follows_cursor": True, "planner_enabled": on}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def planner(opened: TestClient) -> TestClient:
    enable(opened)
    return opened


def create(client: TestClient, title: str = "Bachelorarbeit") -> dict[str, Any]:
    response = client.post("/api/planner/plans", json={"title": title})
    assert response.status_code == 200, response.text
    document: dict[str, Any] = response.json()
    return document


def save(client: TestClient, document: dict[str, Any], **plan: object) -> Response:
    body = {"plan": {**document["plan"], **plan}, "base_revision": document["revision"]}
    response: Response = client.put(f"/api/planner/plans/{document['name']}", json=body)
    return response


STEPS: list[dict[str, Any]] = [
    {"id": "literatur", "title": "Literatur sichten", "status": "done"},
    {"id": "gliederung", "title": "Gliederung", "depends_on": ["literatur"]},
    {"id": "kapitel", "title": "Kapitel 1", "depends_on": ["gliederung"]},
]


def test_everything_is_refused_while_the_planner_is_off(opened: TestClient) -> None:
    calls = [
        opened.get("/api/planner/plans"),
        opened.post("/api/planner/plans", json={"title": "x"}),
        opened.get("/api/planner/plans/x"),
        opened.get("/api/planner/plans/x/next"),
        opened.post("/api/planner/plans/x/export", json={"kind": "typst"}),
        opened.delete("/api/planner/plans/x"),
        opened.post("/api/planner/render-note", json={"source": "Hallo"}),
    ]
    for response in calls:
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "planner_disabled"


def test_changes_need_the_app_header(planner: TestClient) -> None:
    with app_client() as bare:
        bare.headers.pop("X-Typst-Writer")
        assert bare.post("/api/planner/plans", json={"title": "x"}).status_code == 403
        assert bare.delete("/api/planner/plans/x").status_code == 403


def test_create_read_save_and_delete(planner: TestClient, workspace: Path) -> None:
    assert planner.get("/api/planner/plans").json() == []
    document = create(planner, "Bachelorarbeit (Übersicht)")
    assert document["name"] == "bachelorarbeit-uebersicht"
    assert document["path"] == "plans/bachelorarbeit-uebersicht.plan.json"
    assert document["plan"] == {"version": 1, "title": "Bachelorarbeit (Übersicht)", "steps": []}
    assert (workspace / "plans" / "bachelorarbeit-uebersicht.plan.json").is_file()
    assert create(planner, "Bachelorarbeit (Übersicht)")["name"] == "bachelorarbeit-uebersicht-2"

    response = save(planner, document, steps=STEPS)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision"] != document["revision"]
    assert [s["id"] for s in saved["plan"]["steps"]] == ["literatur", "gliederung", "kapitel"]
    assert all(s["x"] is not None for s in saved["plan"]["steps"])  # auto layout

    again = planner.get(f"/api/planner/plans/{document['name']}").json()
    assert again["revision"] == saved["revision"]
    listing = planner.get("/api/planner/plans").json()
    assert [(p["name"], p["steps"], p["done"]) for p in listing] == [
        ("bachelorarbeit-uebersicht", 3, 1),
        ("bachelorarbeit-uebersicht-2", 0, 0),
    ]

    nxt = planner.get(f"/api/planner/plans/{document['name']}/next").json()
    assert [s["id"] for s in nxt["next"]] == ["gliederung"]
    assert [(w["step"]["id"], w["waits_for"]) for w in nxt["waiting"]] == [
        ("kapitel", ["gliederung"])
    ]

    deleted = planner.delete(f"/api/planner/plans/{document['name']}")
    assert deleted.json() == {"path": "plans/bachelorarbeit-uebersicht.plan.json"}
    assert planner.get(f"/api/planner/plans/{document['name']}").status_code == 404


def test_a_save_based_on_an_old_revision_is_refused(planner: TestClient, workspace: Path) -> None:
    document = create(planner)
    assert save(planner, document, steps=STEPS[:1]).status_code == 200
    stale = save(planner, document, steps=[])  # still the first revision
    assert stale.status_code == 409
    assert stale.json()["code"] == "plan_conflict"
    on_disk = (workspace / "plans" / "bachelorarbeit.plan.json").read_text(encoding="utf-8")
    assert "literatur" in on_disk


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        ({"steps": [{"id": "a", "title": "A", "depends_on": ["a"]}]}, "cannot depend on itself"),
        (
            {
                "steps": [
                    {"id": "a", "title": "A", "depends_on": ["b"]},
                    {"id": "b", "title": "B", "depends_on": ["a"]},
                ]
            },
            "a → b → a",
        ),
        ({"steps": [{"id": "a", "title": ""}]}, "Step 1, title"),
        ({"title": "zwei\nzeilen"}, "single line"),
        ({"secret": 1}, "secret"),
    ],
)
def test_invalid_plans_are_refused_with_a_reason(
    planner: TestClient, plan: dict[str, Any], message: str
) -> None:
    response = save(planner, create(planner), **plan)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_plan"
    assert message in response.json()["detail"]


def test_an_invalid_file_is_listed_with_its_error(planner: TestClient, workspace: Path) -> None:
    (workspace / "plans").mkdir()
    (workspace / "plans" / "kaputt.plan.json").write_text("{not json", encoding="utf-8")
    (workspace / "plans" / "Fremd Name.plan.json").write_text("{}", encoding="utf-8")
    listing = planner.get("/api/planner/plans").json()
    assert [p["name"] for p in listing] == ["kaputt"]
    assert "not a valid plan" in listing[0]["error"]
    response = planner.get("/api/planner/plans/kaputt")
    assert response.status_code == 422 and response.json()["code"] == "invalid_plan"


@pytest.mark.parametrize(
    "name", ["..%2Fmain", "%2E%2E", "Main", "-x", "a.b", "a_b", "x" * 61, "%2Fetc%2Fpasswd"]
)
def test_bad_plan_names_are_refused(planner: TestClient, name: str) -> None:
    assert planner.get(f"/api/planner/plans/{name}").status_code in (404, 422)
    assert planner.delete(f"/api/planner/plans/{name}").status_code in (404, 405, 422)


def test_plans_never_leave_the_plans_folder(
    planner: TestClient, workspace: Path, tmp_path: Path
) -> None:
    (workspace / "plans").mkdir()
    outside = tmp_path / "outside.plan.json"
    outside.write_text('{"title": "Fremd"}', encoding="utf-8")
    (workspace / "plans" / "fremd.plan.json").symlink_to(outside)
    (workspace / "plans" / "haupt.plan.json").symlink_to(workspace / "main.typ")
    assert planner.get("/api/planner/plans/fremd").status_code == 403
    assert planner.get("/api/planner/plans/haupt").status_code == 422
    assert planner.delete("/api/planner/plans/haupt").status_code == 422
    assert (workspace / "main.typ").is_file()
    assert [p["name"] for p in planner.get("/api/planner/plans").json()] == ["fremd", "haupt"]
    assert all(p["error"] for p in planner.get("/api/planner/plans").json())


def test_a_plans_file_instead_of_a_folder(planner: TestClient, workspace: Path) -> None:
    (workspace / "plans").write_text("", encoding="utf-8")
    assert planner.get("/api/planner/plans").status_code == 422
    assert planner.post("/api/planner/plans", json={"title": "x"}).status_code == 422


def test_exports_are_written_and_regenerated_on_save(planner: TestClient, workspace: Path) -> None:
    document = create(planner)
    saved = save(planner, document, steps=STEPS).json()
    typst = planner.post("/api/planner/plans/bachelorarbeit/export", json={"kind": "typst"})
    assert typst.json() == {
        "path": "plans/bachelorarbeit.typ",
        "include": '#figure(include "/plans/bachelorarbeit.typ", caption: [Bachelorarbeit]) '
        "<fig:plan-bachelorarbeit>",
    }
    puml = planner.post("/api/planner/plans/bachelorarbeit/export", json={"kind": "plantuml"})
    assert puml.json() == {"path": "plans/bachelorarbeit.puml", "include": None}
    assert planner.get("/api/planner/plans/bachelorarbeit").json()["exports"] == [
        "typst",
        "plantuml",
    ]

    renamed = [{**STEPS[0], "title": "Quellen lesen"}, *STEPS[1:]]
    current = planner.get("/api/planner/plans/bachelorarbeit").json()
    assert current["revision"] == saved["revision"]
    assert save(planner, current, steps=renamed).status_code == 200
    assert "Quellen lesen" in (workspace / "plans" / "bachelorarbeit.typ").read_text("utf-8")
    assert "Quellen lesen" in (workspace / "plans" / "bachelorarbeit.puml").read_text("utf-8")

    # The figure compiles inside the document.
    main = workspace / "main.typ"
    main.write_text(main.read_text("utf-8") + "\n" + typst.json()["include"] + "\n", "utf-8")
    preview = planner.post("/api/export/pdf", json={"overlays": {}})
    assert preview.status_code == 200, preview.text


def test_a_foreign_file_is_only_replaced_after_confirmation(
    planner: TestClient, workspace: Path
) -> None:
    create(planner)
    mine = workspace / "plans" / "bachelorarbeit.typ"
    mine.write_text("= Meine Datei\n", encoding="utf-8")
    response = planner.post("/api/planner/plans/bachelorarbeit/export", json={"kind": "typst"})
    assert response.status_code == 409 and response.json()["code"] == "exists"
    assert mine.read_text("utf-8") == "= Meine Datei\n"
    assert planner.get("/api/planner/plans/bachelorarbeit").json()["exports"] == []
    confirmed = planner.post(
        "/api/planner/plans/bachelorarbeit/export", json={"kind": "typst", "overwrite": True}
    )
    assert confirmed.status_code == 200
    assert "Generated by the planner" in mine.read_text("utf-8")


def test_new_plans_avoid_existing_export_names(planner: TestClient, workspace: Path) -> None:
    (workspace / "plans").mkdir()
    (workspace / "plans" / "arbeit.typ").write_text("= Fremd\n", encoding="utf-8")
    assert create(planner, "Arbeit")["name"] == "arbeit-2"


def test_deleting_keeps_the_exports(planner: TestClient, workspace: Path) -> None:
    create(planner)
    planner.post("/api/planner/plans/bachelorarbeit/export", json={"kind": "typst"})
    planner.delete("/api/planner/plans/bachelorarbeit")
    assert (workspace / "plans" / "bachelorarbeit.typ").is_file()


def test_notes_render_without_touching_the_folder(planner: TestClient, workspace: Path) -> None:
    before = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*"))
    response = planner.post("/api/planner/render-note", json={"source": "*Wichtig:* $x^2$"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ok"] and len(result["pages"]) == 1
    assert result["pages"][0].startswith("<svg")
    after = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*"))
    assert after == before

    broken = planner.post("/api/planner/render-note", json={"source": "Zeile\n#unbekannt"})
    problems = broken.json()["problems"]
    assert not broken.json()["ok"]
    assert problems[0]["file"] == "" and problems[0]["line"] == 2

    too_long = planner.post("/api/planner/render-note", json={"source": "x" * 20_001})
    assert too_long.status_code == 422


def test_without_an_open_folder(client: TestClient) -> None:
    enable(client)
    assert client.get("/api/planner/plans").json()["code"] == "no_workspace"
