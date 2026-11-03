"""Custom Valve Texture Format (VTF) writer for TF2 sprays.

Why a custom writer instead of ``srctools.VTF`` directly?

* TF2 sprays reach their highest quality at *non-power-of-two* sizes
  (1020x1020 for opaque DXT1, 724x724 for DXT5 with alpha). ``srctools.VTF``
  rejects non-power-of-two dimensions, and 1024x1024 DXT1 is exactly 512 KiB of
  pixel data which already exceeds the in-game 512 KB limit once the header is
  added.
* We still want the proven, MIT-licensed libsquish DXT1/DXT5 compressor that
  ships compiled inside ``srctools``. So this module hand-writes the small,
  well-understood VTF 7.1 container (the exact layout the de-facto standard
  browser tool produces) and delegates only the per-block colour compression to
  ``srctools``.

The output is validated in tests by reading it back with ``srctools.vtf.VTF``.
"""
from __future__ import annotations

import array
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import BinaryIO, Optional

import numpy as np
from srctools import vtf as _srcvtf

# The compiled (or pure-python) format conversion helpers inside srctools.
# ``save(fmt, pixels, data, w, h)`` compresses an RGBA byte array into ``data``.
_format_funcs = _srcvtf._format_funcs
_SrcFmt = _srcvtf.ImageFormats


# --- VTF on-disk image format codes (Valve IMAGE_FORMAT_* enum) ------------
class VtfFormat(Enum):
    """Subset of VTF image formats relevant to sprays.

    The value is ``(srctools_format_name, on_disk_code, bytes_per_pixel)``.
    """

    RGBA8888 = ("RGBA8888", 0, 4.0)
    DXT1 = ("DXT1", 13, 0.5)  # opaque, 4:1 colour compression
    DXT5 = ("DXT5", 15, 1.0)  # 8-bit interpolated alpha

    @property
    def code(self) -> int:
        return self.value[1]

    @property
    def bytes_per_pixel(self) -> float:
        return self.value[2]

    @property
    def has_alpha(self) -> bool:
        return self is VtfFormat.DXT5 or self is VtfFormat.RGBA8888

    @property
    def _src(self):  # srctools ImageFormats member
        return getattr(_SrcFmt, self.value[0])


# --- VTF texture flags (subset) -------------------------------------------
FLAG_POINT_SAMPLE = 0x0001
FLAG_CLAMP_S = 0x0004
FLAG_CLAMP_T = 0x0008
FLAG_NO_MIP = 0x0100
FLAG_NO_LOD = 0x0200
FLAG_ONEBITALPHA = 0x1000
FLAG_EIGHTBITALPHA = 0x2000

_VTF_VERSION = (7, 1)
_HEADER_SIZE = 64
#: VTF max single-dimension; sprays never approach this but guard anyway.
_MAX_DIMENSION = 0x7FFF


@dataclass(slots=True)
class SprayFrames:
    """Input to the encoder: one or more equally-sized RGBA frames.

    Each frame is an ``(H, W, 4)`` ``uint8`` array in RGBA order. A single frame
    produces a static spray; multiple frames produce an animated spray.
    """

    frames: list[np.ndarray]
    #: Optional per-mip-level override images (for "fading" sprays where a
    #: different picture is shown at distance). Maps mip level -> list of frames.
    mip_overrides: dict[int, list[np.ndarray]] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return int(self.frames[0].shape[1])

    @property
    def height(self) -> int:
        return int(self.frames[0].shape[0])

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def validate(self) -> None:
        if not self.frames:
            raise ValueError("At least one frame is required.")
        h, w = self.frames[0].shape[:2]
        if w < 1 or h < 1:
            raise ValueError("Frame dimensions must be positive.")
        if w > _MAX_DIMENSION or h > _MAX_DIMENSION:
            raise ValueError(f"Frame dimensions exceed VTF maximum {_MAX_DIMENSION}.")
        for i, fr in enumerate(self.frames):
            if fr.shape[:2] != (h, w):
                raise ValueError(f"Frame {i} size {fr.shape[1]}x{fr.shape[0]} != {w}x{h}.")
            if fr.ndim != 3 or fr.shape[2] != 4:
                raise ValueError(f"Frame {i} must be HxWx4 RGBA.")


def _resize_rgba(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize an RGBA array to ``width`` x ``height`` using a good filter.

    Uses OpenCV's area filter for downscaling (best for mipmaps) and Lanczos for
    any upscaling. Imported lazily so the module loads even if OpenCV is absent.
    """
    import cv2

    if arr.shape[1] == width and arr.shape[0] == height:
        return np.ascontiguousarray(arr)
    shrinking = width < arr.shape[1] or height < arr.shape[0]
    interp = cv2.INTER_AREA if shrinking else cv2.INTER_LANCZOS4
    return np.ascontiguousarray(cv2.resize(arr, (width, height), interpolation=interp))


def _mip_dims(width: int, height: int) -> list[tuple[int, int]]:
    """Return mip dimensions from largest (level 0) to 1x1, like the engine."""
    dims = [(width, height)]
    w, h = width, height
    while w > 1 or h > 1:
        w = max(w >> 1, 1)
        h = max(h >> 1, 1)
        dims.append((w, h))
    return dims


def count_mip_levels(width: int, height: int) -> int:
    """Number of mip levels in a full chain for the given dimensions."""
    return len(_mip_dims(width, height))


def _compress(rgba: np.ndarray, fmt: VtfFormat) -> bytes:
    """Compress one RGBA frame into the given VTF format's raw bytes."""
    h, w = rgba.shape[:2]
    pixels = array.array("B", np.ascontiguousarray(rgba).tobytes())
    buf = bytearray(fmt._src.frame_size(w, h))
    _format_funcs.save(fmt._src, pixels, buf, w, h)
    return bytes(buf)


def _compute_flags(fmt: VtfFormat, *, mipmaps: bool, point_sample: bool) -> int:
    flags = FLAG_CLAMP_S | FLAG_CLAMP_T | FLAG_NO_LOD
    if not mipmaps:
        flags |= FLAG_NO_MIP
    if fmt is VtfFormat.DXT5:
        flags |= FLAG_EIGHTBITALPHA
    if point_sample:
        flags |= FLAG_POINT_SAMPLE
    return flags


def _build_header(
    *,
    width: int,
    height: int,
    flags: int,
    frame_count: int,
    fmt: VtfFormat,
    mip_count: int,
    low_fmt_code: int,
    low_width: int,
    low_height: int,
) -> bytes:
    """Pack the fixed 64-byte VTF 7.1 header."""
    hdr = bytearray(_HEADER_SIZE)
    hdr[0:4] = b"VTF\x00"
    struct.pack_into("<II", hdr, 4, _VTF_VERSION[0], _VTF_VERSION[1])
    struct.pack_into("<I", hdr, 12, _HEADER_SIZE)
    struct.pack_into("<HH", hdr, 16, width, height)
    struct.pack_into("<I", hdr, 20, flags)
    struct.pack_into("<H", hdr, 24, frame_count)
    struct.pack_into("<H", hdr, 26, 0)  # first frame index
    struct.pack_into("<fff", hdr, 32, 0.0, 0.0, 0.0)  # reflectivity
    struct.pack_into("<f", hdr, 48, 1.0)  # bumpmap scale
    struct.pack_into("<i", hdr, 52, fmt.code)
    struct.pack_into("<B", hdr, 56, mip_count)
    # Low-res thumbnail descriptor (vtex/VTFEdit always include one).
    struct.pack_into("<i", hdr, 57, low_fmt_code)
    struct.pack_into("<B", hdr, 61, low_width)
    struct.pack_into("<B", hdr, 62, low_height)
    return bytes(hdr)


def _thumbnail_edge(width: int, height: int) -> int:
    """Square thumbnail edge: the engine standard caps the larger side at 16."""
    edge = min(16, width, height)
    edge -= edge % 4  # DXT1 works in 4x4 blocks
    return max(edge, 0)


def _make_thumbnail(frame0: np.ndarray) -> tuple[int, int, bytes]:
    """Build a small DXT1 low-res thumbnail from the first frame.

    Returns ``(width, height, dxt1_bytes)``. If the image is too small for a
    valid 4x4 block, returns ``(0, 0, b"")`` so no thumbnail is written.
    """
    h, w = frame0.shape[:2]
    edge = _thumbnail_edge(w, h)
    if edge < 4:
        return 0, 0, b""
    thumb = _resize_rgba(frame0, edge, edge)
    return edge, edge, _compress(thumb, VtfFormat.DXT1)


def encode_vtf(
    spray: SprayFrames,
    fmt: VtfFormat,
    *,
    mipmaps: bool = False,
    point_sample: bool = False,
) -> bytes:
    """Encode frames into a complete VTF 7.1 byte string.

    :param spray: The frames (and optional fading mip overrides) to encode.
    :param fmt: Target image format (DXT1 opaque, DXT5 alpha, or RGBA8888).
    :param mipmaps: Generate a full mip chain. Required for "fading" sprays;
        increases file size by ~33%.
    :param point_sample: Use nearest-neighbour sampling (crisp pixel art).
    """
    spray.validate()
    width, height, frame_count = spray.width, spray.height, spray.frame_count

    dims = _mip_dims(width, height)
    mip_count = len(dims) if mipmaps else 1
    flags = _compute_flags(fmt, mipmaps=mipmaps, point_sample=point_sample)

    # Build every mip level's frames (level 0 = source frames).
    mip_frames: list[list[np.ndarray]] = [[np.ascontiguousarray(f) for f in spray.frames]]
    for level in range(1, mip_count):
        w, h = dims[level]
        mip_frames.append([_resize_rgba(f, w, h) for f in spray.frames])

    # Apply fading overrides: replace a whole mip level with custom image(s).
    for level, imgs in spray.mip_overrides.items():
        if level < 0 or level >= mip_count:
            continue
        w, h = dims[level]
        if len(imgs) == 1 and frame_count > 1:
            imgs = imgs * frame_count
        mip_frames[level] = [_resize_rgba(img, w, h) for img in imgs[:frame_count]]

    # Low-res thumbnail (always DXT1, like vtex/VTFEdit) for engine compatibility.
    low_w, low_h, low_data = _make_thumbnail(mip_frames[0][0])
    low_fmt_code = VtfFormat.DXT1.code if low_data else -1

    out = bytearray()
    out += _build_header(
        width=width,
        height=height,
        flags=flags,
        frame_count=frame_count,
        fmt=fmt,
        mip_count=mip_count,
        low_fmt_code=low_fmt_code,
        low_width=low_w,
        low_height=low_h,
    )
    # Low-res image data comes immediately after the header.
    out += low_data
    # High-res data: smallest mip first, then per frame (standard VTF order).
    for level in reversed(range(mip_count)):
        for frame_idx in range(frame_count):
            out += _compress(mip_frames[level][frame_idx], fmt)

    return bytes(out)


def estimate_vtf_size(
    width: int,
    height: int,
    frame_count: int,
    fmt: VtfFormat,
    *,
    mipmaps: bool = False,
) -> int:
    """Estimate the encoded VTF size in bytes without doing the compression."""
    if fmt in (VtfFormat.DXT1, VtfFormat.DXT5):
        # Compressed in 4x4 blocks; account for partial edge blocks per mip.
        block_bytes = 8 if fmt is VtfFormat.DXT1 else 16

        def frame_bytes(w: int, h: int) -> int:
            return ((w + 3) // 4) * ((h + 3) // 4) * block_bytes
    else:
        bpp = int(fmt.bytes_per_pixel)

        def frame_bytes(w: int, h: int) -> int:
            return w * h * bpp

    dims = _mip_dims(width, height) if mipmaps else [(width, height)]
    total = sum(frame_bytes(w, h) for (w, h) in dims) * frame_count

    # Low-res DXT1 thumbnail (always written when a 4x4 block fits).
    thumb_edge = _thumbnail_edge(width, height)
    thumb_bytes = ((thumb_edge + 3) // 4) ** 2 * 8 if thumb_edge >= 4 else 0

    return _HEADER_SIZE + thumb_bytes + total


_FLAG_ENVMAP = 0x4000
_HIGH_RES_RESOURCE = b"\x30\x00\x00"


def missing_image_bytes(stream: BinaryIO) -> int:
    """How many bytes of image data a VTF lacks versus what its header declares (0 = complete).

    Some tools cut sprays short to squeeze them under TF2's size limit, and TF2 can't load
    such files. Raises ``ValueError`` when the header can't be parsed.
    """
    head = stream.read(80)
    if len(head) < 64 or head[:4] != b"VTF\x00":
        raise ValueError("Not a VTF file.")
    try:
        minor = struct.unpack_from("<I", head, 8)[0]
        header_size, width, height, flags, frames = struct.unpack_from("<I2HIH", head, 12)
        high = _srcvtf.FORMAT_ORDER[struct.unpack_from("<i", head, 52)[0]]
        low = _srcvtf.FORMAT_ORDER[struct.unpack_from("<i", head, 57)[0]]
        mips, low_width, low_height = head[56], head[61], head[62]
        depth = struct.unpack_from("<H", head, 63)[0] if minor >= 2 else 1
        if flags & _FLAG_ENVMAP or depth > 1:
            return 0  # Cubemaps and volume textures are never sprays.
        if minor >= 3:
            # 7.3+ files list their data blocks in a resource directory after the header.
            count = struct.unpack_from("<I", head, 68)[0]
            stream.seek(80)
            entries = (struct.unpack("<3sxI", stream.read(8)) for _ in range(count))
            offset = next(data for tag, data in entries if tag == _HIGH_RES_RESOURCE)
        else:
            offset = header_size + low.frame_size(low_width, low_height)
    except (KeyError, StopIteration, struct.error) as exc:
        raise ValueError("Unreadable VTF header.") from exc
    size = frames * sum(
        high.frame_size(max(width >> level, 1), max(height >> level, 1)) for level in range(mips)
    )
    return max(0, offset + size - stream.seek(0, 2))
