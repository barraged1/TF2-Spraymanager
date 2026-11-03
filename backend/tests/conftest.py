"""Shared pytest fixtures and synthetic media generators.

All test media is generated procedurally so the suite needs no external assets.
"""
from __future__ import annotations

import numpy as np
import pytest


def gradient_frame(width: int, height: int, *, alpha: bool = False, shift: int = 0) -> np.ndarray:
    """Create a deterministic RGBA gradient frame.

    ``shift`` rotates the pattern so successive frames differ, which is useful
    for building synthetic animations and loop-detection tests.
    """
    xs = (np.arange(width) + shift) % width
    ys = np.arange(height)
    gx, gy = np.meshgrid(xs, ys)
    r = (gx * 255 // max(width - 1, 1)).astype(np.uint8)
    g = (gy * 255 // max(height - 1, 1)).astype(np.uint8)
    b = ((gx + gy) * 255 // max(width + height - 2, 1)).astype(np.uint8)
    a = np.full((height, width), 255, np.uint8)
    if alpha:
        a = (gx * 255 // max(width - 1, 1)).astype(np.uint8)
    return np.dstack([r, g, b, a])


@pytest.fixture
def gradient():
    return gradient_frame


@pytest.fixture(autouse=True)
def tf2_closed(monkeypatch):
    """Results shouldn't depend on whether TF2 happens to be open on this PC."""
    from app.services import spray_randomizer

    monkeypatch.setattr(spray_randomizer, "tf2_running", lambda: False)


def make_test_video(path, frames, fps: float = 15.0) -> str:
    """Encode RGBA frames to an H.264 mp4 at ``path`` using bundled ffmpeg."""
    import imageio_ffmpeg

    h, w = frames[0].shape[:2]
    writer = imageio_ffmpeg.write_frames(
        str(path),
        (w, h),
        pix_fmt_in="rgba",
        pix_fmt_out="yuv420p",
        fps=fps,
        macro_block_size=1,
    )
    writer.send(None)  # initialize the encoder
    for fr in frames:
        writer.send(np.ascontiguousarray(fr).tobytes())
    writer.close()
    return str(path)


@pytest.fixture
def video_factory(tmp_path):
    """Return a callable that builds a temp video and returns its path."""

    def _make(n: int = 15, size: int = 64, fps: float = 15.0, period: int | None = None):
        period = period or n
        frames = [gradient_frame(size, size, shift=int(size * (i % period) / period)) for i in range(n)]
        return make_test_video(tmp_path / "clip.mp4", frames, fps=fps)

    return _make
