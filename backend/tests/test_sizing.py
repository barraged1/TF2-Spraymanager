"""Tests for the format/resolution budget solver."""
from __future__ import annotations

import pytest

from app.config import MAX_VTF_BYTES
from app.services.sizing import (
    choose_format,
    max_frames_for_edge,
    solve_sizing,
)
from app.services.vtf_writer import VtfFormat, estimate_vtf_size


def test_format_selection():
    assert choose_format(False) is VtfFormat.DXT1
    assert choose_format(True) is VtfFormat.DXT5


def test_static_opaque_uses_large_edge():
    res = solve_sizing(frame_count=1, has_alpha=False)
    assert res.fmt is VtfFormat.DXT1
    # A single opaque frame should reach near the 1020 cap.
    assert res.edge >= 1016
    assert res.estimated_bytes < MAX_VTF_BYTES


def test_static_alpha_capped_at_724():
    res = solve_sizing(frame_count=1, has_alpha=True)
    assert res.fmt is VtfFormat.DXT5
    assert res.edge <= 724
    assert res.estimated_bytes < MAX_VTF_BYTES


def test_more_frames_shrink_resolution():
    one = solve_sizing(frame_count=1, has_alpha=False)
    many = solve_sizing(frame_count=20, has_alpha=False)
    assert many.edge < one.edge
    assert many.estimated_bytes < MAX_VTF_BYTES


def test_result_always_fits_budget():
    for n in (1, 2, 5, 10, 30, 60, 120):
        for alpha in (False, True):
            res = solve_sizing(frame_count=n, has_alpha=alpha)
            actual = estimate_vtf_size(res.width, res.height, n, res.fmt, mipmaps=res.mipmaps)
            assert actual < MAX_VTF_BYTES, f"n={n} alpha={alpha} -> {actual}"
            assert res.edge % 4 == 0


def test_mipmaps_reduce_edge():
    flat = solve_sizing(frame_count=1, has_alpha=False, mipmaps=False)
    mipped = solve_sizing(frame_count=1, has_alpha=False, mipmaps=True)
    assert mipped.edge < flat.edge


def test_max_edge_override():
    res = solve_sizing(frame_count=1, has_alpha=False, max_edge=256)
    assert res.edge == 256


def test_impossible_budget_raises():
    with pytest.raises(ValueError):
        solve_sizing(frame_count=100000, has_alpha=True)


def test_max_frames_for_edge():
    assert max_frames_for_edge(256, has_alpha=False) > max_frames_for_edge(512, has_alpha=False)
    assert max_frames_for_edge(64, has_alpha=False) >= 1
