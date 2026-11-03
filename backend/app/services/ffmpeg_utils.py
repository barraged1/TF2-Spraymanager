"""FFmpeg helpers built on the bundled ``imageio-ffmpeg`` binary.

Provides media probing and decode-accurate frame extraction (with optional time
trimming, fps resampling, and downscaling). All ffmpeg invocations use argument
lists via ``imageio-ffmpeg`` (never a shell), so user-supplied paths and values
cannot inject commands.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import imageio_ffmpeg
import numpy as np


def ffmpeg_exe() -> str:
    """Absolute path to the bundled ffmpeg executable."""
    return imageio_ffmpeg.get_ffmpeg_exe()


@dataclass(slots=True)
class MediaInfo:
    width: int
    height: int
    fps: float
    duration: float

    @property
    def frame_count(self) -> int:
        if self.fps <= 0 or self.duration <= 0:
            return 0
        return int(round(self.fps * self.duration))

    @property
    def is_animated(self) -> bool:
        return self.duration > 0 and (self.frame_count > 1 or self.fps > 0)


def probe(path: str | Path) -> MediaInfo:
    """Read width/height/fps/duration without decoding the whole file."""
    reader = imageio_ffmpeg.read_frames(str(path), pix_fmt="rgba", bpp=4)
    try:
        meta = next(reader)
    finally:
        reader.close()
    w, h = meta["size"]
    return MediaInfo(
        width=int(w),
        height=int(h),
        fps=float(meta.get("fps") or 0.0),
        duration=float(meta.get("duration") or 0.0),
    )


def _seek_params(start: Optional[float]) -> tuple[list[str], list[str]]:
    """Split a start time into a fast input seek + accurate output seek.

    Seeking before ``-i`` jumps to the nearest keyframe quickly; a small output
    seek afterwards makes the final cut frame-accurate.
    """
    if not start or start <= 0:
        return [], []
    pre = max(0.0, start - 1.0)
    fine = start - pre
    input_params = ["-ss", f"{pre:.6f}"] if pre > 0 else []
    output_params = ["-ss", f"{fine:.6f}"] if fine > 0 else []
    return input_params, output_params


def _scale_filter(long_edge: Optional[int]) -> Optional[str]:
    if not long_edge:
        return None
    le = int(long_edge)
    # Scale the longer side to ``le`` and keep aspect (even dims for codecs).
    return (
        f"scale='if(gt(iw,ih),{le},-2)':'if(gt(iw,ih),-2,{le})':flags=area"
    )


def iter_frames(
    path: str | Path,
    *,
    fps: Optional[float] = None,
    start: Optional[float] = None,
    duration: Optional[float] = None,
    long_edge: Optional[int] = None,
    max_frames: Optional[int] = None,
) -> Iterator[np.ndarray]:
    """Yield RGBA frames as ``(H, W, 4)`` arrays, applying trim/fps/scale."""
    input_params, output_params = _seek_params(start)
    if duration and duration > 0:
        output_params += ["-t", f"{duration:.6f}"]

    filters = []
    if fps and fps > 0:
        filters.append(f"fps={fps}")
    scale = _scale_filter(long_edge)
    if scale:
        filters.append(scale)
    if filters:
        output_params += ["-vf", ",".join(filters)]

    reader = imageio_ffmpeg.read_frames(
        str(path),
        pix_fmt="rgba",
        bpp=4,
        input_params=input_params,
        output_params=output_params,
    )
    try:
        meta = next(reader)
        w, h = meta["size"]
        stride = w * h * 4
        count = 0
        for raw in reader:
            if len(raw) < stride:
                continue
            yield np.frombuffer(raw, np.uint8).reshape(h, w, 4).copy()
            count += 1
            if max_frames and count >= max_frames:
                break
    finally:
        reader.close()


def extract_frames(
    path: str | Path,
    *,
    fps: Optional[float] = None,
    start: Optional[float] = None,
    duration: Optional[float] = None,
    long_edge: Optional[int] = None,
    max_frames: Optional[int] = None,
) -> list[np.ndarray]:
    """Eagerly decode frames into a list (convenience wrapper of ``iter_frames``)."""
    return list(
        iter_frames(
            path,
            fps=fps,
            start=start,
            duration=duration,
            long_edge=long_edge,
            max_frames=max_frames,
        )
    )


def transcode_preview(
    src: str | Path,
    dest: str | Path,
    *,
    long_edge: int = 480,
    timeout: float = 120.0,
) -> Path:
    """Transcode any video/GIF into a browser-friendly H.264 mp4 preview.

    The preview is downscaled for snappy timeline scrubbing and uses
    ``+faststart`` so it begins playing before fully buffered.
    """
    dest = Path(dest)
    le = int(long_edge)
    vf = f"scale='if(gt(iw,ih),{le},-2)':'if(gt(iw,ih),-2,{le})':flags=area"
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-i",
        str(src),
        "-vf",
        vf,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0 or not dest.exists():
        msg = proc.stderr.decode("utf-8", "ignore")[-500:]
        raise RuntimeError(f"Preview transcode failed: {msg}")
    return dest
