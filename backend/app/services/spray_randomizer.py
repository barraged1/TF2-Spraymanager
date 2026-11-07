"""Install a TF2 config that switches to a different random spray every game."""
from __future__ import annotations

import argparse
import logging
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .tf2_locate import find_steam_path, find_tf2
from .vtf_writer import missing_image_bytes

ROTATION_CFG = "easyimport_sprays.cfg"
EXCLUDE_FILE = "easyimport_sprays_exclude.txt"
START_FILE = "easyimport_sprays_start.txt"
STEP_KEYS_FILE = "easyimport_sprays_step_keys.txt"
VERBOSE_FILE = "easyimport_sprays_verbose.txt"
MARKER = "// tf2-spray-easyimport"
CLASS_CFGS = (
    "scout", "soldier", "pyro", "demoman", "heavyweapons",
    "engineer", "medic", "sniper", "spy",
)
STEP_SUFFIX = "; easyspray_cycle"
SPRAY_COMMAND = "impulse 201"
SPRAY_BIND = f"{SPRAY_COMMAND}{STEP_SUFFIX}"
#: Frequent actions that can also move the shuffle on, so the next spray is hard to predict.
ACTION_COMMANDS = frozenset({"+jump", "lastinv", "invnext", "invprev", *(f"slot{n}" for n in range(1, 11))})
TF2_PROCESSES = ("tf_win64.exe", "tf.exe")
ECHO = "echo [EasyImport]"

log = logging.getLogger("tf2spray.rotation")

_SAFE_STEM = re.compile(r"^[A-Za-z0-9_.-]+$")
_BIND = re.compile(r'^(?P<head>bind\s+"(?P<key>[^"]+)"\s+")(?P<command>[^"]*)(?P<tail>"[^\n]*)$', re.MULTILINE)


@dataclass(slots=True)
class Hooks:
    startup: Path
    per_game: list[Path]


def _cfg_dir(tf2_dir: Path) -> Path:
    return tf2_dir / "tf" / "cfg"


def rotation_safe(path: Path) -> bool:
    # Names go unquoted inside alias strings, so spaces/semicolons would break the script.
    if not _SAFE_STEM.fullmatch(path.stem):
        return False
    if not 64 <= path.stat().st_size < 512 * 1024:
        return False
    # A cut-off file can't be loaded by TF2, which would leave you without a spray that game.
    with path.open("rb") as stream:
        try:
            return missing_image_bytes(stream) == 0
        except ValueError:
            return False


def read_exclusions(tf2_dir: Path) -> set[str]:
    path = _cfg_dir(tf2_dir) / EXCLUDE_FILE
    if not path.exists():
        return set()
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return {line.strip().lower() for line in lines if line.strip()}


def eligible_sprays(tf2_dir: Path) -> list[Path]:
    logos = tf2_dir / "tf" / "materials" / "vgui" / "logos"
    excluded = read_exclusions(tf2_dir)
    return [
        path for path in sorted(logos.glob("*.vtf"))
        if path.name.lower() not in excluded and rotation_safe(path)
    ]


def is_installed(tf2_dir: Path) -> bool:
    return (_cfg_dir(tf2_dir) / ROTATION_CFG).exists()


def read_start(tf2_dir: Path) -> Path | None:
    """The spray every game launch should open with, if one is set and still usable."""
    path = _cfg_dir(tf2_dir) / START_FILE
    if not path.exists():
        return None
    name = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not name or Path(name).name != name:
        return None
    spray = tf2_dir / "tf" / "materials" / "vgui" / "logos" / name
    return spray if spray.is_file() and rotation_safe(spray) else None


def set_start(tf2_dir: Path, filename: str | None) -> None:
    path = _cfg_dir(tf2_dir) / START_FILE
    if filename:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{filename}\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    refresh(tf2_dir)


def set_included(tf2_dir: Path, filename: str, included: bool) -> None:
    excluded = read_exclusions(tf2_dir)
    if included:
        excluded.discard(filename.lower())
    else:
        excluded.add(filename.lower())
    path = _cfg_dir(tf2_dir) / EXCLUDE_FILE
    if excluded:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{name}\n" for name in sorted(excluded)), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    refresh(tf2_dir)


def hook_files(tf2_dir: Path) -> Hooks:
    cfg = _cfg_dir(tf2_dir)
    # mastercomfig's VPK replaces autoexec and class cfgs; these are its user hooks.
    if any((tf2_dir / "tf" / "custom").glob("mastercomfig*")):
        return Hooks(cfg / "overrides" / "autoexec.cfg", [cfg / "overrides" / "game_overrides.cfg"])
    return Hooks(cfg / "autoexec.cfg", [cfg / f"{name}.cfg" for name in CLASS_CFGS])


def config_files(tf2_dir: Path) -> list[Path]:
    """TF2's config.cfg plus its Steam Cloud copies; with Steam Cloud on, TF2 loads binds from those."""
    files = [_cfg_dir(tf2_dir) / "config.cfg"]
    steam = find_steam_path() if tf2_dir.parent.parent.name.lower() == "steamapps" else None
    if steam:
        files.extend(sorted((steam / "userdata").glob("*/440/remote/cfg/config.cfg")))
    return [path for path in files if path.is_file()]


def _current_binds(tf2_dir: Path) -> list[tuple[str, str]]:
    files = config_files(tf2_dir)
    if not files:
        return []
    newest = max(files, key=lambda path: path.stat().st_mtime)
    return [(m["key"], m["command"]) for m in _BIND.finditer(newest.read_text(encoding="utf-8", errors="ignore"))]


def _keys_stepped_by_rotation(tf2_dir: Path) -> set[str]:
    path = _cfg_dir(tf2_dir) / ROTATION_CFG
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {m["key"] for m in _BIND.finditer(text) if m["command"].endswith(STEP_SUFFIX)}


def key_binds(tf2_dir: Path) -> list[tuple[str, str]]:
    """The (key, command) binds the rotation applies at every launch.

    Each stepping bind keeps the key's own command first, so the key still works even if the
    rotation is removed. Binding at launch also beats Steam Cloud restoring an older config.cfg.
    """
    stepped = {SPRAY_COMMAND, *ACTION_COMMANDS} if step_keys_enabled(tf2_dir) else {SPRAY_COMMAND}
    previously_stepped = _keys_stepped_by_rotation(tf2_dir)
    binds = []
    for key, command in _current_binds(tf2_dir):
        base = command.removesuffix(STEP_SUFFIX)
        if base.lower() in stepped:
            binds.append((key, base + STEP_SUFFIX))
        elif base.lower() in ACTION_COMMANDS and (command != base or key in previously_stepped):
            # Stepping was turned off, but TF2 may still hold or have saved the stepping bind.
            binds.append((key, base))
    return binds


def tf2_running() -> bool:
    """Whether TF2 is open; it rewrites config.cfg's key bindings when it quits."""
    if sys.platform != "win32":
        return False
    try:
        listing = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="ignore",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return any(f'"{name}"' in listing for name in TF2_PROCESSES)


def step_keys_enabled(tf2_dir: Path) -> bool:
    return (_cfg_dir(tf2_dir) / STEP_KEYS_FILE).exists()


def verbose_enabled(tf2_dir: Path) -> bool:
    return (_cfg_dir(tf2_dir) / VERBOSE_FILE).exists()


def set_verbose(tf2_dir: Path, enabled: bool) -> None:
    path = _cfg_dir(tf2_dir) / VERBOSE_FILE
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Log every rotation step in TF2's console.\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    refresh(tf2_dir)


def set_step_keys(tf2_dir: Path, enabled: bool) -> None:
    path = _cfg_dir(tf2_dir) / STEP_KEYS_FILE
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Jump and weapon-switch keys also move the spray rotation on.\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    refresh(tf2_dir)


def _strip_stepping(tf2_dir: Path) -> None:
    """Remove stepping from every config.cfg copy so keys don't call a missing alias."""
    for config in config_files(tf2_dir):
        text = config.read_text(encoding="utf-8", errors="surrogateescape")
        updated = _BIND.sub(
            lambda m: f"{m['head']}{m['command'].removesuffix(STEP_SUFFIX)}{m['tail']}", text
        )
        if updated != text:
            config.write_text(updated, encoding="utf-8", errors="surrogateescape")
            log.info("Removed rotation stepping from key binds in %s", config)


def build_rotation(
    sprays: list[Path],
    rng: random.Random,
    start: Path | None = None,
    *,
    binds: list[tuple[str, str]] | None = None,
    verbose: bool = False,
) -> str:
    # TF2 forgets alias state between launches, so a chosen opener is applied directly.
    opening = (
        [f"cl_logofile materials/vgui/logos/{start.name}", f"{ECHO} Starting spray for this launch - {start.stem}"]
        if start
        else []
    )
    bind_lines = [f'bind "{key}" "{command}"' for key, command in binds or []]
    if not sprays:
        # Keep the hooks and spray bind valid while nothing is in the rotation.
        return (
            "// Generated by TF2 Spray EasyImport. No sprays are in the rotation.\n"
            'alias easyspray_cycle ""\nalias easyspray_game ""\n'
            + "".join(f"{line}\n" for line in bind_lines + opening)
        )
    order = list(sprays)
    rng.shuffle(order)
    if start in order:
        # The opener just played, so it shouldn't come straight back on the next map.
        order.remove(start)
        order.append(start)
    count = len(order)
    lines = [
        "// Generated by TF2 Spray EasyImport. Reshuffle from the app's My Sprays page "
        "(or re-run install_random_sprays.bat)."
    ]
    for i, spray in enumerate(order):
        # Few, self-describing words: TF2 prints each echo word separately and can jumble them.
        step = f"; {ECHO} step={i + 1}/{count} next-map-spray={spray.stem}" if verbose else ""
        # Every step sets the spray right away; TF2 sends it whenever a map loads (a map change
        # or a new server), so wherever your key presses leave off is what the next map gets.
        lines.append(
            f'alias easyspray_c{i} "alias easyspray_cycle easyspray_c{(i + 1) % count}; '
            f'alias easyspray_status easyspray_n{i}; cl_logofile materials/vgui/logos/{spray.name}{step}"'
        )
        lines.append(f'alias easyspray_n{i} "{ECHO} next-map-spray={spray.stem} position={i + 1}/{count}"')
    lines.append('alias easyspray_game "easyspray_cycle; easyspray_status"')
    lines.extend(bind_lines)
    detail = " - logging every step" if verbose else ""
    lines.append(f"{ECHO} Spray rotation loaded - {count} sprays in a shuffled order{detail}")
    stepping = [key for key, command in binds or [] if command.endswith(STEP_SUFFIX)]
    if verbose and stepping:
        lines.append(f"{ECHO} Keys that move it on - {', '.join(stepping)}")
    lines.append("easyspray_c0")
    lines.extend(opening or ["easyspray_status"])
    return "\n".join(lines) + "\n"


def _write_rotation(tf2_dir: Path, rng: random.Random, *, allow_empty: bool = False) -> tuple[int, list[str]]:
    sprays = eligible_sprays(tf2_dir)
    if not sprays and not allow_empty:
        raise ValueError("No eligible .vtf sprays found in materials/vgui/logos.")
    target = _cfg_dir(tf2_dir) / ROTATION_CFG
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".cfg.tmp")
    start, verbose, binds = read_start(tf2_dir), verbose_enabled(tf2_dir), key_binds(tf2_dir)
    temporary.write_text(build_rotation(sprays, rng, start, binds=binds, verbose=verbose), encoding="utf-8")
    temporary.replace(target)
    stepping = [key for key, command in binds if command.endswith(STEP_SUFFIX)]
    log.info(
        "Spray rotation written: %d sprays, newly shuffled%s%s; keys that move it on: %s",
        len(sprays),
        f", every launch starts with {start.stem}" if start else "",
        ", TF2 console logs every step" if verbose else "",
        ", ".join(stepping) or "none",
    )
    return len(sprays), stepping


def _append_hook(path: Path, command: str) -> None:
    text = path.read_text(encoding="utf-8", errors="surrogateescape") if path.exists() else ""
    if MARKER in text:
        return
    if text and not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{text}{command} {MARKER}\n", encoding="utf-8", errors="surrogateescape")


def _remove_hook(path: Path) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8", errors="surrogateescape").splitlines(keepends=True)
    kept = [line for line in lines if MARKER not in line]
    if len(kept) == len(lines):
        return
    remaining = "".join(kept)
    if remaining.strip():
        path.write_text(remaining, encoding="utf-8", errors="surrogateescape")
    else:
        path.unlink()


def install(tf2_dir: Path, rng: random.Random | None = None) -> dict:
    count, keys = _write_rotation(tf2_dir, rng or random.SystemRandom())
    hooks = hook_files(tf2_dir)
    _append_hook(hooks.startup, f"exec {Path(ROTATION_CFG).stem}")
    for path in hooks.per_game:
        _append_hook(path, "easyspray_game")
    return {"sprays": count, "keys": keys, "hooks": hooks}


def refresh(tf2_dir: Path, rng: random.Random | None = None) -> bool:
    if not is_installed(tf2_dir):
        return False
    _write_rotation(tf2_dir, rng or random.SystemRandom(), allow_empty=True)
    return True


def uninstall(tf2_dir: Path) -> None:
    """Remove the rotation; TF2 must be closed or it re-saves the stepping binds on exit."""
    cfg = _cfg_dir(tf2_dir)
    for path in [cfg / "autoexec.cfg", *(cfg / f"{name}.cfg" for name in CLASS_CFGS),
                 cfg / "overrides" / "autoexec.cfg", cfg / "overrides" / "game_overrides.cfg"]:
        _remove_hook(path)
    (cfg / ROTATION_CFG).unlink(missing_ok=True)
    _strip_stepping(tf2_dir)
    log.info("Spray rotation removed from TF2's configs")


def main() -> int:
    parser = argparse.ArgumentParser(description="Switch to a random spray every TF2 game.")
    parser.add_argument("--tf2-dir", type=Path)
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    location = find_tf2() if args.tf2_dir is None else None
    tf2_dir = args.tf2_dir or (location.tf2_dir if location else None)
    if tf2_dir is None:
        print("TF2 was not found. Pass --tf2-dir pointing at the Team Fortress 2 folder.")
        return 1

    if args.uninstall:
        if tf2_running():
            print("Close TF2 first: it saves its key bindings when it quits and would undo this.")
            return 1
        uninstall(tf2_dir)
        print("Random spray rotation removed.")
        return 0

    try:
        result = install(tf2_dir)
    except (OSError, ValueError) as exc:
        print(f"Install failed: {exc}")
        return 1
    hooks = result["hooks"]
    print(f"Rotation installed with {result['sprays']} sprays.")
    print(f"Startup hook:  {hooks.startup}")
    print(f"Per-game hook: {', '.join(str(p) for p in hooks.per_game)}")
    if result["keys"]:
        print(f"Key(s) {', '.join(result['keys'])} also move the rotation on.")
    else:
        print("No 'impulse 201' spray bind found; the rotation only advances per game.")
    print("Restart TF2. Every class pick and spray press moves to a new spray, used from the next map.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
