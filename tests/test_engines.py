import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from vnrpc.engines import clean_title  # noqa: E402

VERSION_CASES = [
    ("Sugar*Style 1.00 - prologue01", "Sugar*Style - prologue01"),
    ("Muv-Luv v1.0.3 - Chapter 2", "Muv-Luv - Chapter 2"),
    ("Some VN [1.05] - Common Route", "Some VN - Common Route"),
    ("Kanon 1;00 - Ayu Route", "Kanon - Ayu Route"),
    ("Making Lovers[ver.1.03] 1920x1080 - Prologue -", "Making Lovers - Prologue"),
    ("Game (v2.0) - Day 3", "Game - Day 3"),
]

KEEP_CASES = [
    "White Album 2 - Common Route",
    "Steins;Gate - Chapter 6: Beta",
    "NEKOPARA vol.1 ~Prologue~",
    "11eyes - Kusakabe Route",
]

RATING_CASES = [
    ("Aoi Tori R18版@- The First Three Days [2/3] -", "Aoi Tori - The First Three Days [2/3]"),
    ("Some VN (R-18) - Chapter 2", "Some VN - Chapter 2"),
    ("Some VN [R18+] - Day 3", "Some VN - Day 3"),
    ("Aoi Tori[ver.1.03] R18\x81@- The First Three Days [2/3] -", "Aoi Tori - The First Three Days [2/3]"),
]


@pytest.mark.parametrize("raw,expected", VERSION_CASES)
def test_version_tokens_are_stripped(raw, expected):
    assert clean_title(raw, None) == expected


@pytest.mark.parametrize("raw", KEEP_CASES)
def test_non_version_numbers_are_kept(raw):
    assert clean_title(raw, None) == raw


@pytest.mark.parametrize("raw,expected", RATING_CASES)
def test_rating_marker_is_stripped(raw, expected):
    assert clean_title(raw, None) == expected
