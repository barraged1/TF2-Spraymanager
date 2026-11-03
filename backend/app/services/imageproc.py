"""Image loading and geometry: square-fitting, resizing, and chroma keying.

TF2 sprays are rendered at a 1:1 aspect ratio, so the converter always produces
square output. Sources are fitted to a square with one of three modes, and an
optional chroma-key step turns a solid background colour into transparency.
"""
from __future__ import annotations

import io
from enum import Enum

import numpy as np
from PIL import Image

# Allow large frames but guard against decompression-bomb style inputs.
Image.MAX_IMAGE_PIXELS = 64 * 1024 * 1024  # 64 MP

#: Alpha values at or below this are treated as "transparent" when detecting
#: whether a source actually needs an alpha-capable format.
_ALPHA_OPAQUE_THRESHOLD = 250


class FitMode(str, Enum):
    LETTERBOX = "letterbox"  # contain: whole image visible, padded to square
    PAD_ALPHA = "pad_alpha"  # contain + always transparent padding (forces DXT5)
    CROP = "crop"            # cover: fill square, crop the overflow
    STRETCH = "stretch"      # distort to a square


def load_rgba(data: bytes) -> np.ndarray:
    """Decode image bytes into an ``(H, W, 4)`` ``uint8`` RGBA array."""
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGBA")
        return np.array(im, dtype=np.uint8)


def pil_to_rgba(im: Image.Image) -> np.ndarray:
    return np.array(im.convert("RGBA"), dtype=np.uint8)


def rgba_to_png(arr: np.ndarray) -> bytes:
    """Encode an RGBA array as PNG bytes (used for browser previews)."""
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def has_alpha(arr: np.ndarray) -> bool:
    """True if the image contains meaningful transparency."""
    if arr.ndim != 3 or arr.shape[2] != 4:
        return False
    return bool(arr[:, :, 3].min() < _ALPHA_OPAQUE_THRESHOLD)


def _resize(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    import cv2

    if (arr.shape[1], arr.shape[0]) == (width, height):
        return np.ascontiguousarray(arr)
    shrinking = width < arr.shape[1] or height < arr.shape[0]
    interp = cv2.INTER_AREA if shrinking else cv2.INTER_LANCZOS4
    return np.ascontiguousarray(cv2.resize(arr, (width, height), interpolation=interp))


def crop_normalized(
    arr: np.ndarray,
    x: float,
    y: float,
    w: float,
    h: float,
) -> np.ndarray:
    """Crop a normalized rectangle (all values in 0..1) from an RGBA array.

    Coordinates are fractions of the source size, so the crop is independent of
    the displayed resolution. The result is clamped to stay within bounds and is
    guaranteed to be at least 1x1.
    """
    src_h, src_w = arr.shape[:2]
    x0 = max(0, min(src_w - 1, int(round(x * src_w))))
    y0 = max(0, min(src_h - 1, int(round(y * src_h))))
    x1 = max(x0 + 1, min(src_w, int(round((x + w) * src_w))))
    y1 = max(y0 + 1, min(src_h, int(round((y + h) * src_h))))
    return np.ascontiguousarray(arr[y0:y1, x0:x1])


def fit_square(
    arr: np.ndarray,
    edge: int,
    mode: FitMode = FitMode.LETTERBOX,
    *,
    pad_color: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> np.ndarray:
    """Fit ``arr`` into an ``edge`` x ``edge`` RGBA square using ``mode``."""
    if edge < 1:
        raise ValueError("edge must be positive")
    src_h, src_w = arr.shape[:2]

    if mode is FitMode.STRETCH:
        return _resize(arr, edge, edge)

    if mode is FitMode.CROP:
        scale = edge / min(src_w, src_h)
        new_w, new_h = max(round(src_w * scale), edge), max(round(src_h * scale), edge)
        resized = _resize(arr, new_w, new_h)
        x0 = (new_w - edge) // 2
        y0 = (new_h - edge) // 2
        return np.ascontiguousarray(resized[y0 : y0 + edge, x0 : x0 + edge])

    # LETTERBOX (contain)
    scale = edge / max(src_w, src_h)
    new_w, new_h = max(round(src_w * scale), 1), max(round(src_h * scale), 1)
    new_w, new_h = min(new_w, edge), min(new_h, edge)
    resized = _resize(arr, new_w, new_h)
    canvas = np.empty((edge, edge, 4), np.uint8)
    canvas[:] = np.array(pad_color, np.uint8)
    x0 = (edge - new_w) // 2
    y0 = (edge - new_h) // 2
    canvas[y0 : y0 + new_h, x0 : x0 + new_w] = resized
    return canvas


def auto_background_color(arr: np.ndarray) -> tuple[int, int, int]:
    """Guess the background colour from the median of the four corners/edges."""
    h, w = arr.shape[:2]
    border = np.concatenate(
        [
            arr[0, :, :3],
            arr[-1, :, :3],
            arr[:, 0, :3],
            arr[:, -1, :3],
        ]
    )
    med = np.median(border, axis=0)
    return int(med[0]), int(med[1]), int(med[2])


def chroma_key(
    arr: np.ndarray,
    key_color: tuple[int, int, int] | None = None,
    *,
    tolerance: int = 40,
    softness: int = 20,
) -> np.ndarray:
    """Make pixels near ``key_color`` transparent.

    :param key_color: RGB colour to remove; auto-detected from the border if None.
    :param tolerance: Colour distance fully removed (alpha -> 0).
    :param softness: Additional distance over which alpha feathers back to opaque.
    """
    if key_color is None:
        key_color = auto_background_color(arr)

    rgb = arr[:, :, :3].astype(np.int32)
    key = np.array(key_color, np.int32)
    dist = np.sqrt(((rgb - key) ** 2).sum(axis=2))

    inner = float(tolerance)
    outer = float(tolerance + max(softness, 1))
    alpha_factor = np.clip((dist - inner) / (outer - inner), 0.0, 1.0)

    out = arr.copy()
    new_alpha = np.minimum(arr[:, :, 3], (alpha_factor * 255).astype(np.uint8))
    out[:, :, 3] = new_alpha
    return out
