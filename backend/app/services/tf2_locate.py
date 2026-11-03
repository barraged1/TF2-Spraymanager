"""Locate a local Team Fortress 2 install and its spray ``logos`` folder.

On Windows this reads the Steam path from the registry, parses Steam's
``libraryfolders.vdf`` to enumerate every library, and looks for the TF2 content
folder (app 440). The result is where finished sprays can be saved directly.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from srctools import Keyvalues

from ..config import settings
from .vmt_writer import build_ui_vmt, sanitize_spray_name

_TF2_RELATIVE = Path("steamapps") / "common" / "Team Fortress 2"
_LOGOS_RELATIVE = Path("tf") / "materials" / "vgui" / "logos"


@dataclass(slots=True)
class Tf2Location:
    tf2_dir: Path
    logos_dir: Path

    def as_dict(self) -> dict:
        return {
            "tf2_dir": str(self.tf2_dir),
            "logos_dir": str(self.logos_dir),
        }


def find_steam_path() -> Optional[Path]:
    """Read the Steam install directory from the Windows registry."""
    if sys.platform != "win32":
        return None
    import winreg

    candidates = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for hive, key, value in candidates:
        try:
            with winreg.OpenKey(hive, key) as handle:
                raw, _ = winreg.QueryValueEx(handle, value)
        except OSError:
            continue
        path = Path(raw)
        if path.exists():
            return path
    return None


def parse_library_paths(vdf_text: str) -> list[Path]:
    """Extract library ``path`` entries from ``libraryfolders.vdf`` text."""
    paths: list[Path] = []
    try:
        kv = Keyvalues.parse(vdf_text, "libraryfolders.vdf")
    except Exception:
        return paths
    root = kv.find_key("libraryfolders", or_blank=True)
    for child in root:
        if not child.has_children():
            continue
        path_val = child.find_key("path", or_blank=True).value
        if path_val:
            paths.append(Path(path_val))
    return paths


def find_library_paths(steam_path: Path) -> list[Path]:
    """Return all Steam library roots, including the base install."""
    libs = [steam_path]
    vdf = steam_path / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            libs.extend(parse_library_paths(vdf.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            pass
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for lib in libs:
        key = str(lib).lower()
        if key not in seen:
            seen.add(key)
            unique.append(lib)
    return unique


def _tf2_from_library(library: Path) -> Optional[Path]:
    tf2 = library / _TF2_RELATIVE
    return tf2 if tf2.is_dir() else None


def find_tf2(
    steam_path: Optional[Path] = None,
    *,
    extra_libraries: Optional[list[Path]] = None,
) -> Optional[Tf2Location]:
    """Locate the TF2 install, returning its directory and logos folder."""
    if steam_path is None and extra_libraries is None and settings.tf2_dir_override:
        tf2 = settings.tf2_dir_override
        return Tf2Location(tf2_dir=tf2, logos_dir=tf2 / _LOGOS_RELATIVE) if tf2.is_dir() else None

    libraries: list[Path] = []
    steam_path = steam_path or find_steam_path()
    if steam_path:
        libraries.extend(find_library_paths(steam_path))
    if extra_libraries:
        libraries.extend(extra_libraries)

    for library in libraries:
        tf2 = _tf2_from_library(library)
        if tf2:
            return Tf2Location(tf2_dir=tf2, logos_dir=tf2 / _LOGOS_RELATIVE)
    return None


def save_spray_to_tf2(
    location: Tf2Location,
    name: str,
    vtf_bytes: bytes,
    vmt_text: Optional[str] = None,
    *,
    overwrite: bool = False,
) -> dict:
    """Write the ``.vtf`` (plus its VMTs) into the logos folder.

    :raises FileExistsError: if a spray with that name exists and ``overwrite`` is False.
    """
    location.logos_dir.mkdir(parents=True, exist_ok=True)
    base = sanitize_spray_name(name)
    vtf_path = location.logos_dir / f"{base}.vtf"
    if vtf_path.exists() and not overwrite:
        raise FileExistsError(f"A spray named '{base}' already exists.")
    vtf_path.write_bytes(vtf_bytes)
    saved = {"vtf": str(vtf_path), "filename": vtf_path.name}
    if vmt_text is not None:
        vmt_path = location.logos_dir / f"{base}.vmt"
        vmt_path.write_text(vmt_text, encoding="utf-8")
        saved["vmt"] = str(vmt_path)
    # TF2's in-game spray picker shows thumbnails from logos/ui/<name>.vmt.
    ui_path = location.logos_dir / "ui" / f"{base}.vmt"
    ui_path.parent.mkdir(exist_ok=True)
    ui_path.write_text(build_ui_vmt(base), encoding="utf-8")
    saved["ui_vmt"] = str(ui_path)
    return saved
