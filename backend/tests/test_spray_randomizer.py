import logging
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import spray_randomizer
from app.services.spray_randomizer import (
    CLASS_CFGS,
    EXCLUDE_FILE,
    MARKER,
    ROTATION_CFG,
    SPRAY_BIND,
    START_FILE,
    install,
    read_exclusions,
    read_start,
    refresh,
    set_included,
    set_start,
    set_step_keys,
    set_verbose,
    tf2_running,
    uninstall,
)


def add_spray(tf2: Path, name: str) -> Path:
    path = tf2 / "tf" / "materials" / "vgui" / "logos" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"VTF\x00" + bytes(60))
    return path


def make_tf2(tmp_path: Path, *, mastercomfig: bool = False) -> Path:
    for name in ("a.vtf", "b.vtf", "c.vtf"):
        add_spray(tmp_path, name)
    cfg = tmp_path / "tf" / "cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.cfg").write_text('bind "t" "impulse 201"\nbind "w" "+forward"\n')
    if mastercomfig:
        (tmp_path / "tf" / "custom").mkdir(parents=True)
        (tmp_path / "tf" / "custom" / "mastercomfig-base.vpk").write_bytes(b"")
        (cfg / "overrides").mkdir()
        (cfg / "overrides" / "autoexec.cfg").write_text("cl_spraydisable 0")
    else:
        (cfg / "autoexec.cfg").write_text("echo mine")
    return tmp_path


def rotation_text(tf2: Path) -> str:
    return (tf2 / "tf" / "cfg" / ROTATION_CFG).read_text()


def test_rotation_is_a_closed_cycle_over_all_sprays(tmp_path):
    tf2 = make_tf2(tmp_path)
    install(tf2, random.Random(1))
    text = rotation_text(tf2)

    cycle = dict(re.findall(r'alias easyspray_c(\d+) "alias easyspray_cycle easyspray_c(\d+)', text))
    seen, node = set(), "0"
    for _ in cycle:
        seen.add(node)
        node = cycle[node]
    assert node == "0" and len(seen) == 3
    assert set(re.findall(r"logos/(\w+\.vtf)", text)) == {"a.vtf", "b.vtf", "c.vtf"}
    assert f'bind "t" "{SPRAY_BIND}"' in text
    assert 'bind "w"' not in text
    config = (tf2 / "tf" / "cfg" / "config.cfg").read_text()
    assert config == 'bind "t" "impulse 201"\nbind "w" "+forward"\n'
    steps = re.findall(r'alias easyspray_c\d+ "[^"]*cl_logofile materials/vgui/logos/(\w+\.vtf)"', text)
    assert sorted(steps) == ["a.vtf", "b.vtf", "c.vtf"]
    assert 'alias easyspray_game "easyspray_cycle; easyspray_status"' in text
    assert text.rstrip().endswith("easyspray_c0\neasyspray_status")


class FakeConsole:
    """Just enough of TF2's console to run the generated rotation config."""

    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}
        self.logofile = ""
        self.output: list[str] = []

    def load(self, cfg: str) -> None:
        for line in cfg.splitlines():
            defined = re.fullmatch(r'alias (\S+) "(.*)"', line)
            if defined:
                self.aliases[defined[1]] = defined[2]
            elif line and not line.startswith(("//", "bind ")):
                self.run(line)

    def run(self, commands: str) -> None:
        for command in filter(None, (part.strip() for part in commands.split(";"))):
            name, _, rest = command.partition(" ")
            if name == "alias":
                alias, _, body = rest.partition(" ")
                self.aliases[alias] = body
            elif name == "cl_logofile":
                self.logofile = rest
            elif name == "echo":
                self.output.append(rest)
            elif name in self.aliases:
                self.run(self.aliases[name])


def test_key_presses_change_the_spray_the_next_server_gets(tmp_path):
    tf2 = make_tf2(tmp_path)
    set_start(tf2, "b.vtf")
    install(tf2, random.Random(1))
    console = FakeConsole()
    console.load(rotation_text(tf2))
    assert console.logofile == "materials/vgui/logos/b.vtf"

    console.run("easyspray_game")  # class pick on the first server
    after_class_pick = console.logofile
    assert after_class_pick != "materials/vgui/logos/b.vtf"
    assert console.output[-1].startswith("[EasyImport] next-map-spray=")
    console.run("easyspray_cycle")  # a jump or weapon switch later in the match
    assert console.logofile != after_class_pick
    console.run("easyspray_cycle")
    console.run("easyspray_cycle")
    assert console.logofile == after_class_pick  # 3 sprays: three steps wrap around


def test_vanilla_hooks_preserve_user_configs_and_are_idempotent(tmp_path):
    tf2 = make_tf2(tmp_path)
    install(tf2, random.Random(1))
    install(tf2, random.Random(2))
    cfg = tf2 / "tf" / "cfg"

    assert (cfg / "autoexec.cfg").read_text() == f"echo mine\nexec easyimport_sprays {MARKER}\n"
    for name in CLASS_CFGS:
        assert (cfg / f"{name}.cfg").read_text() == f"easyspray_game {MARKER}\n"


def test_mastercomfig_uses_override_hooks(tmp_path):
    tf2 = make_tf2(tmp_path, mastercomfig=True)
    install(tf2, random.Random(1))
    overrides = tf2 / "tf" / "cfg" / "overrides"

    assert (overrides / "autoexec.cfg").read_text() == (
        f"cl_spraydisable 0\nexec easyimport_sprays {MARKER}\n"
    )
    assert (overrides / "game_overrides.cfg").read_text() == f"easyspray_game {MARKER}\n"
    assert not (tf2 / "tf" / "cfg" / "scout.cfg").exists()


def test_unsafe_names_and_invalid_files_are_skipped(tmp_path):
    tf2 = make_tf2(tmp_path)
    add_spray(tf2, "has space.vtf")
    add_spray(tf2, "bad;cmd.vtf")
    add_spray(tf2, "fake.vtf").write_bytes(b"nope" * 20)
    install(tf2, random.Random(1))
    assert set(re.findall(r"logos/(\S+?\.vtf)", rotation_text(tf2))) == {"a.vtf", "b.vtf", "c.vtf"}


def test_install_without_sprays_fails_and_writes_nothing(tmp_path):
    (tmp_path / "tf" / "cfg").mkdir(parents=True)
    with pytest.raises(ValueError):
        install(tmp_path)
    assert not (tmp_path / "tf" / "cfg" / ROTATION_CFG).exists()
    assert not (tmp_path / "tf" / "cfg" / "autoexec.cfg").exists()


def test_refresh_only_when_installed_and_picks_up_new_sprays(tmp_path):
    tf2 = make_tf2(tmp_path)
    assert refresh(tf2) is False
    install(tf2, random.Random(1))
    add_spray(tf2, "d.vtf")
    assert refresh(tf2, random.Random(3)) is True
    assert "logos/d.vtf" in rotation_text(tf2)


def test_exclusions_are_respected_and_cleared(tmp_path):
    tf2 = make_tf2(tmp_path)
    install(tf2, random.Random(1))
    set_included(tf2, "B.vtf", False)
    assert read_exclusions(tf2) == {"b.vtf"}
    assert "logos/b.vtf" not in rotation_text(tf2)

    set_included(tf2, "b.vtf", True)
    assert "logos/b.vtf" in rotation_text(tf2)
    assert not (tf2 / "tf" / "cfg" / EXCLUDE_FILE).exists()


def test_starting_spray_opens_every_launch_and_plays_last_in_the_deck(tmp_path):
    tf2 = make_tf2(tmp_path)
    set_start(tf2, "b.vtf")
    install(tf2, random.Random(1))
    lines = rotation_text(tf2).rstrip().splitlines()

    assert lines[-2:] == [
        "cl_logofile materials/vgui/logos/b.vtf",
        "echo [EasyImport] Starting spray for this launch - b",
    ]
    assert "easyspray_game" not in lines
    deck = dict(re.findall(r'alias easyspray_c(\d+) "[^"]*cl_logofile materials/vgui/logos/([^";\s]+)', "\n".join(lines)))
    assert deck[str(len(deck) - 1)] == "b.vtf"


def test_starting_spray_is_ignored_when_unusable_and_can_be_cleared(tmp_path):
    tf2 = make_tf2(tmp_path)
    add_spray(tf2, "has space.vtf")
    install(tf2, random.Random(1))
    for bad in ("../escape.vtf", "gone.vtf", "has space.vtf"):
        set_start(tf2, bad)
        assert read_start(tf2) is None
        assert rotation_text(tf2).rstrip().endswith("easyspray_status")

    set_start(tf2, "a.vtf")
    assert "Starting spray for this launch - a" in rotation_text(tf2)
    set_start(tf2, None)
    assert not (tf2 / "tf" / "cfg" / START_FILE).exists()
    assert rotation_text(tf2).rstrip().endswith("easyspray_status")


def test_refresh_with_nothing_eligible_writes_a_harmless_rotation(tmp_path):
    tf2 = make_tf2(tmp_path)
    install(tf2, random.Random(1))
    for name in ("a.vtf", "b.vtf", "c.vtf"):
        set_included(tf2, name, False)
    text = rotation_text(tf2)
    assert "cl_logofile" not in text
    assert 'alias easyspray_cycle ""' in text and 'alias easyspray_game ""' in text


def test_uninstall_restores_everything(tmp_path):
    tf2 = make_tf2(tmp_path)
    install(tf2, random.Random(1))
    cfg = tf2 / "tf" / "cfg"
    (cfg / "config.cfg").write_text(f'bind "t" "{SPRAY_BIND}"\n')
    uninstall(tf2)

    assert (cfg / "autoexec.cfg").read_text() == "echo mine\n"
    assert not (cfg / "scout.cfg").exists()
    assert not (cfg / ROTATION_CFG).exists()
    assert (cfg / "config.cfg").read_text() == 'bind "t" "impulse 201"\n'


PLAYER_CONFIG = (
    'bind "1" "slot1"\nbind "q" "lastinv"\nbind "t" "impulse 201"\nbind "w" "+forward"\n'
    'bind "SPACE" "+jump"\nbind "MOUSE1" "+attack"\nbind "MWHEELDOWN" "invnext"\n'
    'cl_logofile "materials/vgui/logos/a.vtf"\n'
)


def player_tf2(tmp_path: Path) -> tuple[Path, Path]:
    tf2 = make_tf2(tmp_path)
    config = tf2 / "tf" / "cfg" / "config.cfg"
    config.write_text(PLAYER_CONFIG)
    return tf2, config


def rotation_binds(tf2: Path) -> dict[str, str]:
    return dict(re.findall(r'^bind "([^"]+)" "([^"]*)"$', rotation_text(tf2), re.MULTILINE))


def test_step_keys_are_bound_at_launch_without_touching_config_cfg(tmp_path):
    tf2, config = player_tf2(tmp_path)
    install(tf2, random.Random(1))
    assert rotation_binds(tf2) == {"t": SPRAY_BIND}

    set_step_keys(tf2, True)
    assert rotation_binds(tf2) == {
        "1": "slot1; easyspray_cycle",
        "q": "lastinv; easyspray_cycle",
        "t": SPRAY_BIND,
        "SPACE": "+jump; easyspray_cycle",
        "MWHEELDOWN": "invnext; easyspray_cycle",
    }
    assert config.read_text() == PLAYER_CONFIG


def test_turning_step_keys_off_restores_keys_tf2_already_saved(tmp_path):
    tf2, config = player_tf2(tmp_path)
    install(tf2, random.Random(1))
    set_step_keys(tf2, True)
    # TF2 saves the stepping binds it was given into config.cfg when it quits.
    config.write_text(PLAYER_CONFIG.replace('"+jump"', '"+jump; easyspray_cycle"'))

    set_step_keys(tf2, False)
    assert rotation_binds(tf2) == {"SPACE": "+jump", "1": "slot1", "q": "lastinv", "t": SPRAY_BIND,
                                   "MWHEELDOWN": "invnext"}
    set_step_keys(tf2, False)
    assert rotation_binds(tf2)["SPACE"] == "+jump"


def test_step_keys_choice_waits_for_the_rotation(tmp_path):
    tf2, config = player_tf2(tmp_path)
    set_step_keys(tf2, True)
    assert not (tf2 / "tf" / "cfg" / ROTATION_CFG).exists()
    assert "SPACE" in install(tf2, random.Random(1))["keys"]


def test_refresh_follows_keys_rebound_in_tf2_options(tmp_path):
    tf2, config = player_tf2(tmp_path)
    install(tf2, random.Random(1))
    set_step_keys(tf2, True)
    # The player moves jump from SPACE to ALT in TF2's options; TF2 saves config.cfg on quit.
    config.write_text(PLAYER_CONFIG.replace('bind "SPACE" "+jump"', 'bind "SPACE" "+duck"\nbind "ALT" "+jump"'))
    refresh(tf2, random.Random(2))
    binds = rotation_binds(tf2)
    assert binds["ALT"] == "+jump; easyspray_cycle" and "SPACE" not in binds


def test_newest_steam_cloud_config_wins_and_uninstall_cleans_every_copy(tmp_path, monkeypatch):
    tf2, local = player_tf2(tmp_path)
    cloud = tmp_path / "userdata" / "1" / "440" / "remote" / "cfg" / "config.cfg"
    cloud.parent.mkdir(parents=True)
    cloud.write_text(PLAYER_CONFIG.replace('bind "q" "lastinv"', 'bind "e" "lastinv"') + f'bind "y" "{SPRAY_BIND}"\n')
    os.utime(local, (1_000_000, 1_000_000))
    monkeypatch.setattr(spray_randomizer, "config_files", lambda tf2_dir: [local, cloud])

    install(tf2, random.Random(1))
    set_step_keys(tf2, True)
    binds = rotation_binds(tf2)
    assert binds["e"] == "lastinv; easyspray_cycle" and binds["y"] == SPRAY_BIND and "q" not in binds

    local.write_text(PLAYER_CONFIG.replace('"+jump"', '"+jump; easyspray_cycle"'))
    uninstall(tf2)
    assert "easyspray" not in local.read_text() and "easyspray" not in cloud.read_text()
    assert 'bind "y" "impulse 201"' in cloud.read_text()


def test_verbose_logs_every_step_in_the_tf2_console(tmp_path):
    tf2 = make_tf2(tmp_path)
    install(tf2, random.Random(1))
    assert "step=" not in rotation_text(tf2)

    set_verbose(tf2, True)
    text = rotation_text(tf2)
    steps = re.findall(r'alias easyspray_c\d+ "[^"]*echo \[EasyImport\] step=(\d)/3 next-map-spray=\w+"', text)
    assert sorted(steps) == ["1", "2", "3"]
    assert "Spray rotation loaded - 3 sprays in a shuffled order - logging every step" in text

    set_verbose(tf2, False)
    assert "step=" not in rotation_text(tf2)


def test_rotation_changes_are_logged_for_the_app_console(tmp_path, caplog):
    tf2, _ = player_tf2(tmp_path)
    with caplog.at_level(logging.INFO, logger="tf2spray.rotation"):
        install(tf2, random.Random(1))
        set_step_keys(tf2, True)
    assert "Spray rotation written: 3 sprays" in caplog.text
    assert "keys that move it on: 1, q, t, SPACE, MWHEELDOWN" in caplog.text


@pytest.mark.skipif(sys.platform != "win32", reason="uses the Windows process list")
def test_tf2_running_looks_for_the_game_process(monkeypatch):
    def listing(text):
        return lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=text)

    monkeypatch.setattr(subprocess, "run", listing('"explorer.exe","1"\n"tf_win64.exe","2"\n'))
    assert tf2_running() is True
    monkeypatch.setattr(subprocess, "run", listing('"explorer.exe","1"\n"hl2.exe","3"\n'))
    assert tf2_running() is False
