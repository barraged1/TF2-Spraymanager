"""Tests for TF2 install detection and saving sprays into the logos folder."""
from __future__ import annotations

from pathlib import Path

from app.services.tf2_locate import (
    find_tf2,
    parse_library_paths,
    save_spray_to_tf2,
)


def test_parse_library_paths():
    vdf = """
    "libraryfolders"
    {
        "0"
        {
            "path"  "C:/Program Files (x86)/Steam"
            "apps"  { "440" "123" }
        }
        "1"
        {
            "path"  "D:/SteamLibrary"
        }
    }
    """
    paths = parse_library_paths(vdf)
    assert Path("C:/Program Files (x86)/Steam") in paths
    assert Path("D:/SteamLibrary") in paths


def _make_steam_with_tf2(root: Path) -> tuple[Path, Path]:
    steam = root / "Steam"
    library = root / "GamesLibrary"
    (steam / "steamapps").mkdir(parents=True)
    tf_dir = library / "steamapps" / "common" / "Team Fortress 2" / "tf"
    tf_dir.mkdir(parents=True)
    vdf = f"""
    "libraryfolders"
    {{
        "0" {{ "path" "{steam.as_posix()}" }}
        "1" {{ "path" "{library.as_posix()}" }}
    }}
    """
    (steam / "steamapps" / "libraryfolders.vdf").write_text(vdf, encoding="utf-8")
    return steam, library


def test_find_tf2_via_library(tmp_path):
    steam, library = _make_steam_with_tf2(tmp_path)
    loc = find_tf2(steam_path=steam)
    assert loc is not None
    assert loc.tf2_dir == library / "steamapps" / "common" / "Team Fortress 2"
    assert loc.logos_dir.name == "logos"
    assert loc.logos_dir.parts[-3:] == ("vgui", "logos") or "logos" in loc.logos_dir.parts


def test_find_tf2_missing(tmp_path):
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text('"libraryfolders" {}', encoding="utf-8")
    assert find_tf2(steam_path=steam) is None


def test_save_spray_to_tf2(tmp_path):
    steam, _ = _make_steam_with_tf2(tmp_path)
    loc = find_tf2(steam_path=steam)
    saved = save_spray_to_tf2(loc, "Cool Spray!", b"VTF\x00data", '"UnlitGeneric"{}')
    assert Path(saved["vtf"]).exists()
    assert Path(saved["vtf"]).name == "Cool_Spray.vtf"
    assert Path(saved["vmt"]).exists()
