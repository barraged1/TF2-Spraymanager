"""Tests for the installed-spray library: listing, previews, delete/restore, import, API."""
from __future__ import annotations

import io
import os
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import create_app
from app.services import library, spray_randomizer
from app.services.library import LibraryError
from app.services.tf2_locate import Tf2Location
from app.services.vtf_writer import SprayFrames, VtfFormat, encode_vtf
from conftest import gradient_frame, make_test_video


def vtf_bytes(frames: int = 1, width: int = 64, height: int = 64) -> bytes:
    images = [gradient_frame(width, height, shift=i * 4) for i in range(frames)]
    return encode_vtf(SprayFrames(frames=images), VtfFormat.DXT1)


@pytest.fixture
def tf2(tmp_path, monkeypatch) -> Tf2Location:
    root = tmp_path / "Team Fortress 2"
    logos = root / "tf" / "materials" / "vgui" / "logos"
    (logos / "ui").mkdir(parents=True)
    (root / "tf" / "cfg").mkdir(parents=True)
    monkeypatch.setattr(settings, "tf2_dir_override", root)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.ensure_dirs()
    return Tf2Location(tf2_dir=root, logos_dir=logos)


def add(loc: Tf2Location, name: str, data: bytes | None = None, vmts: bool = True) -> None:
    (loc.logos_dir / f"{name}.vtf").write_bytes(vtf_bytes() if data is None else data)
    if vmts:
        (loc.logos_dir / f"{name}.vmt").write_text("vmt")
        (loc.logos_dir / "ui" / f"{name.lower()}.vmt").write_text("ui")


def test_list_library_reports_metadata_current_and_invalid(tf2):
    add(tf2, "Static")
    add(tf2, "Anim", vtf_bytes(frames=4))
    add(tf2, "has space")
    (tf2.logos_dir / "broken.vtf").write_bytes(b"not a texture at all" * 10)
    (tf2.tf2_dir / "tf" / "cfg" / "config.cfg").write_text(
        'cl_logofile "materials/vgui/logos/Anim.vtf"\n'
    )

    data = library.list_library(tf2)
    by_name = {s["filename"]: s for s in data["sprays"]}

    assert [s["filename"] for s in data["sprays"]] == ["Anim.vtf", "broken.vtf", "has space.vtf", "Static.vtf"]
    assert by_name["Anim.vtf"]["frames"] == 4 and by_name["Anim.vtf"]["is_current"]
    assert by_name["Static.vtf"] | {"width": 64, "height": 64, "format": "DXT1", "valid": True} == by_name["Static.vtf"]
    assert by_name["broken.vtf"]["valid"] is False
    assert by_name["has space.vtf"]["rotation_ok"] is False
    assert data["rotation"] == {
        "installed": False, "count": 2, "start": None, "step_keys": False, "verbose": False
    }


def test_preview_is_square_animated_and_cached(tf2, monkeypatch):
    add(tf2, "Wide", encode_vtf(SprayFrames(frames=[gradient_frame(64, 32)]), VtfFormat.DXT1))
    add(tf2, "Anim", vtf_bytes(frames=3))

    still = Image.open(io.BytesIO(library.render_preview(tf2.logos_dir / "Wide.vtf", 512)))
    assert still.format == "WEBP" and still.size == (64, 64)
    anim = Image.open(io.BytesIO(library.render_preview(tf2.logos_dir / "Anim.vtf", 32)))
    assert anim.n_frames == 3 and anim.size == (32, 32)

    first = library.preview_file(tf2.logos_dir / "Anim.vtf", "thumb")
    monkeypatch.setattr(library, "render_preview", lambda *a: pytest.fail("cache miss"))
    assert library.preview_file(tf2.logos_dir / "Anim.vtf", "thumb") == first


def test_unreadable_vtf_preview_is_a_clean_error(tf2):
    (tf2.logos_dir / "broken.vtf").write_bytes(b"garbage")
    with pytest.raises(LibraryError) as err:
        library.render_preview(tf2.logos_dir / "broken.vtf", 64)
    assert err.value.status == 422


def test_cut_off_spray_is_flagged_partly_previewed_and_kept_out_of_rotation(tf2):
    add(tf2, "Cut", vtf_bytes(frames=3)[:-40])
    add(tf2, "Fine")

    by_name = {s["filename"]: s for s in library.list_library(tf2)["sprays"]}
    assert by_name["Cut.vtf"]["valid"] and by_name["Cut.vtf"]["missing_bytes"] == 40
    assert by_name["Cut.vtf"]["rotation_ok"] is False
    assert by_name["Fine.vtf"]["missing_bytes"] == 0 and by_name["Fine.vtf"]["rotation_ok"]
    assert [p.name for p in spray_randomizer.eligible_sprays(tf2.tf2_dir)] == ["Fine.vtf"]

    preview = Image.open(io.BytesIO(library.render_preview(tf2.logos_dir / "Cut.vtf", 64)))
    assert preview.n_frames == 2

    imported, errors = library.import_vtfs(tf2, [("cut2.vtf", vtf_bytes()[:-8])])
    assert imported == [] and "cut off" in errors[0]


@pytest.mark.parametrize("name", ["../x.vtf", "a/b.vtf", "a\\b.vtf", "x.txt", "missing.vtf"])
def test_spray_path_rejects_traversal_and_unknown(tf2, name):
    with pytest.raises(LibraryError):
        library.spray_path(tf2, name)


def test_delete_moves_companions_to_trash_and_restore_brings_them_back(tf2):
    add(tf2, "Gone")
    trash_id = library.delete_spray(tf2, "Gone.vtf")

    assert not (tf2.logos_dir / "Gone.vtf").exists()
    assert not (tf2.logos_dir / "Gone.vmt").exists()
    assert not (tf2.logos_dir / "ui" / "gone.vmt").exists()

    assert library.restore_spray(tf2, trash_id) == "Gone.vtf"
    assert (tf2.logos_dir / "Gone.vtf").exists()
    assert (tf2.logos_dir / "ui" / "gone.vmt").read_text() == "ui"
    assert not (settings.trash_dir / trash_id).exists()


def test_restore_refuses_to_overwrite(tf2):
    add(tf2, "Twin")
    trash_id = library.delete_spray(tf2, "Twin.vtf")
    add(tf2, "Twin")
    with pytest.raises(LibraryError) as err:
        library.restore_spray(tf2, trash_id)
    assert err.value.status == 409


def test_delete_keeps_rotation_valid(tf2):
    add(tf2, "Only")
    spray_randomizer.install(tf2.tf2_dir)
    library.delete_spray(tf2, "Only.vtf")
    rotation = (tf2.tf2_dir / "tf" / "cfg" / spray_randomizer.ROTATION_CFG).read_text()
    assert "Only.vtf" not in rotation
    assert 'alias easyspray_game ""' in rotation


def test_import_vtfs_validates_and_dedupes_names(tf2):
    add(tf2, "dup")
    imported, errors = library.import_vtfs(
        tf2,
        [
            ("dup.vtf", vtf_bytes()),
            ("My Spray!.vtf", vtf_bytes()),
            ("fake.vtf", b"nope"),
            ("big.vtf", b"VTF\x00" + bytes(512 * 1024)),
            ("pic.png", b"png"),
        ],
    )
    assert imported == ["dup_2.vtf", "My_Spray.vtf"]
    assert len(errors) == 3
    assert (tf2.logos_dir / "ui" / "My_Spray.vmt").exists()


def test_purge_trash_drops_only_old_entries(tf2):
    add(tf2, "Old")
    add(tf2, "New")
    old_id = library.delete_spray(tf2, "Old.vtf")
    new_id = library.delete_spray(tf2, "New.vtf")
    stale = time.time() - 30 * 24 * 3600
    os.utime(settings.trash_dir / old_id, (stale, stale))

    assert library.purge_trash() == 1
    assert (settings.trash_dir / new_id).exists()


# ------------------------------------------------------------------ API


@pytest.fixture
def client(tf2):
    return TestClient(create_app())


def test_api_library_listing_preview_download(client, tf2):
    add(tf2, "Anim", vtf_bytes(frames=2))
    listing = client.get("/api/library").json()
    assert listing["tf2_found"] is True
    assert listing["sprays"][0]["filename"] == "Anim.vtf"

    preview = client.get("/api/library/sprays/Anim.vtf/preview", params={"size": "full"})
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(preview.content)).n_frames == 2

    download = client.get("/api/library/sprays/Anim.vtf/download")
    assert download.content[:4] == b"VTF\x00"
    assert client.get("/api/library/sprays/nope.vtf/preview").status_code == 404


def test_api_library_without_tf2(client, tf2, monkeypatch):
    monkeypatch.setattr(settings, "tf2_dir_override", tf2.tf2_dir / "missing")
    assert client.get("/api/library").json()["tf2_found"] is False
    assert client.delete("/api/library/sprays/a.vtf").status_code == 404


def test_api_delete_restore_and_import(client, tf2):
    add(tf2, "Keep")
    deleted = client.delete("/api/library/sprays/Keep.vtf").json()
    assert client.get("/api/library").json()["sprays"] == []
    assert client.post(f"/api/library/trash/{deleted['trash_id']}/restore").json()["filename"] == "Keep.vtf"
    assert client.post("/api/library/trash/not-an-id/restore").status_code == 400

    resp = client.post(
        "/api/library/import",
        files=[
            ("files", ("new.vtf", vtf_bytes(), "application/octet-stream")),
            ("files", ("bad.vtf", b"bad", "application/octet-stream")),
        ],
    ).json()
    assert resp["imported"] == ["new.vtf"] and len(resp["errors"]) == 1


def test_api_rotation_controls(client, tf2):
    add(tf2, "One")
    add(tf2, "Two")
    assert client.post("/api/library/rotation/shuffle").status_code == 409

    assert client.put("/api/library/rotation", json={"enabled": True}).json() == {
        "installed": True,
        "count": 2,
        "start": None,
        "step_keys": False,
        "verbose": False,
    }
    excluded = client.put("/api/library/sprays/Two.vtf/rotation", json={"included": False}).json()
    assert excluded["rotation"]["count"] == 1
    rotation = (tf2.tf2_dir / "tf" / "cfg" / spray_randomizer.ROTATION_CFG).read_text()
    assert "Two.vtf" not in rotation and "One.vtf" in rotation
    assert client.post("/api/library/rotation/shuffle").status_code == 200

    assert client.put("/api/library/rotation", json={"enabled": False}).json()["installed"] is False


def test_api_starting_spray(client, tf2):
    add(tf2, "First")
    add(tf2, "has space")
    client.put("/api/library/rotation", json={"enabled": True})
    start = "/api/library/rotation/start"

    assert client.put(start, json={"filename": "First.vtf"}).json()["start"] == "First.vtf"
    assert client.get("/api/library").json()["rotation"]["start"] == "First.vtf"
    rotation = (tf2.tf2_dir / "tf" / "cfg" / spray_randomizer.ROTATION_CFG).read_text()
    assert rotation.rstrip().endswith("echo [EasyImport] Starting spray for this launch - First")

    assert client.put(start, json={"filename": "has space.vtf"}).status_code == 400
    assert client.put(start, json={"filename": "nope.vtf"}).status_code == 404
    assert client.put(start, json={"filename": None}).json()["start"] is None


def test_api_step_keys_and_close_tf2_guard(client, tf2, monkeypatch):
    add(tf2, "One")
    config = tf2.tf2_dir / "tf" / "cfg" / "config.cfg"
    original = 'bind "SPACE" "+jump"\nbind "t" "impulse 201"\n'
    config.write_text(original)
    client.put("/api/library/rotation", json={"enabled": True})

    # Key stepping only rewrites the rotation file, so it works while TF2 is open.
    monkeypatch.setattr(spray_randomizer, "tf2_running", lambda: True)
    assert client.put("/api/library/rotation/step-keys", json={"enabled": True}).json()["step_keys"] is True
    rotation = (tf2.tf2_dir / "tf" / "cfg" / spray_randomizer.ROTATION_CFG).read_text()
    assert 'bind "SPACE" "+jump; easyspray_cycle"' in rotation
    assert config.read_text() == original
    assert client.put("/api/library/rotation/verbose", json={"enabled": True}).json()["verbose"] is True

    assert client.put("/api/library/rotation", json={"enabled": False}).status_code == 409


def _png() -> bytes:
    buf = io.BytesIO()
    Image.fromarray(gradient_frame(120, 80), "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def test_api_save_conflict_requires_overwrite(client, tf2):
    job = client.post("/api/import/upload", files={"file": ("p.png", _png(), "image/png")}).json()["job_id"]
    client.post(f"/api/job/{job}/convert", json={"name": "mine"})

    first = client.post(f"/api/job/{job}/save-to-tf2", json={"name": "mine"})
    assert first.json()["filename"] == "mine.vtf"
    assert (tf2.logos_dir / "ui" / "mine.vmt").exists()
    assert client.post(f"/api/job/{job}/save-to-tf2", json={"name": "mine"}).status_code == 409
    assert client.post(f"/api/job/{job}/save-to-tf2", json={"name": "mine", "overwrite": True}).status_code == 200


def test_api_boomerang_and_filmstrip(client, tmp_path):
    frames = [gradient_frame(64, 64, shift=i * 6) for i in range(20)]
    with open(make_test_video(tmp_path / "clip.mp4", frames, fps=10.0), "rb") as fh:
        job = client.post("/api/import/upload", files={"file": ("clip.mp4", fh.read(), "video/mp4")}).json()["job_id"]

    opts = {"animated": True, "start": 0.0, "duration": 1.0, "fps": 5.0}
    plain = client.post(f"/api/job/{job}/convert", json=opts).json()["frame_count"]
    boomerang = client.post(f"/api/job/{job}/convert", json=opts | {"boomerang": True}).json()["frame_count"]
    assert boomerang == plain * 2 - 2
    estimate = client.post(f"/api/job/{job}/estimate", json=opts | {"boomerang": True}).json()
    assert estimate["frame_count"] == 8

    strip = client.get(f"/api/job/{job}/filmstrip")
    assert strip.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(strip.content)).size[1] == 56


def test_api_filmstrip_rejects_images(client):
    job = client.post("/api/import/upload", files={"file": ("p.png", _png(), "image/png")}).json()["job_id"]
    assert client.get(f"/api/job/{job}/filmstrip").status_code == 400
