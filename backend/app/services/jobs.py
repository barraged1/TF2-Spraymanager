"""Job-level orchestration shared by the API routes.

Resolves the source file for a job, reports media info, generates browser
previews, and extracts the frames used for conversion. Keeps the HTTP layer thin.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from . import ffmpeg_utils, storage
from .imageproc import load_rgba, rgba_to_png

_STATIC_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tga"}
_VIDEO_EXTS = {".gif", ".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}


class JobError(Exception):
    pass


def source_path(job_id: str) -> Path:
    """Return the imported source file for a job."""
    base = storage.job_dir(job_id)
    matches = sorted(base.glob("source.*"))
    if not matches:
        raise JobError("No source media has been imported for this job yet.")
    return matches[0]


def _is_static_ext(path: Path) -> bool:
    return path.suffix.lower() in _STATIC_IMAGE_EXTS


def media_info(job_id: str) -> dict:
    """Describe the source: kind, dimensions, fps/duration, and preview URLs."""
    path = source_path(job_id)
    ensure_previews(job_id)
    base_url = f"/api/job/{job_id}/file"

    if _is_static_ext(path):
        arr = load_rgba(path.read_bytes())
        return {
            "kind": "image",
            "width": int(arr.shape[1]),
            "height": int(arr.shape[0]),
            "fps": 0.0,
            "duration": 0.0,
            "frame_count": 1,
            "animated": False,
            "preview_image": f"{base_url}/preview.png",
            "preview_video": None,
        }

    info = ffmpeg_utils.probe(path)
    animated = info.duration > 0.05 and info.frame_count != 1
    return {
        "kind": "video" if animated else "image",
        "width": info.width,
        "height": info.height,
        "fps": round(info.fps, 4),
        "duration": round(info.duration, 4),
        "frame_count": info.frame_count,
        "animated": animated,
        "preview_image": f"{base_url}/preview.png",
        "preview_video": f"{base_url}/preview.mp4" if animated else None,
    }


def ensure_previews(job_id: str) -> None:
    """Generate ``preview.png`` (poster) and, for video, ``preview.mp4``."""
    path = source_path(job_id)
    base = storage.job_dir(job_id)
    png = base / "preview.png"
    mp4 = base / "preview.mp4"

    if _is_static_ext(path):
        if not png.exists():
            png.write_bytes(_downscaled_png(load_rgba(path.read_bytes())))
        return

    info = ffmpeg_utils.probe(path)
    animated = info.duration > 0.05 and info.frame_count != 1
    if not png.exists():
        frames = ffmpeg_utils.extract_frames(path, long_edge=480, max_frames=1)
        if frames:
            png.write_bytes(rgba_to_png(frames[0]))
    if animated and not mp4.exists():
        try:
            ffmpeg_utils.transcode_preview(path, mp4)
        except Exception:  # noqa: BLE001 - preview is best-effort
            pass


def _downscaled_png(arr: np.ndarray, long_edge: int = 480) -> bytes:
    import cv2

    h, w = arr.shape[:2]
    scale = long_edge / max(w, h)
    if scale < 1:
        arr = cv2.resize(arr, (max(int(w * scale), 1), max(int(h * scale), 1)), interpolation=cv2.INTER_AREA)
    return rgba_to_png(np.ascontiguousarray(arr))


def frame_at(job_id: str, time_s: float, *, long_edge: Optional[int] = None) -> bytes:
    """Return a single frame at ``time_s`` as PNG bytes (for scrubbing)."""
    path = source_path(job_id)
    if _is_static_ext(path):
        return rgba_to_png(load_rgba(path.read_bytes()))
    frames = ffmpeg_utils.extract_frames(path, start=max(0.0, time_s), max_frames=1, long_edge=long_edge)
    if not frames:
        frames = ffmpeg_utils.extract_frames(path, max_frames=1, long_edge=long_edge)
    if not frames:
        raise JobError("Could not read a frame at the requested time.")
    return rgba_to_png(frames[0])


def load_convert_frames(
    job_id: str,
    *,
    animated: bool,
    start: Optional[float] = None,
    duration: Optional[float] = None,
    fps: float = 5.0,
    max_frames: Optional[int] = None,
) -> list[np.ndarray]:
    """Load the RGBA frames to convert into a spray."""
    path = source_path(job_id)

    if _is_static_ext(path):
        return [load_rgba(path.read_bytes())]

    info = ffmpeg_utils.probe(path)
    is_animated_source = info.duration > 0.05 and info.frame_count != 1
    if not animated or not is_animated_source:
        # Single still frame taken at ``start`` (or the beginning).
        frames = ffmpeg_utils.extract_frames(path, start=start or 0.0, max_frames=1)
        if not frames:
            frames = ffmpeg_utils.extract_frames(path, max_frames=1)
        return frames[:1]

    frames = ffmpeg_utils.extract_frames(
        path,
        fps=fps,
        start=start,
        duration=duration,
        max_frames=max_frames,
    )
    if not frames:
        raise JobError("No frames could be extracted from the selected range.")
    return frames


def fade_image(job_id: str) -> Optional[np.ndarray]:
    """Return the optional 'far' fade image uploaded for this job, if any."""
    base = storage.job_dir(job_id)
    matches = sorted(base.glob("fade.*"))
    if not matches:
        return None
    return load_rgba(matches[0].read_bytes())


def filmstrip(job_id: str, count: int = 24, height: int = 56) -> Path:
    """PNG strip of ``count`` evenly spaced frames, laid out across the whole clip."""
    out = storage.job_dir(job_id) / "filmstrip.png"
    if out.exists():
        return out
    path = source_path(job_id)
    info = ffmpeg_utils.probe(path)
    if _is_static_ext(path) or info.duration <= 0:
        raise JobError("Filmstrips are only available for videos and GIFs.")
    frames = ffmpeg_utils.extract_frames(
        path, fps=count / info.duration, long_edge=height * 3, max_frames=count
    )
    if not frames:
        raise JobError("Could not read frames for the filmstrip.")
    src_h, src_w = frames[0].shape[:2]
    tile_w = max(1, round(height * src_w / src_h))
    strip = Image.new("RGB", (tile_w * len(frames), height))
    for index, frame in enumerate(frames):
        tile = Image.fromarray(frame, "RGBA").convert("RGB").resize((tile_w, height), Image.LANCZOS)
        strip.paste(tile, (index * tile_w, 0))
    strip.save(out, format="PNG")
    return out
