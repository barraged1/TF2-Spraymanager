"""Find where a clip loops most seamlessly (frame-similarity seam search).

The core idea is autocorrelation over frames: a segment of length ``L`` starting
at frame ``s`` makes a good loop when frame ``s+k`` closely matches frame
``s+L+k`` for a short window of ``k`` (i.e. ``L`` is a visual period). We score
every plausible ``(s, L)`` on small grayscale thumbnails and return the best,
most diverse candidates as time ranges the user can preview and trim to.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .ffmpeg_utils import extract_frames, probe

#: Resolution of the grayscale thumbnails used for comparison.
_THUMB = 32
#: Hard cap on analysis frames so very long clips stay responsive.
_MAX_ANALYSIS_FRAMES = 400


@dataclass(slots=True)
class LoopCandidate:
    start_frame: int
    end_frame: int
    length_frames: int
    start_time: float
    end_time: float
    duration: float
    score: float
    similarity: float

    def as_dict(self) -> dict:
        return {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "length_frames": self.length_frames,
            "start_time": round(self.start_time, 4),
            "end_time": round(self.end_time, 4),
            "duration": round(self.duration, 4),
            "score": round(self.score, 4),
            "similarity": round(self.similarity, 4),
        }


@dataclass(slots=True)
class LoopAnalysis:
    fps: float
    frame_count: int
    duration: float
    candidates: list[LoopCandidate] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "fps": round(self.fps, 4),
            "frame_count": self.frame_count,
            "duration": round(self.duration, 4),
            "candidates": [c.as_dict() for c in self.candidates],
        }


def _thumbnails(frames: list[np.ndarray]) -> np.ndarray:
    """Return an ``(N, THUMB*THUMB)`` float32 array of grayscale thumbnails."""
    import cv2

    out = np.empty((len(frames), _THUMB * _THUMB), np.float32)
    for i, fr in enumerate(frames):
        gray = cv2.cvtColor(fr, cv2.COLOR_RGBA2GRAY)
        small = cv2.resize(gray, (_THUMB, _THUMB), interpolation=cv2.INTER_AREA)
        out[i] = small.reshape(-1).astype(np.float32)
    return out


def _similarity(score: float) -> float:
    # ``score`` is mean squared error on 0..255 grayscale; convert to RMSE -> 0..1.
    rmse = float(np.sqrt(max(score, 0.0)))
    return max(0.0, 1.0 - rmse / 255.0)


def find_loops_from_frames(
    frames: list[np.ndarray],
    fps: float,
    *,
    min_duration: float = 0.4,
    max_duration: float | None = None,
    window: int = 2,
    top_n: int = 6,
) -> LoopAnalysis:
    """Score loop candidates from already-extracted frames.

    :param frames: RGBA frames sampled at ``fps``.
    :param window: Number of consecutive frames matched at the seam to reject
        coincidental single-frame matches.
    """
    n = len(frames)
    duration = n / fps if fps else 0.0
    analysis = LoopAnalysis(fps=fps, frame_count=n, duration=duration)
    if n < 3 or fps <= 0:
        return analysis

    window = max(1, window)
    g = _thumbnails(frames)

    min_len = max(2, int(round(min_duration * fps)))
    hard_max = n - window
    max_len = hard_max if max_duration is None else min(hard_max, int(round(max_duration * fps)))
    if max_len < min_len:
        return analysis

    raw: list[tuple[float, int, int]] = []  # (score, start, length)
    for length in range(min_len, max_len + 1):
        tail = n - length
        if tail < window:
            continue
        diff = g[:tail] - g[length : length + tail]
        per_start = np.mean(diff * diff, axis=1)  # MSE(i, i+length)
        if window > 1:
            kernel = np.ones(window, np.float32) / window
            wc = np.convolve(per_start, kernel, mode="valid")
        else:
            wc = per_start
        s = int(np.argmin(wc))
        raw.append((float(wc[s]), s, length))

    raw.sort(key=lambda t: t[0])

    # Greedily keep diverse candidates (avoid near-duplicate start/length).
    chosen: list[tuple[float, int, int]] = []
    for score, s, length in raw:
        if any(abs(length - L2) <= max(2, int(0.1 * L2)) and abs(s - s2) <= 2 for _, s2, L2 in chosen):
            continue
        chosen.append((score, s, length))
        if len(chosen) >= top_n:
            break

    for score, s, length in chosen:
        e = s + length - 1
        analysis.candidates.append(
            LoopCandidate(
                start_frame=s,
                end_frame=e,
                length_frames=length,
                start_time=s / fps,
                end_time=(e + 1) / fps,
                duration=length / fps,
                score=score,
                similarity=_similarity(score),
            )
        )
    return analysis


def find_loops(
    path: str,
    *,
    analysis_fps: float = 12.0,
    long_edge: int = 96,
    min_duration: float = 0.4,
    max_duration: float | None = None,
    window: int = 2,
    top_n: int = 6,
) -> LoopAnalysis:
    """Extract analysis frames from ``path`` and score loop candidates."""
    info = probe(path)
    fps = analysis_fps
    if info.duration > 0:
        # Keep within the analysis-frame budget for long clips.
        max_fps_for_budget = _MAX_ANALYSIS_FRAMES / info.duration
        fps = min(analysis_fps, max(2.0, max_fps_for_budget))

    frames = extract_frames(path, fps=fps, long_edge=long_edge, max_frames=_MAX_ANALYSIS_FRAMES)
    return find_loops_from_frames(
        frames,
        fps,
        min_duration=min_duration,
        max_duration=max_duration,
        window=window,
        top_n=top_n,
    )
