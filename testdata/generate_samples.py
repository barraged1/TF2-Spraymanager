"""Generate sample media for manual/E2E testing of the spray tool.

Run with the project venv:  ``.venv\\Scripts\\python.exe testdata\\generate_samples.py``
Produces a static image and a short clip whose content repeats every second.
"""
from __future__ import annotations

from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent


def frame(width: int, height: int, shift: int) -> np.ndarray:
    xs = (np.arange(width) + shift) % width
    ys = np.arange(height)
    gx, gy = np.meshgrid(xs, ys)
    r = (gx * 255 // max(width - 1, 1)).astype(np.uint8)
    g = (gy * 255 // max(height - 1, 1)).astype(np.uint8)
    b = ((gx + gy) * 255 // max(width + height - 2, 1)).astype(np.uint8)
    a = np.full((height, width), 255, np.uint8)
    return np.dstack([r, g, b, a])


def main() -> None:
    Image.fromarray(frame(512, 384, 0), "RGBA").save(OUT / "sample.png")

    period, total, size, fps = 24, 72, 240, 24.0
    writer = imageio_ffmpeg.write_frames(
        str(OUT / "loop.mp4"),
        (size, size),
        pix_fmt_in="rgba",
        pix_fmt_out="yuv420p",
        fps=fps,
        macro_block_size=1,
    )
    writer.send(None)
    for i in range(total):
        writer.send(np.ascontiguousarray(frame(size, size, int(size * (i % period) / period))).tobytes())
    writer.close()
    print("Wrote", OUT / "sample.png", "and", OUT / "loop.mp4")


if __name__ == "__main__":
    main()
