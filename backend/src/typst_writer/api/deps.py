"""Service container shared by REST and WebSocket endpoints."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Depends, Request

from typst_writer.config import AppConfig
from typst_writer.services.compile import CompileService
from typst_writer.services.grammar import GrammarService
from typst_writer.services.local_check import LocalAI
from typst_writer.services.review import ReviewService
from typst_writer.services.snippets import SnippetService
from typst_writer.services.workspace import WorkspaceService

if TYPE_CHECKING:
    from typst_writer.api.websocket import Hub


@dataclass
class Services:
    config: AppConfig
    workspace: WorkspaceService
    compile: CompileService
    snippets: SnippetService
    review: ReviewService
    grammar: GrammarService
    local_ai: LocalAI
    hub: "Hub"


def get_services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


ServicesDep = Annotated[Services, Depends(get_services)]
