"""REST endpoints of the Planner extension under `/api/planner`.

All of them answer 409 `planner_disabled` while the extension is turned off.
"""

from typing import Annotated

from fastapi import APIRouter
from fastapi import Path as PathParam
from pydantic import BaseModel, ConfigDict, Field

from typst_writer.api.deps import ServicesDep
from typst_writer.api.schemas import EntryPath
from typst_writer.domain.models import CompileResult
from typst_writer.domain.planner import MAX_NOTES
from typst_writer.services.planner import (
    PLAN_NAME_PATTERN,
    ExportKind,
    ExportResult,
    NextView,
    PlanDocument,
    PlanSummary,
)

router = APIRouter(prefix="/api/planner")

PlanName = Annotated[str, PathParam(pattern=PLAN_NAME_PATTERN)]


class CreatePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)


class SavePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: dict[str, object]  # validated by the service, for a readable message
    base_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExportPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ExportKind
    overwrite: bool = False  # replace a file of that name the planner did not generate


class RenderNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(max_length=MAX_NOTES)


@router.get("/plans")
async def list_plans(s: ServicesDep) -> list[PlanSummary]:
    return s.planner.list_plans()


@router.post("/plans")
async def create_plan(body: CreatePlanRequest, s: ServicesDep) -> PlanDocument:
    document = s.planner.create(body.title)
    await s.hub.workspace_changed()
    return document


@router.get("/plans/{name}")
async def read_plan(name: PlanName, s: ServicesDep) -> PlanDocument:
    return s.planner.read(name)


@router.put("/plans/{name}")
async def save_plan(name: PlanName, body: SavePlanRequest, s: ServicesDep) -> PlanDocument:
    document = s.planner.save(name, body.plan, body.base_revision)
    await s.hub.workspace_changed()  # regenerated exports change the preview
    return document


@router.delete("/plans/{name}")
async def delete_plan(name: PlanName, s: ServicesDep) -> EntryPath:
    path = s.planner.delete(name)
    await s.hub.workspace_changed()
    return EntryPath(path=path)


@router.post("/plans/{name}/export")
async def export_plan(name: PlanName, body: ExportPlanRequest, s: ServicesDep) -> ExportResult:
    result = s.planner.export(name, body.kind, body.overwrite)
    await s.hub.workspace_changed()
    return result


@router.get("/plans/{name}/next")
async def next_steps(name: PlanName, s: ServicesDep) -> NextView:
    return s.planner.next(name)


@router.post("/render-note")
async def render_note(body: RenderNoteRequest, s: ServicesDep) -> CompileResult:
    return await s.planner.render_note(body.source)
