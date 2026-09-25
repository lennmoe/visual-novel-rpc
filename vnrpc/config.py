from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml

from .paths import CONFIG_FILE, GAMES_DIR, SETTINGS_FILE, ensure_dirs

# The Discord Application ID the app talks to.  This one is carried over from the
# user's earlier per-VN scripts so Rich Presence works out of the box; it can be
# replaced in Settings with any application you own.
DEFAULT_CLIENT_ID = "1466261523889393892"

DEFAULTS: dict[str, Any] = {
    "discord_client_id": DEFAULT_CLIENT_ID,
    "detection_mode": "auto",          # "auto" | "manual"
    "manual_target": {                  # used when detection_mode == "manual"
        "exe": "",                      # exe name, e.g. "SugarStyle.exe"
        "title_contains": "",           # optional extra filter on the window title
    },
    "allow_nsfw_covers": False,
    "use_steam_names": True,            # prefer the installed Steam app's library name
    "show_elapsed": True,               # show a running timer in the presence
    "clear_on_close": True,             # clear presence when the VN window is gone
    "idle_minutes": 0,                  # >0: clear presence after N min without title change
    "update_min_interval": 5,           # seconds; Discord tolerates ~5 updates / 20 s (1 / 4 s)
    "start_minimized": False,
    "default_asset_key": "vn_cover",    # Discord asset key used when no usable cover URL
    "show_vndb_button": True,           # add a "View on VNDB" button to the presence
    "title_rules": [],                 # extra user rules, see title_parser.DEFAULT_RULES
}

# Legacy JSON per-game field -> current YAML field, applied once during migration.
_LEGACY_GAME_FIELDS = {"custom_name": "title", "exe_path": "path"}


def game_key(exe: str) -> str:
    """Normalize an exe name into a stable per-game key (and games/<key>.yaml stem)."""
    name = os.path.basename(exe or "").strip().lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def _safe_filename(key: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in key)
    return cleaned or "game"


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Config:
    def __init__(
        self,
        data: dict[str, Any] | None = None,
        games: dict[str, dict[str, Any]] | None = None,
        game_filenames: dict[str, str] | None = None,
    ) -> None:
        self._data = _merge_defaults(data or {})
        self._games: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (games or {}).items()}
        self._game_filenames: dict[str, str] = dict(game_filenames or {})  # key -> filename stem on disk
        # games are touched from the UI, the window watcher and the playtime
        # thread; one re-entrant lock keeps the dicts and files consistent
        self._lock = threading.RLock()
        self._playtime_frac: dict[str, float] = {}  # sub-second remainders not yet on disk

    @classmethod
    def load(cls) -> "Config":
        ensure_dirs()
        if not CONFIG_FILE.exists() and SETTINGS_FILE.exists():
            return cls._migrate_from_legacy()

        data: dict[str, Any] = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (FileNotFoundError, yaml.YAMLError, OSError):
            data = {}
        if not isinstance(data, dict):
            data = {}

        games: dict[str, dict[str, Any]] = {}
        game_filenames: dict[str, str] = {}
        for path in sorted(GAMES_DIR.glob("*.yaml")):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    entry = yaml.safe_load(fh) or {}
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(entry, dict):
                continue
            key = entry.pop("_key", None) or path.stem
            games[key] = entry
            game_filenames[key] = path.stem

        cfg = cls(data, games, game_filenames)
        if not CONFIG_FILE.exists():
            cfg.save()
        # rename any file left over from an older naming scheme (e.g. a title
        # was just added, or the naming scheme itself changed) to the current
        # title-based name
        for key, entry in list(cfg._games.items()):
            if cfg._game_filenames.get(key) != cfg._filename_for(key, entry):
                cfg._save_game_file(key)
        return cfg

    @classmethod
    def _migrate_from_legacy(cls) -> "Config":
        """One-time move from the old single settings.json to config.yaml + games/*.yaml.
        The old file is left in place untouched, as a safety net."""
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                old = json.load(fh)
        except (OSError, json.JSONDecodeError):
            old = {}
        per_game = old.pop("per_game", {}) or {}

        cfg = cls(old)
        for key, entry in per_game.items():
            renamed = dict(entry)
            for old_field, new_field in _LEGACY_GAME_FIELDS.items():
                if old_field in renamed:
                    renamed[new_field] = renamed.pop(old_field)
            cfg._games[key] = renamed
        cfg.save()
        for key in cfg._games:
            cfg._save_game_file(key)
        return cfg

    def save(self) -> None:
        ensure_dirs()
        with self._lock:
            _atomic_write_yaml(CONFIG_FILE, self._data)

    def _filename_for(self, key: str, entry: dict[str, Any]) -> str:
        """The file's basename: the VN's title once known, else its exe key.
        Disambiguated against whatever other games are currently using that name."""
        title = (entry.get("title") or "").strip()
        base = _safe_filename(title) if title else _safe_filename(key)
        candidate = base
        n = 2
        used = {v.lower() for k, v in self._game_filenames.items() if k != key}
        while candidate.lower() in used:
            candidate = f"{base}_{n}"
            n += 1
        return candidate

    def _save_game_file(self, key: str) -> None:
        with self._lock:
            self._save_game_file_locked(key)

    def _save_game_file_locked(self, key: str) -> None:
        entry = self._games.get(key)
        if entry is None:
            return
        new_stem = self._filename_for(key, entry)
        old_stem = self._game_filenames.get(key)
        if old_stem and old_stem.lower() != new_stem.lower():
            try:
                (GAMES_DIR / f"{old_stem}.yaml").unlink()
            except FileNotFoundError:
                pass
        to_write = dict(entry)
        to_write["_key"] = key
        _atomic_write_yaml(GAMES_DIR / f"{new_stem}.yaml", to_write)
        self._game_filenames[key] = new_stem

    def _delete_game_file(self, key: str) -> None:
        stem = self._game_filenames.pop(key, None) or _safe_filename(key)
        try:
            (GAMES_DIR / f"{stem}.yaml").unlink()
        except FileNotFoundError:
            pass

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def game_override(self, exe: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._games.get(game_key(exe), {}))

    def all_games(self) -> dict[str, dict[str, Any]]:
        """Every tracked VN, keyed by its normalized id -- for the Library view."""
        with self._lock:
            return {k: dict(v) for k, v in self._games.items()}

    def set_game_override(self, exe: str, **fields: Any) -> None:
        key = game_key(exe)
        with self._lock:
            entry = self._games.setdefault(key, {})
            entry.update({k: v for k, v in fields.items() if v is not None})
            self._save_game_file_locked(key)

    def clear_game_override(self, exe: str) -> None:
        key = game_key(exe)
        with self._lock:
            if key in self._games:
                del self._games[key]
                self._playtime_frac.pop(key, None)
                self._delete_game_file(key)

    def get_playtime_seconds(self, key: str) -> int:
        """``key`` is already a normalized :func:`game_key`, not a raw exe name."""
        with self._lock:
            return int(self._games.get(key, {}).get("playtime_seconds", 0))

    def add_playtime_seconds(self, key: str, seconds: float) -> None:
        if not key or seconds <= 0:
            return
        with self._lock:
            entry = self._games.setdefault(key, {})
            # carry the fractional part over to the next flush instead of
            # truncating it away every time (that lost ~1% of all playtime)
            total = self._playtime_frac.get(key, 0.0) + seconds
            whole = int(total)
            self._playtime_frac[key] = total - whole
            entry["playtime_seconds"] = int(entry.get("playtime_seconds", 0)) + whole
            self._save_game_file_locked(key)

    def reset_playtime(self, exe: str) -> None:
        key = game_key(exe)
        with self._lock:
            entry = self._games.get(key)
            if entry is not None:
                entry.pop("playtime_seconds", None)
                self._playtime_frac.pop(key, None)
                self._save_game_file_locked(key)
