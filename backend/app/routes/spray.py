"""Routes for loop analysis, conversion, downloads, and saving into TF2."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import MAX_VTF_BYTES
from ..models import (
    ConvertRequest,
    ConvertResponse,
    EstimateRequest,
    EstimateResponse,
    LoopRequest,
    SaveRequest,
    Tf2StatusResponse,
)
from ..services import imageproc, jobs, library, loopfinder, sizing, spray_randomizer, storage, tf2_locate
from ..services.imageproc import FitMode
from ..services.spray_builder import ConvertOptions, build_spray
from ..services.vmt_writer import build_vmt
from ..services.vtf_writer import VtfFormat

router = APIRouter(prefix="/api", tags=["spray"])

_FORMAT_MAP = {"auto": None, "dxt1": VtfFormat.DXT1, "dxt5": VtfFormat.DXT5}


@router.post("/job/{job_id}/loops")
def analyze_loops(job_id: str, req: LoopRequest) -> dict:
    path = source_path = jobs.source_path(job_id)
    try:
        analysis = loopfinder.find_loops(
            str(path),
            analysis_fps=req.analysis_fps,
            min_duration=req.min_duration,
            max_duration=req.max_duration,
            top_n=req.top_n,
        )
    except Exception as exc:  # noqa: BLE001 - non-animated or unreadable
        return {"fps": 0.0, "frame_count": 0, "duration": 0.0, "candidates": [], "error": str(exc)}
    return analysis.as_dict()


@router.post("/job/{job_id}/estimate", response_model=EstimateResponse)
def estimate(job_id: str, req: EstimateRequest) -> EstimateResponse:
    """Predict the output resolution/format/size before doing a full conversion."""
    base = storage.job_dir(job_id)

    if req.animated and req.duration and req.duration > 0:
        frame_count = max(1, int(round(req.duration * req.fps)))
    else:
        frame_count = 1
    if req.boomerang and frame_count > 2:
        frame_count = frame_count * 2 - 2

    if req.format == "dxt5":
        fmt = VtfFormat.DXT5
    elif req.format == "dxt1":
        fmt = VtfFormat.DXT1
    else:
        preview = base / "preview.png"
        src_alpha = False
        if preview.exists():
            src_alpha = imageproc.has_alpha(imageproc.load_rgba(preview.read_bytes()))
        fmt = sizing.choose_format(req.chroma_key or src_alpha or req.fit_mode == "pad_alpha")

    use_mip = req.mipmaps or req.fade
    try:
        sized = sizing.solve_sizing(
            frame_count, fmt.has_alpha, mipmaps=use_mip, max_edge=req.max_edge, fmt=fmt
        )
    except ValueError as exc:
        return EstimateResponse(
            fits=False,
            width=0,
            height=0,
            frame_count=frame_count,
            format=fmt.name,
            mipmaps=use_mip,
            size_bytes=0,
            size_kib=0.0,
            detail=str(exc),
        )

    return EstimateResponse(
        fits=True,
        width=sized.width,
        height=sized.height,
        frame_count=frame_count,
        format=fmt.name,
        mipmaps=use_mip,
        size_bytes=sized.estimated_bytes,
        size_kib=round(sized.estimated_bytes / 1024, 2),
    )


@router.post("/job/{job_id}/convert", response_model=ConvertResponse)
def convert(job_id: str, req: ConvertRequest) -> ConvertResponse:
    fade_img = jobs.fade_image(job_id) if req.fade else None
    if req.fade and fade_img is None:
        raise HTTPException(status_code=400, detail="Enable fading after uploading a 'far' fade image.")

    frames = jobs.load_convert_frames(
        job_id,
        animated=req.animated,
        start=req.start,
        duration=req.duration,
        fps=req.fps,
    )
    if req.boomerang and len(frames) > 2:
        frames = frames + frames[-2:0:-1]

    options = ConvertOptions(
        name=req.name,
        crop=(req.crop.x, req.crop.y, req.crop.w, req.crop.h) if req.crop else None,
        fit_mode=FitMode(req.fit_mode),
        point_sample=req.point_sample,
        mipmaps=req.mipmaps,
        max_edge=req.max_edge,
        force_format=_FORMAT_MAP[req.format],
        chroma_key=req.chroma_key,
        chroma_color=tuple(req.chroma_color) if req.chroma_color else None,
        chroma_tolerance=req.chroma_tolerance,
        chroma_softness=req.chroma_softness,
        fade_image=fade_img,
        fade_from_level=req.fade_from_level,
        translucent=req.translucent,
    )

    try:
        result = build_spray(frames, options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    base = storage.job_dir(job_id)
    (base / "output.vtf").write_bytes(result.vtf)
    (base / "output.vmt").write_text(result.vmt, encoding="utf-8")
    (base / "manifest.json").write_text(json.dumps({"name": result.name}), encoding="utf-8")

    # Decode the encoded VTF so the preview shows exactly what TF2 will render.
    (base / "result.webp").write_bytes(
        library.render_preview(base / "output.vtf", library.PREVIEW_EDGES["full"])
    )
    preview_url = f"/api/job/{job_id}/file/result.webp"

    return ConvertResponse(
        job_id=job_id,
        name=result.name,
        width=result.width,
        height=result.height,
        frame_count=result.frame_count,
        format=result.fmt,
        mipmaps=result.mipmaps,
        size_bytes=result.size_bytes,
        size_kib=round(result.size_bytes / 1024, 2),
        within_limit=result.size_bytes < MAX_VTF_BYTES,
        download_vtf=f"/api/job/{job_id}/download/vtf",
        download_vmt=f"/api/job/{job_id}/download/vmt",
        preview_url=preview_url,
    )


def _spray_name(job_id: str) -> str:
    manifest = storage.job_dir(job_id) / "manifest.json"
    if manifest.exists():
        try:
            return json.loads(manifest.read_text(encoding="utf-8")).get("name", "spray")
        except (ValueError, OSError):
            pass
    return "spray"


@router.get("/job/{job_id}/download/vtf")
def download_vtf(job_id: str) -> FileResponse:
    path = storage.job_dir(job_id) / "output.vtf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Convert a spray first.")
    return FileResponse(path, media_type="application/octet-stream", filename=f"{_spray_name(job_id)}.vtf")


@router.get("/job/{job_id}/download/vmt")
def download_vmt(job_id: str) -> FileResponse:
    path = storage.job_dir(job_id) / "output.vmt"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Convert a spray first.")
    return FileResponse(path, media_type="text/plain", filename=f"{_spray_name(job_id)}.vmt")


@router.get("/tf2/status", response_model=Tf2StatusResponse)
def tf2_status() -> Tf2StatusResponse:
    loc = tf2_locate.find_tf2()
    if loc is None:
        return Tf2StatusResponse(found=False)
    return Tf2StatusResponse(found=True, tf2_dir=str(loc.tf2_dir), logos_dir=str(loc.logos_dir))


@router.post("/job/{job_id}/save-to-tf2")
def save_to_tf2(job_id: str, req: SaveRequest) -> dict:
    loc = tf2_locate.find_tf2()
    if loc is None:
        raise HTTPException(status_code=404, detail="Team Fortress 2 install was not found.")

    base = storage.job_dir(job_id)
    vtf_path = base / "output.vtf"
    if not vtf_path.exists():
        raise HTTPException(status_code=404, detail="Convert a spray first.")

    name = req.name or _spray_name(job_id)
    # Regenerate the VMT so its $basetexture always matches the final saved name.
    vmt_text = build_vmt(name)
    try:
        saved = tf2_locate.save_spray_to_tf2(
            loc, name, vtf_path.read_bytes(), vmt_text, overwrite=req.overwrite
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    rotation_refreshed = spray_randomizer.refresh(loc.tf2_dir)
    return {
        "ok": True,
        "saved": saved,
        "filename": saved["filename"],
        "logos_dir": str(loc.logos_dir),
        "rotation_refreshed": rotation_refreshed,
    }
