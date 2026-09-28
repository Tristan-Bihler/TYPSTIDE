"""FastAPI app factory and server entry point."""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from typst_writer.adapters.typst_py import typst_version
from typst_writer.api import rest
from typst_writer.config import AppConfig, load_config

# Never configurable: the app must only be reachable from this machine.
HOST = "127.0.0.1"


def create_app(config: AppConfig) -> FastAPI:
    bundled = typst_version()
    if bundled != config.typst.version:
        raise RuntimeError(
            f"Typst {bundled} is installed but config.toml pins {config.typst.version}"
        )

    app = FastAPI(title="typst-writer", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://{HOST}:{config.server.frontend_port}"],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(rest.router)
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
