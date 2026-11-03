"""High-level orchestration: turn source frames + options into a finished spray.

This ties together :mod:`imageproc` (geometry / chroma key), :mod:`sizing`
(format + resolution budget) and :mod:`vtf_writer` (encoding) so the API layer
has a single entry point for producing a ``.vtf`` + ``.vmt`` pair.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import imageproc, sizing
from .imageproc import FitMode
from .vmt_writer import build_vmt, sanitize_spray_name
from .vtf_writer import (
    SprayFrames,
    VtfFormat,
    count_mip_levels,
    encode_vtf,
)


@dataclass(slots=True)
class ConvertOptions:
    name: str = "spray"
    crop: Optional[tuple[float, float, float, float]] = None
    fit_mode: FitMode = FitMode.LETTERBOX
    point_sample: bool = False
    mipmaps: bool = False
    max_edge: Optional[int] = None
    force_format: Optional[VtfFormat] = None

    # Chroma key (background removal -> transparency)
    chroma_key: bool = False
    chroma_color: Optional[tuple[int, int, int]] = None
    chroma_tolerance: int = 40
    chroma_softness: int = 20

    # Fading spray: a different image shown at distance via mipmaps.
    fade_image: Optional[np.ndarray] = None
    fade_from_level: int = 2

    # Translucent VMT (almost always desired for sprays).
    translucent: bool = True


@dataclass(slots=True)
class ConvertResult:
    vtf: bytes
    vmt: str
    name: str
    width: int
    height: int
    frame_count: int
    fmt: str
    mipmaps: bool
    size_bytes: int
    fitted_frames: list[np.ndarray] = field(repr=False, default_factory=list)


def build_spray(frames: list[np.ndarray], options: ConvertOptions) -> ConvertResult:
    """Build a complete spray from one or more RGBA frames.

    A single frame yields a static spray; multiple frames yield an animated one.
    """
    if not frames:
        raise ValueError("No frames supplied.")

    # 0. Optional crop (normalized rect) applied before everything else.
    if options.crop is not None:
        frames = [imageproc.crop_normalized(f, *options.crop) for f in frames]

    # 1. Optional background removal first, so alpha detection is accurate.
    if options.chroma_key:
        frames = [
            imageproc.chroma_key(
                f,
                options.chroma_color,
                tolerance=options.chroma_tolerance,
                softness=options.chroma_softness,
            )
            for f in frames
        ]

    # 2. Decide format from transparency (unless forced). Transparent-padding fit
    #    needs an alpha format even when the source is fully opaque.
    needs_alpha = options.fit_mode is FitMode.PAD_ALPHA or any(imageproc.has_alpha(f) for f in frames)
    fmt = options.force_format or sizing.choose_format(needs_alpha)

    # 3. Fading requires a mip chain.
    use_mipmaps = options.mipmaps or options.fade_image is not None

    # 4. Solve for the largest square edge that fits the budget.
    sized = sizing.solve_sizing(
        frame_count=len(frames),
        has_alpha=fmt.has_alpha,
        mipmaps=use_mipmaps,
        max_edge=options.max_edge,
        fmt=fmt,
    )
    edge = sized.edge

    # 5. Fit every frame to the square.
    pad = (0, 0, 0, 0) if fmt.has_alpha else (0, 0, 0, 255)
    fitted = [imageproc.fit_square(f, edge, options.fit_mode, pad_color=pad) for f in frames]

    # 6. Prepare fading mip overrides (far image on the lower mips).
    mip_overrides: dict[int, list[np.ndarray]] = {}
    if options.fade_image is not None and use_mipmaps:
        far = imageproc.fit_square(options.fade_image, edge, options.fit_mode, pad_color=pad)
        levels = count_mip_levels(edge, edge)
        start = max(1, min(options.fade_from_level, levels - 1))
        for level in range(start, levels):
            mip_overrides[level] = [far]

    spray = SprayFrames(frames=fitted, mip_overrides=mip_overrides)
    vtf = encode_vtf(spray, fmt, mipmaps=use_mipmaps, point_sample=options.point_sample)

    name = sanitize_spray_name(options.name)
    vmt = build_vmt(name, translucent=options.translucent)

    return ConvertResult(
        vtf=vtf,
        vmt=vmt,
        name=name,
        width=edge,
        height=edge,
        frame_count=len(fitted),
        fmt=fmt.name,
        mipmaps=use_mipmaps,
        size_bytes=len(vtf),
        fitted_frames=fitted,
    )
