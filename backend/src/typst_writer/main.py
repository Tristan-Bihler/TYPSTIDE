"""FastAPI app factory and server entry point."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from typst_writer.adapters.claude_cli import ClaudeCliProvider
from typst_writer.adapters.ollama import OllamaProvider
from typst_writer.adapters.typst_py import TypstPyCompiler, typst_version
from typst_writer.api import planner, rest, websocket
from typst_writer.api.deps import Services
from typst_writer.api.schemas import ErrorResponse
from typst_writer.config import SNIPPETS_PATH, AppConfig, load_config
from typst_writer.domain import errors
from typst_writer.domain.formatting import CannotFormatError
from typst_writer.infra.app_dirs import cache_dir, config_dir
from typst_writer.infra.state_store import StateStore
from typst_writer.ports.compiler import CompileFailedError
from typst_writer.services.compile import CompileService
from typst_writer.services.completion import CompletionService
from typst_writer.services.formatting import FormattingService
from typst_writer.services.grammar import GrammarService
from typst_writer.services.local_check import LocalAI
from typst_writer.services.planner import PlannerService
from typst_writer.services.review import ReviewService
from typst_writer.services.settings import SettingsService
from typst_writer.services.snippets import SnippetService
from typst_writer.services.workspace import WorkspaceService

# Never configurable: the app must only be reachable from this machine.
HOST = "127.0.0.1"
# Every changing request must carry this header. Browsers send a custom header cross-site
# only after a CORS preflight, which other origins fail: no web page can make the app act.
APP_HEADER = "X-Typst-Writer"
CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_STATUS: dict[type[errors.WorkspaceError], tuple[int, str]] = {
    errors.NoWorkspaceError: (409, "no_workspace"),
    errors.PathOutsideWorkspaceError: (403, "outside_workspace"),
    errors.EntryNotFoundError: (404, "not_found"),
    errors.EntryExistsError: (409, "exists"),
    errors.InvalidNameError: (422, "invalid_name"),
    errors.NotATextFileError: (415, "not_text"),
    errors.NoMainFileError: (409, "no_main"),
    errors.UnknownSnippetError: (404, "unknown_snippet"),
    errors.InvalidSnippetParamsError: (422, "invalid_params"),
    errors.AIUnavailableError: (409, "ai_unavailable"),
    errors.AIFailedError: (502, "ai_failed"),
    errors.TextTooLongError: (413, "too_long"),
    errors.CheckerUnavailableError: (409, "checker_unavailable"),
    CannotFormatError: (422, "cannot_format"),
    errors.PlannerDisabledError: (409, "planner_disabled"),
    errors.PlanConflictError: (409, "plan_conflict"),
    errors.PlanInvalidError: (422, "invalid_plan"),
}


async def _workspace_error(_request: Request, exc: Exception) -> JSONResponse:
    status, code = next(
        (v for cls, v in _STATUS.items() if isinstance(exc, cls)), (400, "workspace_error")
    )
    body = ErrorResponse(detail=str(exc), code=code)
    return JSONResponse(status_code=status, content=body.model_dump())


async def _compile_failed(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, CompileFailedError):
        raise TypeError(type(exc))
    body = ErrorResponse(detail=str(exc), code="compile_failed", problems=exc.problems)
    return JSONResponse(status_code=422, content=body.model_dump())


async def _require_app_header(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    changing = request.method in CHANGING_METHODS and request.url.path.startswith("/api/")
    if changing and request.headers.get(APP_HEADER) != "1":
        body = ErrorResponse(detail=f"Missing {APP_HEADER} header.", code="missing_header")
        return JSONResponse(status_code=403, content=body.model_dump())
    return await call_next(request)


def create_app(
    config: AppConfig, *, static_dir: Path | None = None, origin: str | None = None
) -> FastAPI:
    """The app. `static_dir`: serve the built frontend too (Windows app); `origin`: the
    page's origin then, instead of the Vite dev server's."""
    bundled = typst_version()
    if bundled != config.typst.version:
        raise RuntimeError(
            f"Typst {bundled} is installed but config.toml pins {config.typst.version}"
        )

    workspace = WorkspaceService(StateStore(config_dir() / "state.json"))
    workspace.restore_last()
    settings = SettingsService(config_dir() / "settings.json")
    hub = websocket.Hub(workspace)
    grammar = GrammarService(
        config, settings, lambda: str(workspace.guard.root) if workspace.info() else None
    )
    grammar.subscribe(hub.checker_status)
    completion = CompletionService(config, workspace)
    completion.subscribe(hub.completer_status)
    ollama = OllamaProvider(config.ollama)
    compile_service = CompileService(TypstPyCompiler(), cache_dir())
    services = Services(
        config=config,
        workspace=workspace,
        compile=compile_service,
        snippets=SnippetService(SNIPPETS_PATH),
        formatting=FormattingService(SNIPPETS_PATH),
        review=ReviewService(
            ClaudeCliProvider(config.claude.models, config.claude.timeout_seconds),
            ollama,
            settings,
            config.limits.max_ai_text_chars,
        ),
        settings=settings,
        grammar=grammar,
        completion=completion,
        local_ai=LocalAI(ollama, settings, config.ollama.max_paragraph_chars),
        planner=PlannerService(workspace, settings, compile_service),
        hub=hub,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await grammar.startup()  # starts LTeX+ in the background if installed
        yield
        await grammar.shutdown()
        await completion.shutdown()
        await ollama.close()

    app = FastAPI(
        title="typst-writer", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.services = services
    app.state.allowed_origins = {origin or f"http://{HOST}:{config.server.frontend_port}"}
    app.middleware("http")(_require_app_header)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(app.state.allowed_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", APP_HEADER],
    )
    # Blocks DNS-rebinding: a foreign domain resolving to 127.0.0.1 is still refused.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[HOST, "localhost"])
    app.add_exception_handler(errors.WorkspaceError, _workspace_error)
    app.add_exception_handler(CompileFailedError, _compile_failed)
    app.include_router(rest.router)
    app.include_router(planner.router)
    app.include_router(websocket.router)
    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


def app_factory() -> FastAPI:
    """Zero-argument factory for `uvicorn --factory` (used with `--reload` in development)."""
    return create_app(load_config())


def run() -> None:
    config = load_config()
    uvicorn.run(
        create_app(config),
        host=HOST,
        port=config.server.backend_port,
        ws_max_size=config.limits.max_ws_message_bytes,
    )


if __name__ == "__main__":
    run()
