"""Tests for the loop finder (frame-similarity seam search)."""
from __future__ import annotations

import pytest

from app.services.loopfinder import find_loops, find_loops_from_frames
from conftest import gradient_frame


def _periodic_frames(period: int, count: int, size: int = 48):
    return [gradient_frame(size, size, shift=int(size * (i % period) / period)) for i in range(count)]


def test_detects_known_period():
    frames = _periodic_frames(period=12, count=36)
    analysis = find_loops_from_frames(frames, fps=12.0, min_duration=0.3)
    assert analysis.candidates
    lengths = [c.length_frames for c in analysis.candidates]
    assert any(abs(length - 12) <= 1 for length in lengths)


def test_best_candidate_is_seamless():
    frames = _periodic_frames(period=10, count=40)
    analysis = find_loops_from_frames(frames, fps=10.0, min_duration=0.3)
    best = analysis.candidates[0]
    assert best.similarity > 0.95
    assert best.duration == pytest.approx(best.length_frames / 10.0)


def test_time_ranges_make_sense():
    frames = _periodic_frames(period=8, count=24)
    analysis = find_loops_from_frames(frames, fps=8.0)
    for cand in analysis.candidates:
        assert 0 <= cand.start_time < cand.end_time <= analysis.duration + 1e-6
        assert cand.length_frames == cand.end_frame - cand.start_frame + 1


def test_handles_too_few_frames():
    frames = _periodic_frames(period=2, count=2)
    analysis = find_loops_from_frames(frames, fps=5.0)
    assert analysis.candidates == []


def test_find_loops_on_video(video_factory):
    # Build a ~3s clip whose content repeats every 10 frames (1s at 10 fps).
    path = video_factory(n=30, size=64, fps=10.0, period=10)
    analysis = find_loops(path, analysis_fps=10.0, min_duration=0.5)
    assert analysis.candidates
    # The dominant period (~1s) should surface as a candidate.
    assert any(abs(c.duration - 1.0) <= 0.25 for c in analysis.candidates)
