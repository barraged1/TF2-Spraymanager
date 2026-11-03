"""Decide the best VTF format and resolution that fits the 512 KB spray budget.

Given a frame count and whether the source has transparency, this picks:

* the image format (``DXT1`` for opaque, ``DXT5`` for alpha), and
* the largest square edge length (multiple of 4) whose encoded size stays under
  the in-game limit.

Sprays are always rendered at a 1:1 aspect ratio in-game, so square output is
the sensible target; non-square sources are fitted to a square earlier in the
pipeline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import MAX_EDGE_DXT1, MAX_EDGE_DXT5, MAX_VTF_BYTES
from .vtf_writer import VtfFormat, estimate_vtf_size

#: Small safety margin so we stay comfortably under the hard limit.
_SAFETY_BYTES = 1024


@dataclass(slots=True)
class SizingResult:
    width: int
    height: int
    fmt: VtfFormat
    mipmaps: bool
    frame_count: int
    estimated_bytes: int

    @property
    def edge(self) -> int:
        return self.width


def choose_format(has_alpha: bool) -> VtfFormat:
    """Pick the spray-appropriate compressed format.

    DXT5 is used whenever transparency is present (DXT1's 1-bit alpha is also
    broken on Linux Source builds), otherwise DXT1 for maximum resolution.
    """
    return VtfFormat.DXT5 if has_alpha else VtfFormat.DXT1


def _max_edge_for_format(fmt: VtfFormat) -> int:
    return MAX_EDGE_DXT5 if fmt is VtfFormat.DXT5 else MAX_EDGE_DXT1


def solve_sizing(
    frame_count: int,
    has_alpha: bool,
    *,
    max_bytes: int = MAX_VTF_BYTES,
    mipmaps: bool = False,
    max_edge: int | None = None,
    fmt: VtfFormat | None = None,
) -> SizingResult:
    """Solve for the largest square spray that fits ``max_bytes``.

    :param frame_count: Number of animation frames (1 for a static spray).
    :param has_alpha: Whether the source needs transparency (selects DXT5).
    :param mipmaps: Whether a full mip chain is included (needed for fading).
    :param max_edge: Optional hard cap on the edge length (e.g. user choice).
    :param fmt: Force a specific format instead of auto-selecting.
    :raises ValueError: if not even a 4x4 spray fits the budget.
    """
    if frame_count < 1:
        raise ValueError("frame_count must be >= 1")

    fmt = fmt or choose_format(has_alpha)
    cap = _max_edge_for_format(fmt)
    if max_edge is not None:
        cap = min(cap, max_edge)
    cap -= cap % 4
    cap = max(cap, 4)

    budget = max_bytes - _SAFETY_BYTES
    bpp = fmt.bytes_per_pixel
    mip_factor = 4.0 / 3.0 if mipmaps else 1.0

    # Closed-form starting estimate, then refine against the exact estimator.
    raw = math.sqrt(max(budget - 64, 0) / (frame_count * bpp * mip_factor))
    edge = min(int(raw), cap)
    edge -= edge % 4

    while edge >= 4 and estimate_vtf_size(edge, edge, frame_count, fmt, mipmaps=mipmaps) > max_bytes:
        edge -= 4

    if edge < 4:
        raise ValueError(
            f"Cannot fit {frame_count} frame(s) of {fmt.name} under {max_bytes} bytes. "
            "Reduce the frame count or shorten the clip."
        )

    return SizingResult(
        width=edge,
        height=edge,
        fmt=fmt,
        mipmaps=mipmaps,
        frame_count=frame_count,
        estimated_bytes=estimate_vtf_size(edge, edge, frame_count, fmt, mipmaps=mipmaps),
    )


def max_frames_for_edge(
    edge: int,
    has_alpha: bool,
    *,
    max_bytes: int = MAX_VTF_BYTES,
    mipmaps: bool = False,
) -> int:
    """Largest frame count that fits at a fixed square ``edge`` length."""
    fmt = choose_format(has_alpha)
    if estimate_vtf_size(edge, edge, 1, fmt, mipmaps=mipmaps) > max_bytes:
        return 0
    n = 1
    while estimate_vtf_size(edge, edge, n + 1, fmt, mipmaps=mipmaps) <= max_bytes:
        n += 1
    return n
