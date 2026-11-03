"""Tests for image geometry, chroma keying, and the spray-builder pipeline."""
from __future__ import annotations

import io

import numpy as np
import pytest
from srctools.vtf import VTF

from app.config import MAX_VTF_BYTES
from app.services import imageproc
from app.services.imageproc import FitMode, chroma_key, fit_square, has_alpha, load_rgba
from app.services.spray_builder import ConvertOptions, build_spray
from app.services.vtf_writer import VtfFormat
from conftest import gradient_frame


def _png_bytes(arr: np.ndarray) -> bytes:
    return imageproc.rgba_to_png(arr)


def test_load_rgba_roundtrip():
    arr = gradient_frame(40, 30)
    decoded = load_rgba(_png_bytes(arr))
    assert decoded.shape == (30, 40, 4)


@pytest.mark.parametrize("mode", list(FitMode))
def test_fit_square_produces_square(mode):
    arr = gradient_frame(200, 100)
    out = fit_square(arr, 128, mode)
    assert out.shape == (128, 128, 4)


def test_letterbox_pads_transparent():
    arr = gradient_frame(200, 100)  # wide -> vertical padding
    out = fit_square(arr, 128, FitMode.LETTERBOX, pad_color=(0, 0, 0, 0))
    # Top and bottom rows should be fully transparent padding.
    assert out[0, :, 3].max() == 0
    assert out[-1, :, 3].max() == 0


def test_crop_fills_square():
    arr = gradient_frame(200, 100)
    out = fit_square(arr, 128, FitMode.CROP)
    # Cover mode leaves no transparent padding.
    assert out[:, :, 3].min() == 255


def test_has_alpha_detection():
    assert not has_alpha(gradient_frame(16, 16, alpha=False))
    assert has_alpha(gradient_frame(16, 16, alpha=True))


def test_chroma_key_removes_background():
    arr = np.zeros((16, 16, 4), np.uint8)
    arr[:, :, 1] = 255  # green screen
    arr[:, :, 3] = 255
    arr[4:12, 4:12, 0] = 255  # red square subject
    arr[4:12, 4:12, 1] = 0
    keyed = chroma_key(arr, (0, 255, 0), tolerance=40, softness=10)
    assert keyed[0, 0, 3] == 0       # background removed
    assert keyed[8, 8, 3] == 255     # subject kept


def test_crop_normalized_region():
    arr = gradient_frame(100, 80)
    cropped = imageproc.crop_normalized(arr, 0.25, 0.5, 0.5, 0.5)
    # x: 25..75 (50px), y: 40..80 (40px)
    assert cropped.shape == (40, 50, 4)


def test_crop_normalized_clamped_to_bounds():
    arr = gradient_frame(100, 80)
    cropped = imageproc.crop_normalized(arr, 0.9, 0.9, 0.5, 0.5)
    assert cropped.shape[0] >= 1 and cropped.shape[1] >= 1
    assert cropped.shape[0] <= 80 and cropped.shape[1] <= 100


def test_build_spray_with_crop():
    res = build_spray([gradient_frame(400, 200)], ConvertOptions(name="c", crop=(0.25, 0.0, 0.5, 1.0)))
    assert res.width == res.height
    assert res.size_bytes < MAX_VTF_BYTES


def test_pad_alpha_uses_dxt5_with_transparent_bars():
    # An opaque wide source with transparent padding must force DXT5 and the
    # letterbox bars must be fully transparent (keeps aspect ratio in-game).
    res = build_spray([gradient_frame(400, 200)], ConvertOptions(name="p", fit_mode=FitMode.PAD_ALPHA))
    assert res.fmt == "DXT5"
    top_alpha = res.fitted_frames[0][0, :, 3]
    assert int(top_alpha.max()) == 0


def test_build_static_spray_opaque():
    res = build_spray([gradient_frame(300, 300)], ConvertOptions(name="My Spray!"))
    assert res.fmt == "DXT1"
    assert res.width == res.height
    assert res.size_bytes < MAX_VTF_BYTES
    assert res.name == "My_Spray"
    vtf = VTF.read(io.BytesIO(res.vtf))
    assert vtf.frame_count == 1
    assert "vgui/logos/My_Spray" in res.vmt


def test_build_static_spray_with_alpha_uses_dxt5():
    res = build_spray([gradient_frame(256, 256, alpha=True)], ConvertOptions())
    assert res.fmt == "DXT5"
    assert res.size_bytes < MAX_VTF_BYTES


def test_build_animated_spray():
    frames = [gradient_frame(128, 128, shift=s) for s in range(0, 128, 16)]
    res = build_spray(frames, ConvertOptions(name="anim"))
    assert res.frame_count == len(frames)
    assert res.size_bytes < MAX_VTF_BYTES
    vtf = VTF.read(io.BytesIO(res.vtf))
    assert vtf.frame_count == len(frames)


def test_fading_spray_enables_mipmaps():
    near = gradient_frame(256, 256)
    far = gradient_frame(256, 256, shift=64)
    res = build_spray([near], ConvertOptions(name="fade", fade_image=far, fade_from_level=2))
    assert res.mipmaps is True
    vtf = VTF.read(io.BytesIO(res.vtf))
    assert vtf.mipmap_count > 1
    assert res.size_bytes < MAX_VTF_BYTES
