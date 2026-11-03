"""Tests for ffmpeg-based probing and frame extraction."""
from __future__ import annotations

import pytest

from app.services.ffmpeg_utils import extract_frames, probe


def test_probe_reports_dimensions_and_fps(video_factory):
    path = video_factory(n=15, size=64, fps=15.0)
    info = probe(path)
    assert info.width == 64
    assert info.height == 64
    assert info.fps == pytest.approx(15.0, abs=0.5)
    assert info.duration == pytest.approx(1.0, abs=0.2)


def test_extract_native_frames(video_factory):
    path = video_factory(n=15, size=64, fps=15.0)
    frames = extract_frames(path)
    assert 13 <= len(frames) <= 16  # codec may drop/pad a frame
    assert frames[0].shape == (64, 64, 4)


def test_extract_resampled_fps(video_factory):
    path = video_factory(n=30, size=64, fps=30.0)  # ~1 second
    frames = extract_frames(path, fps=5.0)
    # ~1s at 5 fps -> about 5 frames.
    assert 4 <= len(frames) <= 7


def test_extract_downscaled(video_factory):
    path = video_factory(n=10, size=128, fps=10.0)
    frames = extract_frames(path, long_edge=32)
    assert frames[0].shape[0] == 32 and frames[0].shape[1] == 32


def test_extract_trim_range(video_factory):
    path = video_factory(n=30, size=64, fps=30.0)  # ~1s
    frames = extract_frames(path, start=0.0, duration=0.5, fps=10.0)
    # 0.5s at 10 fps -> ~5 frames.
    assert 3 <= len(frames) <= 7


def test_max_frames_cap(video_factory):
    path = video_factory(n=30, size=64, fps=30.0)
    frames = extract_frames(path, max_frames=4)
    assert len(frames) == 4
