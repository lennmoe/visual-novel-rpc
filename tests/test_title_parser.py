import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from vnrpc.title_parser import parse  # noqa: E402

CASES = [
    ("Sugar*Style - prologue01", "Sugar*Style", "free", "Prologue01"),
    ("Grisaia no Kajitsu - Yumiko Route - Chapter 4", "Grisaia no Kajitsu", "route", "Yumiko Route"),
    ("Katawa Shoujo - Act 1", "Katawa Shoujo", "chapter", "Chapter 1"),
    ("Making Lovers - Prologue", "Making Lovers", "prologue", "Prologue"),
    ("Hatsuyuki Sakura [ Chapter III ]", "Hatsuyuki Sakura", "chapter", "Chapter 3"),
    ("NEKOPARA vol.1 ~Prologue~", "NEKOPARA vol.1", "prologue", "Prologue"),
    ("素晴らしき日々 第三章", "素晴らしき日々", "chapter", "Chapter 3"),
    ("G-senjou no Maou - 第2章", "G-senjou no Maou", "chapter", "Chapter 2"),
    ("Fate/stay night - Fate Route", "Fate/stay night", "route", "Fate Route"),
    ("Clannad - Nagisa編", "Clannad", "route", "Nagisa Arc"),
    ("Some VN - Day 5", "Some VN", "chapter", "Day 5"),
    ("Some VN - Good Ending", "Some VN", "ending", "Good Ending"),
    ("Steins;Gate - Chapter 6: Beta", "Steins;Gate", "chapter", "Chapter 6"),
    ("White Album 2 - Common Route", "White Album 2", "route", "Common Route"),
    ("Amatsutsumi - Kokoro, Chapter 1", "Amatsutsumi", "chapter", "Kokoro — Chapter 1"),
]


@pytest.mark.parametrize("title,game,section_type,label", CASES)
def test_parse(title, game, section_type, label):
    info = parse(title, game)
    assert info.section_type == section_type, info
    assert info.section_label == label, info


def test_bare_game_name_yields_nothing():
    info = parse("Sugar*Style", "Sugar*Style")
    assert info.is_empty


def test_noise_is_stripped():
    info = parse("Making Lovers[ver.1.03] 1920x1080 - Prologue -", "Making Lovers")
    assert info.section_label == "Prologue"


def test_unknown_game_falls_back_to_leftover_text():
    info = parse("Mystery VN - Somewhere Nice", "")
    assert info.section_type == "free"
    assert "Somewhere Nice" in info.section_label


def test_fallback_keeps_real_trailing_brackets():
    info = parse("Aoi Tori - The First Three Days [2/3]", "Aoi Tori")
    assert info.section_label == "The First Three Days [2/3]"


def test_fallback_drops_brackets_left_empty_by_version_stripping():
    info = parse("Some VN [1.05]", "Some VN")
    assert "[" not in info.section_label


@pytest.mark.parametrize(
    "title,game",
    [
        ("Sugar*Style 1.00 - Prologue", "Sugar*Style"),
        ("Sugar*Style v1.0.3 - Prologue", "Sugar*Style"),
        ("Sugar*Style 1;00 - Prologue", "Sugar*Style"),
        ("Sugar*Style [1.05] - Prologue", "Sugar*Style"),
    ],
)
def test_version_numbers_are_dropped(title, game):
    info = parse(title, game)
    assert info.section_label == "Prologue", info
    assert "1" not in info.section_label
