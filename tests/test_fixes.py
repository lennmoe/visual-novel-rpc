import os
import time

import pytest

from vnrpc import config as config_mod
from vnrpc import window_watcher
from vnrpc.config import DEFAULTS, Config
from vnrpc.core import Snapshot, VNRPCEngine
from vnrpc.engines import blacklist_set, is_blacklisted
from vnrpc.title_parser import DEFAULT_RULES, build_rules
from vnrpc.winapi import WindowInfo
from vnrpc.window_watcher import WindowWatcher


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "GAMES_DIR", tmp_path / "games")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.yaml")
    return Config()


def test_playtime_keeps_fractional_seconds(cfg):
    for _ in range(4):
        cfg.add_playtime_seconds("game", 0.5)
    assert cfg.get_playtime_seconds("game") == 2


def test_no_playtime_banked_while_paused(cfg):
    engine = VNRPCEngine(cfg)
    engine._playtime_key = "game"
    engine._playtime_tick_start = time.time() - 30
    engine.set_paused(True)
    assert cfg.get_playtime_seconds("game") == 30
    engine._playtime_tick_start = time.time() - 600
    engine._flush_playtime()
    assert cfg.get_playtime_seconds("game") == 30


def test_build_rules_skips_malformed_entries():
    rules = build_rules([
        "not a dict",
        {"label": "no pattern"},
        {"pattern": "(unclosed"},
        {"name": "ok", "pattern": r"part\s*(?P<n>\d+)", "label": "Part {n}"},
    ])
    assert [r.name for r in rules[: len(rules) - len(DEFAULT_RULES)]] == ["ok"]


def test_activity_respects_privacy(cfg):
    engine = VNRPCEngine(cfg)
    snap = Snapshot(detected=True, game_name="Sugar*Style", section_label="Chapter 2", session_start=100)
    assert engine.activity_for(snap).details == "Reading — Chapter 2"
    snap.privacy = "partial"
    assert engine.activity_for(snap).details == ""
    snap.privacy = "private"
    assert engine.activity_for(snap).name == "Visual Novel"
    snap.privacy = "off"
    assert engine.activity_for(snap) is None
    assert engine.activity_for(Snapshot()) is None


def _win(exe_path: str, class_name: str = "") -> WindowInfo:
    return WindowInfo(hwnd=1, title="Some window", pid=1, exe_path=exe_path, class_name=class_name)


def test_user_blacklist_is_normalized():
    bl = blacklist_set(["osu!", r"C:\Apps\Medal.EXE", ""])
    assert is_blacklisted("osu!.exe", bl)
    assert is_blacklisted("medal.exe", bl)
    assert is_blacklisted("discord.exe", bl)
    assert not is_blacklisted("BGI.exe", bl)


def test_blacklisted_window_is_never_picked(monkeypatch):
    osu = _win(r"C:\osu\osu!.exe", class_name="SDL_app")
    picked = []
    watcher = WindowWatcher(picked.append)
    assert watcher._pick_auto([osu])[0] is osu
    watcher.configure(mode="auto", blacklist=blacklist_set(["osu!.exe"]))
    monkeypatch.setattr(window_watcher, "list_top_level_windows", lambda: [osu])
    watcher._tick()
    assert picked == []


def test_library_game_is_detected_by_saved_path():
    game = _win(r"C:\vn\Sakura\sakura.exe")
    watcher = WindowWatcher(lambda _t: None)
    assert watcher._pick_auto([game]) is None
    known = frozenset({os.path.normcase(r"c:\VN\sakura\SAKURA.exe")})
    assert watcher._pick_auto([game], known)[0] is game


def test_add_to_blacklist_does_not_touch_defaults(cfg):
    engine = VNRPCEngine(cfg)
    before = list(DEFAULTS["blacklist_exe"])
    engine.add_to_blacklist("RiotClientServices.exe")
    engine.add_to_blacklist("riotclientservices")
    assert cfg["blacklist_exe"] == before + ["RiotClientServices.exe"]
    assert DEFAULTS["blacklist_exe"] == before
    assert "riotclientservices.exe" in engine.blacklist

