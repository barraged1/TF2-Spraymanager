"""End-to-end API tests using FastAPI's TestClient."""
from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import MAX_VTF_BYTES, settings
from app.main import create_app
from conftest import gradient_frame, make_test_video


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.ensure_dirs()
    yield


@pytest.fixture
def client():
    return TestClient(create_app())


def _png_bytes(width=300, height=200, alpha=False) -> bytes:
    arr = gradient_frame(width, height, alpha=alpha)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def test_health_and_config(client):
    assert client.get("/api/health").json()["status"] == "ok"
    cfg = client.get("/api/config").json()
    assert cfg["max_vtf_bytes"] == MAX_VTF_BYTES
    assert cfg["default_spray_fps"] == 5


def test_upload_image_convert_download(client):
    up = client.post(
        "/api/import/upload",
        files={"file": ("pic.png", _png_bytes(), "image/png")},
    )
    assert up.status_code == 200, up.text
    job_id = up.json()["job_id"]
    assert up.json()["media"]["kind"] == "image"

    conv = client.post(f"/api/job/{job_id}/convert", json={"name": "My Spray!"})
    assert conv.status_code == 200, conv.text
    body = conv.json()
    assert body["format"] == "DXT1"
    assert body["within_limit"] is True
    assert body["width"] == body["height"]

    vtf = client.get(f"/api/job/{job_id}/download/vtf")
    assert vtf.status_code == 200
    assert vtf.content[:4] == b"VTF\x00"
    assert len(vtf.content) < MAX_VTF_BYTES
    assert "My_Spray.vtf" in vtf.headers.get("content-disposition", "")

    vmt = client.get(f"/api/job/{job_id}/download/vmt")
    assert "UnlitGeneric" in vmt.text


def test_alpha_image_uses_dxt5(client):
    up = client.post(
        "/api/import/upload",
        files={"file": ("pic.png", _png_bytes(alpha=True), "image/png")},
    )
    job_id = up.json()["job_id"]
    conv = client.post(f"/api/job/{job_id}/convert", json={"name": "alpha"})
    assert conv.json()["format"] == "DXT5"


def test_video_upload_loops_and_animated_convert(client, tmp_path):
    frames = [gradient_frame(96, 96, shift=int(96 * (i % 10) / 10)) for i in range(30)]
    path = make_test_video(tmp_path / "clip.mp4", frames, fps=10.0)
    with open(path, "rb") as fh:
        data = fh.read()

    up = client.post("/api/import/upload", files={"file": ("clip.mp4", data, "video/mp4")})
    assert up.status_code == 200, up.text
    job_id = up.json()["job_id"]
    assert up.json()["media"]["animated"] is True

    loops = client.post(f"/api/job/{job_id}/loops", json={"analysis_fps": 10.0, "min_duration": 0.5})
    assert loops.status_code == 200
    assert "candidates" in loops.json()

    conv = client.post(
        f"/api/job/{job_id}/convert",
        json={"name": "anim", "animated": True, "start": 0.0, "duration": 1.0, "fps": 5.0},
    )
    assert conv.status_code == 200, conv.text
    body = conv.json()
    assert body["frame_count"] > 1
    assert body["within_limit"] is True
    assert body["preview_url"].endswith("result.webp")

    vtf = client.get(f"/api/job/{job_id}/download/vtf")
    assert vtf.content[:4] == b"VTF\x00"


def test_url_import_blocks_private_host(client):
    resp = client.post("/api/import/url", json={"url": "http://127.0.0.1/x.mp4"})
    assert resp.status_code == 400
    assert "non-public" in resp.json()["detail"].lower() or "host" in resp.json()["detail"].lower()


def test_frame_endpoint_returns_png(client):
    up = client.post("/api/import/upload", files={"file": ("pic.png", _png_bytes(), "image/png")})
    job_id = up.json()["job_id"]
    frame = client.get(f"/api/job/{job_id}/frame", params={"t": 0})
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/png"


def test_tf2_status_shape(client):
    resp = client.get("/api/tf2/status")
    assert resp.status_code == 200
    assert "found" in resp.json()


def test_estimate_matches_convert_for_static(client):
    up = client.post("/api/import/upload", files={"file": ("pic.png", _png_bytes(), "image/png")})
    job_id = up.json()["job_id"]

    est = client.post(f"/api/job/{job_id}/estimate", json={"animated": False}).json()
    conv = client.post(f"/api/job/{job_id}/convert", json={"animated": False}).json()

    assert est["fits"] is True
    assert est["format"] == conv["format"] == "DXT1"
    assert est["width"] == conv["width"]
    # The pre-convert estimate should exactly match the real encoded size.
    assert est["size_bytes"] == conv["size_bytes"]
    assert est["size_kib"] < 512


def test_convert_with_crop(client):
    up = client.post("/api/import/upload", files={"file": ("pic.png", _png_bytes(), "image/png")})
    job_id = up.json()["job_id"]
    conv = client.post(
        f"/api/job/{job_id}/convert",
        json={"name": "cropped", "crop": {"x": 0.15, "y": 0.05, "w": 0.7, "h": 0.7}},
    )
    assert conv.status_code == 200, conv.text
    assert conv.json()["within_limit"] is True
    assert conv.json()["width"] == conv.json()["height"]
    vtf = client.get(f"/api/job/{job_id}/download/vtf")
    assert vtf.content[:4] == b"VTF\x00"


def test_pad_alpha_forces_dxt5_in_estimate_and_convert(client):
    up = client.post("/api/import/upload", files={"file": ("pic.png", _png_bytes(), "image/png")})
    job_id = up.json()["job_id"]

    est = client.post(
        f"/api/job/{job_id}/estimate", json={"animated": False, "fit_mode": "pad_alpha"}
    ).json()
    assert est["format"] == "DXT5"

    conv = client.post(
        f"/api/job/{job_id}/convert", json={"name": "padded", "fit_mode": "pad_alpha"}
    ).json()
    assert conv["format"] == "DXT5"
    assert conv["within_limit"] is True

