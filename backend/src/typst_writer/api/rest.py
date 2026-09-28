"""REST endpoints under `/api`."""

from fastapi import APIRouter

from typst_writer.adapters.typst_py import typst_version
from typst_writer.api.schemas import HealthResponse

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", typst_version=typst_version())
