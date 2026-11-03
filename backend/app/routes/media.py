"""Routes for importing media and serving job files/frames."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from ..models import ImportResponse, UrlImportRequest
from ..services import ingest, jobs, storage

router = APIRouter(prefix="/api", tags=["media"])


@router.post("/import/upload", response_model=ImportResponse)
async def import_upload(file: UploadFile = File(...)) -> ImportResponse:
    data = await file.read()
    job_id = storage.new_job()
    ingest.save_upload(job_id, file.filename or "upload", data)
    jobs.ensure_previews(job_id)
    return ImportResponse(job_id=job_id, media=jobs.media_info(job_id))


@router.post("/import/url", response_model=ImportResponse)
def import_url(req: UrlImportRequest) -> ImportResponse:
    job_id = storage.new_job()
    ingest.import_url(job_id, req.url)
    jobs.ensure_previews(job_id)
    return ImportResponse(job_id=job_id, media=jobs.media_info(job_id))


@router.post("/job/{job_id}/fade-image")
async def upload_fade_image(job_id: str, file: UploadFile = File(...)) -> dict:
    data = await file.read()
    ingest.validate_upload_name(file.filename or "fade.png")
    from pathlib import Path

    ext = Path(file.filename or "fade.png").suffix.lower()
    dest = storage.job_path(job_id, f"fade{ext}", create=True)
    dest.write_bytes(data)
    return {"ok": True}


@router.get("/job/{job_id}/info")
def job_info(job_id: str) -> dict:
    return jobs.media_info(job_id)


@router.get("/job/{job_id}/file/{name}")
def job_file(job_id: str, name: str) -> FileResponse:
    path = storage.job_path(job_id, name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path)


@router.get("/job/{job_id}/frame")
def job_frame(job_id: str, t: float = Query(0.0, ge=0), long_edge: int | None = Query(None, ge=16, le=1080)) -> Response:
    png = jobs.frame_at(job_id, t, long_edge=long_edge)
    return Response(content=png, media_type="image/png")


@router.get("/job/{job_id}/filmstrip")
def job_filmstrip(job_id: str) -> FileResponse:
    return FileResponse(jobs.filmstrip(job_id), media_type="image/png")
