from __future__ import annotations

import os
import sys
from pathlib import Path


def _appdata_root() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "VisualNovelRPC"


def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


APP_DIR: Path = _appdata_root()
SETTINGS_FILE: Path = APP_DIR / "settings.json"
CONFIG_FILE: Path = APP_DIR / "config.yaml"
GAMES_DIR: Path = APP_DIR / "games"
CACHE_DIR: Path = APP_DIR / "cache"
VNDB_CACHE_DIR: Path = CACHE_DIR / "vndb"
COVER_CACHE_DIR: Path = CACHE_DIR / "covers"
LOCAL_COVER_DIR: Path = COVER_CACHE_DIR / "local"
LOG_FILE: Path = APP_DIR / "vnrpc.log"

ASSETS_DIR: Path = _assets_dir()
APP_ICON_PNG: Path = ASSETS_DIR / "app_icon.png"
APP_ICON_ICO: Path = ASSETS_DIR / "vnrpc.ico"


def ensure_dirs() -> None:
    for d in (APP_DIR, GAMES_DIR, CACHE_DIR, VNDB_CACHE_DIR, COVER_CACHE_DIR, LOCAL_COVER_DIR):
        d.mkdir(parents=True, exist_ok=True)
