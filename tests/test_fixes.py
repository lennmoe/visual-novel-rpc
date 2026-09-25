import time

import pytest

from vnrpc import config as config_mod
from vnrpc.config import Config
from vnrpc.core import Snapshot, VNRPCEngine
from vnrpc.title_parser import DEFAULT_RULES, build_rules


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
    engine.set_paused(True)                 # banks the 30 s played so far
    assert cfg.get_playtime_seconds("game") == 30
    engine._playtime_tick_start = time.time() - 600
    engine._flush_playtime()                # e.g. the game closes while paused
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
