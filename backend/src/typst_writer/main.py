"""FastAPI app factory and server entry point."""

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from typst_writer.adapters.typst_py import TypstPyCompiler, typst_version
from typst_writer.api import rest, websocket
from typst_writer.api.deps import Services
from typst_writer.api.schemas import ErrorResponse
from typst_writer.config import AppConfig, load_config
from typst_writer.domain import errors
from typst_writer.infra.app_dirs import cache_dir, config_dir
from typst_writer.infra.state_store import StateStore
from typst_writer.ports.compiler import CompileFailedError
from typst_writer.services.compile import CompileService
from typst_writer.services.workspace import WorkspaceService

# Never configurable: the app must only be reachable from this machine.
HOST = "127.0.0.1"

_STATUS: dict[type[errors.WorkspaceError], tuple[int, str]] = {
    errors.NoWorkspaceError: (409, "no_workspace"),
    errors.PathOutsideWorkspaceError: (403, "outside_workspace"),
    errors.EntryNotFoundError: (404, "not_found"),
    errors.EntryExistsError: (409, "exists"),
    errors.InvalidNameError: (422, "invalid_name"),
    errors.NotATextFileError: (415, "not_text"),
    errors.NoMainFileError: (409, "no_main"),
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


def create_app(config: AppConfig) -> FastAPI:
    bundled = typst_version()
    if bundled != config.typst.version:
        raise RuntimeError(
            f"Typst {bundled} is installed but config.toml pins {config.typst.version}"
        )

    workspace = WorkspaceService(StateStore(config_dir() / "state.json"))
    workspace.restore_last()
    services = Services(
        config=config,
        workspace=workspace,
        compile=CompileService(TypstPyCompiler(), cache_dir()),
        hub=websocket.Hub(workspace),
    )

    app = FastAPI(title="typst-writer", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = services
    app.state.allowed_origins = {f"http://{HOST}:{config.server.frontend_port}"}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(app.state.allowed_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    # Blocks DNS-rebinding: a foreign domain resolving to 127.0.0.1 is still refused.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[HOST, "localhost"])
    app.add_exception_handler(errors.WorkspaceError, _workspace_error)
    app.add_exception_handler(CompileFailedError, _compile_failed)
    app.include_router(rest.router)
    app.include_router(websocket.router)
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
