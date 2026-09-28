"""Request/response models shared by the REST and WebSocket endpoints."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    typst_version: str
