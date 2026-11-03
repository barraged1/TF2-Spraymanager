"""Pydantic request/response models for the API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class UrlImportRequest(BaseModel):
    url: str = Field(..., min_length=1, description="http(s) link to media or a video page")


class LoopRequest(BaseModel):
    analysis_fps: float = Field(12.0, gt=0, le=60)
    min_duration: float = Field(0.4, ge=0.1, le=30)
    max_duration: Optional[float] = Field(None, gt=0, le=60)
    top_n: int = Field(6, ge=1, le=20)


class CropRect(BaseModel):
    """A normalized crop rectangle (fractions of the source size, 0..1)."""

    x: float = Field(0.0, ge=0, le=1)
    y: float = Field(0.0, ge=0, le=1)
    w: float = Field(1.0, gt=0, le=1)
    h: float = Field(1.0, gt=0, le=1)


class ConvertRequest(BaseModel):
    name: str = "spray"

    # --- Source selection (video/animated only) ---
    animated: bool = True
    start: Optional[float] = Field(None, ge=0)
    duration: Optional[float] = Field(None, gt=0)
    fps: float = Field(5.0, gt=0, le=30, description="Spray playback fps (TF2 uses ~5)")
    #: Append the clip reversed so any clip loops seamlessly (forward then backward).
    boomerang: bool = False

    # --- Geometry ---
    crop: Optional[CropRect] = None
    fit_mode: Literal["letterbox", "pad_alpha", "crop", "stretch"] = "letterbox"
    max_edge: Optional[int] = Field(None, ge=4, le=1020)
    point_sample: bool = False
    mipmaps: bool = False

    # --- Format ---
    format: Literal["auto", "dxt1", "dxt5"] = "auto"

    # --- Chroma key (background -> transparency) ---
    chroma_key: bool = False
    chroma_color: Optional[tuple[int, int, int]] = None
    chroma_tolerance: int = Field(40, ge=0, le=255)
    chroma_softness: int = Field(20, ge=0, le=255)

    # --- Fading spray (needs a fade image uploaded to the job) ---
    fade: bool = False
    fade_from_level: int = Field(2, ge=1, le=12)

    translucent: bool = True


class ImportResponse(BaseModel):
    job_id: str
    media: dict


class ConvertResponse(BaseModel):
    job_id: str
    name: str
    width: int
    height: int
    frame_count: int
    format: str
    mipmaps: bool
    size_bytes: int
    size_kib: float
    within_limit: bool
    download_vtf: str
    download_vmt: str
    preview_url: str


class SaveRequest(BaseModel):
    name: Optional[str] = None
    overwrite: bool = False


class RotationToggle(BaseModel):
    enabled: bool


class IncludeToggle(BaseModel):
    included: bool


class StartSpray(BaseModel):
    filename: Optional[str] = None


class EstimateRequest(BaseModel):
    """Lightweight inputs for a pre-conversion size/resolution estimate."""

    animated: bool = True
    duration: Optional[float] = Field(None, gt=0)
    fps: float = Field(5.0, gt=0, le=30)
    boomerang: bool = False
    format: Literal["auto", "dxt1", "dxt5"] = "auto"
    mipmaps: bool = False
    fade: bool = False
    chroma_key: bool = False
    fit_mode: Literal["letterbox", "pad_alpha", "crop", "stretch"] = "letterbox"
    max_edge: Optional[int] = Field(None, ge=4, le=1020)


class EstimateResponse(BaseModel):
    fits: bool
    width: int
    height: int
    frame_count: int
    format: str
    mipmaps: bool
    size_bytes: int
    size_kib: float
    detail: Optional[str] = None


class Tf2StatusResponse(BaseModel):
    found: bool
    tf2_dir: Optional[str] = None
    logos_dir: Optional[str] = None
