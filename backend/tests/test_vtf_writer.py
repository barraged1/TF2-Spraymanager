"""Tests for the custom VTF writer, validated by reading output back via srctools."""
from __future__ import annotations

import io
import struct

import pytest
from srctools.vtf import VTF, ImageFormats

from app.config import MAX_VTF_BYTES
from app.services.vtf_writer import (
    SprayFrames,
    VtfFormat,
    encode_vtf,
    estimate_vtf_size,
    missing_image_bytes,
)
from conftest import gradient_frame


def _read_back(data: bytes) -> VTF:
    return VTF.read(io.BytesIO(data))


@pytest.mark.parametrize("fmt, mipmaps", [(VtfFormat.DXT1, False), (VtfFormat.DXT5, True)])
def test_missing_image_bytes_spots_cut_off_files(fmt, mipmaps):
    frames = [gradient_frame(70, 70, alpha=True, shift=i) for i in range(3)]
    data = encode_vtf(SprayFrames(frames=frames), fmt, mipmaps=mipmaps)

    assert missing_image_bytes(io.BytesIO(data)) == 0
    assert missing_image_bytes(io.BytesIO(data[:-100])) == 100


def test_missing_image_bytes_follows_the_resource_directory():
    stream = io.BytesIO()
    VTF(64, 64, (7, 4), fmt=ImageFormats.DXT1, frames=2).save(stream)
    data = stream.getvalue()

    assert missing_image_bytes(io.BytesIO(data)) == 0
    assert missing_image_bytes(io.BytesIO(data[:-8])) == 8


def test_missing_image_bytes_rejects_unparseable_headers():
    bad_format = bytearray(encode_vtf(SprayFrames(frames=[gradient_frame(8, 8)]), VtfFormat.DXT1))
    struct.pack_into("<i", bad_format, 52, 999)
    for data in (b"\x89PNG" + bytes(100), b"VTF\x00", bytes(bad_format)):
        with pytest.raises(ValueError):
            missing_image_bytes(io.BytesIO(data))


def test_static_dxt1_roundtrip():
    spray = SprayFrames(frames=[gradient_frame(64, 64)])
    data = encode_vtf(spray, VtfFormat.DXT1)

    assert data[:4] == b"VTF\x00"
    vtf = _read_back(data)
    assert (vtf.width, vtf.height) == (64, 64)
    assert vtf.frame_count == 1
    assert vtf.version == (7, 1)
    assert vtf.format is ImageFormats.DXT1
    assert len(data) < MAX_VTF_BYTES


def test_static_dxt5_alpha_roundtrip():
    spray = SprayFrames(frames=[gradient_frame(128, 128, alpha=True)])
    data = encode_vtf(spray, VtfFormat.DXT5)

    vtf = _read_back(data)
    assert (vtf.width, vtf.height) == (128, 128)
    assert vtf.format is ImageFormats.DXT5
    # Pixels should be recoverable; alpha gradient should survive roughly.
    frame = vtf.get(frame=0)
    frame.load()


def test_animated_frame_count():
    frames = [gradient_frame(64, 64, shift=s) for s in range(0, 64, 8)]
    spray = SprayFrames(frames=frames)
    data = encode_vtf(spray, VtfFormat.DXT1)

    vtf = _read_back(data)
    assert vtf.frame_count == len(frames)
    assert (vtf.width, vtf.height) == (64, 64)


def test_non_power_of_two_dimensions():
    # 1020 and 724 are the real max spray edges and are NOT powers of two.
    spray = SprayFrames(frames=[gradient_frame(1020, 1020)])
    data = encode_vtf(spray, VtfFormat.DXT1)
    vtf = _read_back(data)
    assert (vtf.width, vtf.height) == (1020, 1020)
    assert len(data) < MAX_VTF_BYTES


def test_mipmaps_increase_size_and_count():
    spray = SprayFrames(frames=[gradient_frame(256, 256)])
    flat = encode_vtf(spray, VtfFormat.DXT1, mipmaps=False)
    mipped = encode_vtf(spray, VtfFormat.DXT1, mipmaps=True)

    assert len(mipped) > len(flat)
    vtf = _read_back(mipped)
    assert vtf.mipmap_count > 1


def test_estimate_matches_actual_size():
    for fmt in (VtfFormat.DXT1, VtfFormat.DXT5):
        for mips in (False, True):
            spray = SprayFrames(frames=[gradient_frame(128, 128, alpha=fmt is VtfFormat.DXT5)])
            data = encode_vtf(spray, fmt, mipmaps=mips)
            est = estimate_vtf_size(128, 128, 1, fmt, mipmaps=mips)
            assert est == len(data), f"{fmt} mips={mips}: est {est} != actual {len(data)}"


def test_validate_rejects_mismatched_frames():
    spray = SprayFrames(frames=[gradient_frame(64, 64), gradient_frame(32, 32)])
    with pytest.raises(ValueError):
        encode_vtf(spray, VtfFormat.DXT1)


def test_low_res_thumbnail_written():
    # vtex/VTFEdit always include a DXT1 low-res thumbnail (<=16x16); verify ours.
    import struct

    spray = SprayFrames(frames=[gradient_frame(256, 256)])
    data = encode_vtf(spray, VtfFormat.DXT1)

    low_fmt = struct.unpack_from("<i", data, 57)[0]
    low_w, low_h = data[61], data[62]
    assert low_fmt == 13  # DXT1
    assert (low_w, low_h) == (16, 16)

    vtf = _read_back(data)
    assert vtf.low_format is ImageFormats.DXT1
