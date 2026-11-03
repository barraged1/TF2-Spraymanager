"""Browse and manage the sprays installed in TF2's ``materials/vgui/logos`` folder."""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image
from srctools.vtf import VTF

from ..config import DEFAULT_SPRAY_FPS, MAX_VTF_BYTES, settings
from . import spray_randomizer
from .tf2_locate import Tf2Location, save_spray_to_tf2
from .vmt_writer import build_vmt, sanitize_spray_name
from .vtf_writer import missing_image_bytes

PREVIEW_EDGES = {"thumb": 192, "full": 512}
_MAX_PREVIEW_FRAMES = 120
_TRASH_ID = re.compile(r"^[0-9a-f]{32}$")
_LOGOFILE = re.compile(
    r'^\s*cl_logofile\s+"?materials/vgui/logos/([^"\r\n]+?)"?\s*$', re.IGNORECASE | re.MULTILINE
)


class LibraryError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(slots=True)
class SprayInfo:
    filename: str
    name: str
    size_bytes: int
    modified: float
    valid: bool = False
    width: int = 0
    height: int = 0
    frames: int = 0
    format: str = ""
    mipmaps: int = 0
    missing_bytes: int = 0


def read_info(path: Path) -> SprayInfo:
    stat = path.stat()
    info = SprayInfo(path.name, path.stem, stat.st_size, stat.st_mtime)
    try:
        with path.open("rb") as stream:
            vtf = VTF.read(stream, header_only=True)
            stream.seek(0)
            missing = missing_image_bytes(stream)
    except Exception:  # noqa: BLE001 - arbitrary files can sit in the logos folder
        return info
    info.valid = True
    info.width, info.height = vtf.width, vtf.height
    info.frames = vtf.frame_count
    info.format = vtf.format.name
    info.mipmaps = vtf.mipmap_count
    info.missing_bytes = missing
    return info


def current_spray(tf2_dir: Path) -> str | None:
    """The spray TF2 last saved as ``cl_logofile`` in config.cfg."""
    config = tf2_dir / "tf" / "cfg" / "config.cfg"
    if not config.exists():
        return None
    match = _LOGOFILE.search(config.read_text(encoding="utf-8", errors="ignore"))
    return match.group(1) if match else None


def rotation_status(loc: Tf2Location) -> dict:
    start = spray_randomizer.read_start(loc.tf2_dir)
    return {
        "installed": spray_randomizer.is_installed(loc.tf2_dir),
        "count": len(spray_randomizer.eligible_sprays(loc.tf2_dir)),
        "start": start.name if start else None,
        "step_keys": spray_randomizer.step_keys_enabled(loc.tf2_dir),
        "verbose": spray_randomizer.verbose_enabled(loc.tf2_dir),
    }


def list_library(loc: Tf2Location) -> dict:
    current = (current_spray(loc.tf2_dir) or "").lower()
    excluded = spray_randomizer.read_exclusions(loc.tf2_dir)
    sprays = []
    for path in sorted(loc.logos_dir.glob("*.vtf"), key=lambda p: p.name.lower()):
        info = read_info(path)
        entry = asdict(info)
        entry.update(
            over_limit=info.size_bytes >= MAX_VTF_BYTES,
            is_current=path.name.lower() == current,
            rotation_ok=spray_randomizer.rotation_safe(path),
            rotation_included=path.name.lower() not in excluded,
        )
        sprays.append(entry)
    return {
        "tf2_found": True,
        "logos_dir": str(loc.logos_dir),
        "sprays": sprays,
        "rotation": rotation_status(loc),
    }


def spray_path(loc: Tf2Location, filename: str) -> Path:
    """Resolve ``filename`` to a spray inside the logos folder, rejecting traversal."""
    if Path(filename).name != filename or not filename.lower().endswith(".vtf"):
        raise LibraryError("Invalid spray file name.")
    path = loc.logos_dir / filename
    if path.resolve().parent != loc.logos_dir.resolve() or not path.is_file():
        raise LibraryError("Spray not found.", 404)
    return path


def render_preview(path: Path, max_edge: int) -> bytes:
    """Decode a VTF into a (possibly animated) WebP that looks like it does in-game.

    Frames after a cut-off point in a damaged file are left out.
    """
    images: list[Image.Image] = []
    stride = 1
    try:
        with path.open("rb") as stream:
            vtf = VTF.read(stream)
            stride = -(-vtf.frame_count // _MAX_PREVIEW_FRAMES)
            for index in range(0, vtf.frame_count, stride):
                images.append(vtf.get(frame=index).to_PIL())
    except Exception:  # noqa: BLE001 - corrupt/unsupported textures; keep frames that decoded
        pass
    if not images:
        raise LibraryError(f"{path.name} is not a readable VTF texture.", 422)

    # TF2 stretches every spray to a square, so previews do too.
    edge = min(max_edge, max(images[0].size))
    frames = [image.resize((edge, edge), Image.LANCZOS) for image in images]
    buf = io.BytesIO()
    if len(frames) == 1:
        frames[0].save(buf, format="WEBP", quality=90)
    else:
        frames[0].save(
            buf,
            format="WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=round(1000 / DEFAULT_SPRAY_FPS) * stride,
            loop=0,
            quality=85,
        )
    return buf.getvalue()


def preview_file(path: Path, size: str) -> Path:
    edge = PREVIEW_EDGES[size]
    stat = path.stat()
    key = hashlib.sha1(
        f"{path.name.lower()}|{stat.st_mtime_ns}|{stat.st_size}|{edge}".encode()
    ).hexdigest()
    cached = settings.library_cache_dir / f"{key}.webp"
    if not cached.exists():
        data = render_preview(path, edge)
        cached.parent.mkdir(parents=True, exist_ok=True)
        temporary = cached.with_name(f"{key}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(data)
        temporary.replace(cached)
    return cached


def _find_case_insensitive(folder: Path, name: str) -> Path | None:
    if not folder.is_dir():
        return None
    wanted = name.lower()
    return next((p for p in folder.iterdir() if p.is_file() and p.name.lower() == wanted), None)


def _companions(loc: Tf2Location, vtf: Path) -> list[tuple[Path, str]]:
    """The spray plus the VMTs TF2 keeps beside it, as (path, path relative to logos)."""
    files = [(vtf, vtf.name)]
    for folder, prefix in ((loc.logos_dir, ""), (loc.logos_dir / "ui", "ui/")):
        match = _find_case_insensitive(folder, f"{vtf.stem}.vmt")
        if match:
            files.append((match, prefix + match.name))
    return files


def _write_manifest(folder: Path, files: list[str]) -> None:
    (folder / "manifest.json").write_text(
        json.dumps({"files": files, "deleted": time.time()}), encoding="utf-8"
    )


def delete_spray(loc: Tf2Location, filename: str) -> str:
    """Move a spray and its VMTs to the trash; returns an id that can restore it."""
    path = spray_path(loc, filename)
    trash_id = uuid.uuid4().hex
    folder = settings.trash_dir / trash_id
    folder.mkdir(parents=True)
    moved: list[str] = []
    for source, relative in _companions(loc, path):
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(target))
        except OSError as exc:
            if moved:
                _write_manifest(folder, moved)
            else:
                shutil.rmtree(folder, ignore_errors=True)
            raise LibraryError(
                f"Could not delete {source.name} ({exc.strerror}). Close anything using it and retry.",
                409,
            ) from exc
        moved.append(relative)
    _write_manifest(folder, moved)
    spray_randomizer.refresh(loc.tf2_dir)
    return trash_id


def restore_spray(loc: Tf2Location, trash_id: str) -> str:
    if not _TRASH_ID.fullmatch(trash_id):
        raise LibraryError("Invalid trash id.")
    folder = settings.trash_dir / trash_id
    manifest = folder / "manifest.json"
    if not manifest.is_file():
        raise LibraryError("That spray is no longer in the trash.", 404)
    files = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    moves = []
    for relative in files:
        parts = Path(relative).parts
        if Path(relative).is_absolute() or ".." in parts or len(parts) > 2:
            raise LibraryError("Corrupt trash entry.", 422)
        destination = loc.logos_dir / relative
        if destination.exists():
            raise LibraryError(f"A spray named {Path(relative).stem} already exists.", 409)
        moves.append((folder / relative, destination))
    for source, destination in moves:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    shutil.rmtree(folder, ignore_errors=True)
    spray_randomizer.refresh(loc.tf2_dir)
    return next(Path(relative).name for relative in files if relative.lower().endswith(".vtf"))


def purge_trash(max_age_s: float = 7 * 24 * 3600) -> int:
    if not settings.trash_dir.is_dir():
        return 0
    removed = 0
    for folder in settings.trash_dir.iterdir():
        if folder.is_dir() and _TRASH_ID.fullmatch(folder.name):
            if time.time() - folder.stat().st_mtime > max_age_s:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
    return removed


def _unique_stem(loc: Tf2Location, base: str) -> str:
    existing = {path.stem.lower() for path in loc.logos_dir.glob("*.vtf")}
    candidate, number = base, 2
    while candidate.lower() in existing:
        candidate = f"{base}_{number}"
        number += 1
    return candidate


def import_vtfs(loc: Tf2Location, uploads: list[tuple[str, bytes]]) -> tuple[list[str], list[str]]:
    """Copy uploaded ``.vtf`` files into the library; returns (imported names, errors)."""
    imported: list[str] = []
    errors: list[str] = []
    for filename, data in uploads:
        if not filename.lower().endswith(".vtf"):
            errors.append(f"{filename}: only .vtf files can be imported here.")
            continue
        if len(data) >= MAX_VTF_BYTES:
            errors.append(f"{filename}: 512 KB or larger, so TF2 would ignore it.")
            continue
        try:
            VTF.read(io.BytesIO(data), header_only=True)
            missing = missing_image_bytes(io.BytesIO(data))
        except Exception:  # noqa: BLE001 - untrusted upload
            errors.append(f"{filename}: not a valid VTF texture.")
            continue
        if missing:
            errors.append(
                f"{filename}: the file is cut off ({missing:,} bytes of image data missing), "
                "so TF2 can't load it."
            )
            continue
        stem = _unique_stem(loc, sanitize_spray_name(Path(filename).stem))
        save_spray_to_tf2(loc, stem, data, build_vmt(stem))
        imported.append(f"{stem}.vtf")
    if imported:
        spray_randomizer.refresh(loc.tf2_dir)
    return imported, errors
