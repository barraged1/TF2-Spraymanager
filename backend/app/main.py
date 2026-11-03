"""FastAPI application: wires routes, error handling, and the static frontend."""
from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import (
    DEFAULT_SPRAY_FPS,
    MAX_EDGE_DXT1,
    MAX_EDGE_DXT5,
    MAX_VTF_BYTES,
    settings,
)
from .routes import library as library_routes
from .routes import media, spray
from .services import library
from .services.ingest import IngestError
from .services.jobs import JobError
from .services.library import LibraryError
from .services.storage import StorageError, cleanup_expired

log = logging.getLogger("tf2spray")

# Windows' registry-based MIME map often lacks .webp, which previews rely on.
mimetypes.add_type("image/webp", ".webp")

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    try:
        removed = cleanup_expired()
        if removed:
            log.info("Cleaned up %d expired job(s).", removed)
        library.purge_trash()
    except Exception:  # noqa: BLE001 - never block startup on cleanup
        log.warning("Job cleanup failed during startup.", exc_info=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="TF2 Spray EasyImport", version=__version__, lifespan=lifespan)

    # Map domain errors to clean 400/404 responses.
    @app.exception_handler(IngestError)
    async def _ingest_err(_: Request, exc: IngestError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(JobError)
    async def _job_err(_: Request, exc: JobError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(StorageError)
    async def _storage_err(_: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(LibraryError)
    async def _library_err(_: Request, exc: LibraryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/config")
    def config() -> dict:
        return {
            "max_upload_bytes": settings.max_upload_bytes,
            "max_vtf_bytes": MAX_VTF_BYTES,
            "url_import_enabled": settings.url_import_enabled,
            "default_spray_fps": DEFAULT_SPRAY_FPS,
            "max_edge_dxt1": MAX_EDGE_DXT1,
            "max_edge_dxt5": MAX_EDGE_DXT5,
        }

    app.include_router(media.router)
    app.include_router(spray.router)
    app.include_router(library_routes.router)

    if _FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()
