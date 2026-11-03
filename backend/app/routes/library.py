"""Routes for viewing and managing the sprays installed in TF2."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from ..config import MAX_VTF_BYTES
from ..models import IncludeToggle, RotationToggle, StartSpray
from ..services import library, spray_randomizer, tf2_locate
from ..services.library import LibraryError
from ..services.tf2_locate import Tf2Location

router = APIRouter(prefix="/api/library", tags=["library"])


def _location() -> Tf2Location:
    loc = tf2_locate.find_tf2()
    if loc is None:
        raise LibraryError("Team Fortress 2 install was not found.", 404)
    return loc


@router.get("")
def get_library() -> dict:
    loc = tf2_locate.find_tf2()
    if loc is None:
        return {"tf2_found": False, "sprays": [], "rotation": {"installed": False, "count": 0}}
    return library.list_library(loc)


@router.get("/sprays/{filename}/preview")
def spray_preview(filename: str, size: Literal["thumb", "full"] = "thumb") -> FileResponse:
    path = library.spray_path(_location(), filename)
    return FileResponse(
        library.preview_file(path, size),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/sprays/{filename}/download")
def spray_download(filename: str) -> FileResponse:
    path = library.spray_path(_location(), filename)
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@router.delete("/sprays/{filename}")
def spray_delete(filename: str) -> dict:
    return {"ok": True, "trash_id": library.delete_spray(_location(), filename)}


@router.post("/trash/{trash_id}/restore")
def spray_restore(trash_id: str) -> dict:
    return {"ok": True, "filename": library.restore_spray(_location(), trash_id)}


@router.post("/import")
async def import_sprays(files: list[UploadFile] = File(...)) -> dict:
    loc = _location()
    # Read at most one byte past the limit; anything that long is rejected anyway.
    uploads = [(f.filename or "spray.vtf", await f.read(MAX_VTF_BYTES + 1)) for f in files]
    imported, errors = library.import_vtfs(loc, uploads)
    return {"imported": imported, "errors": errors}


@router.put("/sprays/{filename}/rotation")
def spray_rotation(filename: str, req: IncludeToggle) -> dict:
    loc = _location()
    path = library.spray_path(loc, filename)
    spray_randomizer.set_included(loc.tf2_dir, path.name, req.included)
    return {"ok": True, "included": req.included, "rotation": library.rotation_status(loc)}


def _require_tf2_closed() -> None:
    if spray_randomizer.tf2_running():
        raise LibraryError(
            "Close TF2 first — it saves its key bindings when it quits and would undo this change.", 409
        )


@router.put("/rotation")
def set_rotation(req: RotationToggle) -> dict:
    loc = _location()
    if req.enabled:
        try:
            spray_randomizer.install(loc.tf2_dir)
        except ValueError as exc:
            raise LibraryError(str(exc)) from exc
    else:
        _require_tf2_closed()
        spray_randomizer.uninstall(loc.tf2_dir)
    return library.rotation_status(loc)


@router.put("/rotation/step-keys")
def set_step_keys(req: RotationToggle) -> dict:
    loc = _location()
    spray_randomizer.set_step_keys(loc.tf2_dir, req.enabled)
    return library.rotation_status(loc)


@router.put("/rotation/verbose")
def set_verbose(req: RotationToggle) -> dict:
    loc = _location()
    spray_randomizer.set_verbose(loc.tf2_dir, req.enabled)
    return library.rotation_status(loc)


@router.post("/rotation/shuffle")
def shuffle_rotation() -> dict:
    loc = _location()
    if not spray_randomizer.refresh(loc.tf2_dir):
        raise LibraryError("Turn on the random spray rotation first.", 409)
    return library.rotation_status(loc)


@router.put("/rotation/start")
def set_start_spray(req: StartSpray) -> dict:
    loc = _location()
    filename = None
    if req.filename:
        path = library.spray_path(loc, req.filename)
        if not spray_randomizer.rotation_safe(path):
            raise LibraryError(
                "This spray can't start the rotation (its name has spaces or symbols, "
                "or the file is damaged, unreadable or over 512 KB)."
            )
        filename = path.name
    spray_randomizer.set_start(loc.tf2_dir, filename)
    return library.rotation_status(loc)
