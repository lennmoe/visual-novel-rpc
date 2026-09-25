from __future__ import annotations

import difflib
import re
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable

from . import steam
from .config import Config, game_key
from .covers import Cover, cover_from_vn, resolve_cover
from .engines import clean_title
from .presence import Activity, PresenceManager
from .title_parser import Rule, build_rules, parse, strip_game_name
from .vndb import ReleaseCover, VNDBClient, VNResult
from .window_watcher import TargetState, WindowWatcher

_SECTION_TAIL = re.compile(r"\s*[-–—~～:|].*$")

_PLAYTIME_FLUSH_INTERVAL = 60.0  # seconds between "still playing" saves to disk


def format_playtime(seconds: int) -> str:
    """``5102`` -> ``"1h 25m"``."""
    total_minutes = max(0, int(seconds)) // 60
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes:02d}m"


@dataclass
class Snapshot:
    """Everything the UI needs to draw the "now playing" card."""
    detected: bool = False
    exe: str = ""
    engine_name: str = ""
    raw_title: str = ""
    game_name: str = ""
    section_type: str = ""
    section_label: str = ""
    cover: Cover = field(default_factory=Cover)
    vn: VNResult | None = None
    vndb_locked: bool = False       # game/cover pinned by a per-game override
    presence_text: str = ""         # one-line preview of what Discord shows
    steam_name: str = ""            # name from the matching installed Steam app, if any
    privacy: str = "full"           # "full" | "partial" | "private" | "off"
    playtime_seconds: int = 0       # total time ever spent on this game (persisted)
    playtime_text: str = ""         # "44h 42m", ready to display
    session_start: int = 0          # epoch seconds this play session began


class VNRPCEngine:
    def __init__(
        self,
        config: Config,
        *,
        on_snapshot: Callable[[Snapshot], None] | None = None,
        on_status: Callable[[str, bool, str], None] | None = None,
    ) -> None:
        self.config = config
        self._on_snapshot = on_snapshot or (lambda snap: None)
        self._on_status = on_status or (lambda kind, ok, msg: None)

        self.vndb = VNDBClient()
        self.presence = PresenceManager(
            config["discord_client_id"],
            min_interval=config["update_min_interval"],
            on_status=lambda ok, msg: self._on_status("discord", ok, msg),
        )
        self.watcher = WindowWatcher(self._handle_target)

        self._lock = threading.Lock()
        self._snapshot = Snapshot()
        self._current_key = ""
        self._session_start = 0
        self._auto_match: dict[str, VNResult | None] = {}
        self._rules: list[Rule] = build_rules(config.get("title_rules"))
        self._paused = False

        # playtime: `_playtime_key` is the game currently accruing time;
        # `_playtime_tick_start` is when the current unsaved stretch began.
        self._playtime_key = ""
        self._playtime_tick_start = 0.0
        self._playtime_lock = threading.Lock()
        self._playtime_thread: threading.Thread | None = None
        self._playtime_stop = threading.Event()

    def start(self) -> None:
        self._apply_watcher_config()
        self.presence.start()
        self.watcher.start()
        self._playtime_stop.clear()
        self._playtime_thread = threading.Thread(target=self._playtime_loop, name="playtime", daemon=True)
        self._playtime_thread.start()

    def stop(self) -> None:
        self._playtime_stop.set()
        if self._playtime_thread:
            self._playtime_thread.join(timeout=2)
        self._flush_playtime()
        self.watcher.stop()
        self.presence.stop()

    def set_paused(self, paused: bool) -> None:
        with self._playtime_lock:
            if paused:
                self._flush_playtime_locked()   # bank time played up to the pause
            else:
                self._playtime_tick_start = time.time()  # resume counting from now
            self._paused = paused
        self.presence.set_paused(paused)
        if not paused:
            self.watcher.poke()

    def reload_config(self) -> None:
        self._rules = build_rules(self.config.get("title_rules"))
        self.presence.set_client_id(self.config["discord_client_id"])
        self.presence.set_min_interval(self.config["update_min_interval"])
        self._apply_watcher_config()
        self.watcher.poke()
        self._auto_match.clear()

    def _apply_watcher_config(self) -> None:
        mt = self.config["manual_target"]
        self.watcher.configure(
            mode=self.config["detection_mode"],
            manual_exe=mt.get("exe", ""),
            manual_title_contains=mt.get("title_contains", ""),
        )

    @property
    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def list_windows(self):
        return self.watcher.list_windows()

    def _handle_target(self, target: TargetState | None) -> None:
        if target is None:
            with self._playtime_lock:
                self._flush_playtime_locked()
                self._playtime_key = ""
            self._current_key = ""
            snap = Snapshot(detected=False)
            self._store(snap)
            if self.config["clear_on_close"]:
                self.presence.set_activity(None)
            self._on_status("game", False, "no visual novel detected")
            return

        key = game_key(target.exe)
        if key != self._current_key:
            with self._playtime_lock:
                self._flush_playtime_locked()  # bank whatever the previous game accrued
                self._playtime_key = key
                self._playtime_tick_start = time.time()
            self._current_key = key
            self._session_start = int(time.time())

        override = self.config.game_override(target.exe)
        if target.exe_path and override.get("path") != target.exe_path:
            # remembered so the Library can relaunch this VN later
            self.config.set_game_override(target.exe, path=target.exe_path)
            override = self.config.game_override(target.exe)
        cleaned = clean_title(target.raw_title, None) if not target.engine_name else clean_title(
            target.raw_title, _engine_by_name(target.engine_name)
        )

        steam_name = ""
        if self.config.get("use_steam_names", True):
            try:
                app = steam.app_for_exe(target.exe_path)
                steam_name = app.name if app else ""
            except Exception:
                steam_name = ""

        vn = self._resolve_vn(key, cleaned, override, steam_name)
        game_name = (
            override.get("title")
            or (vn.title if vn else "")
            or steam_name
            or _guess_game_name(cleaned)
        )

        rules = build_rules((override.get("title_rules") or []) + (self.config.get("title_rules") or []))
        info = parse(cleaned, game_name, rules)

        cover = self._resolve_cover(override, vn, game_name)
        privacy = (override.get("privacy") or "full").lower()
        playtime_seconds = self.config.get_playtime_seconds(key)

        snap = Snapshot(
            detected=True,
            exe=target.exe,
            engine_name=target.engine_name,
            raw_title=target.raw_title,
            game_name=game_name,
            section_type=info.section_type,
            section_label=info.section_label,
            cover=cover,
            vn=vn,
            vndb_locked=bool(override.get("vndb_id") or override.get("cover_source")),
            steam_name=steam_name,
            privacy=privacy,
            playtime_seconds=playtime_seconds,
            playtime_text=format_playtime(playtime_seconds),
            session_start=self._session_start,
        )
        snap.presence_text = _preview(game_name, info.section_label)
        self._store(snap)
        self._on_status("game", True, f"{game_name or target.exe}")
        self._push_presence(snap)

    def _resolve_vn(self, key: str, cleaned: str, override: dict, steam_name: str = "") -> VNResult | None:
        if override.get("vndb_id"):
            # failures are cached too: offline, every retry blocks for up to a minute
            cache_key = "id:" + override["vndb_id"]
            if cache_key in self._auto_match:
                return self._auto_match[cache_key]
            try:
                vn = self.vndb.get_vn(override["vndb_id"])
            except Exception as exc:
                vn = None
                self._on_status("vndb", False, f"VNDB lookup failed: {exc}")
            self._auto_match[cache_key] = vn
            return vn
        if override.get("cover_source") in ("url", "local", "none"):
            return None  # user chose a non-VNDB cover; don't auto-search
        if key in self._auto_match:
            return self._auto_match[key]
        # one auto search per game per session; a Steam library name is a much
        # cleaner query than whatever the window title happens to say
        query = steam_name or _search_query(cleaned)
        vn = None
        try:
            results = self.vndb.search_vn(query, limit=8)
            vn = _best_vn_match(results, query)
        except Exception as exc:  # network/parse issues shouldn't break detection
            self._on_status("vndb", False, f"VNDB lookup failed: {exc}")
        self._auto_match[key] = vn
        return vn

    def _resolve_cover(self, override: dict, vn: VNResult | None, game_name: str) -> Cover:
        allow_nsfw = self.config["allow_nsfw_covers"]
        asset = self.config["default_asset_key"]
        source = override.get("cover_source")
        if source:
            try:
                return resolve_cover(
                    source,
                    override.get("cover_value", ""),
                    vndb=self.vndb,
                    allow_nsfw=allow_nsfw,
                    default_asset_key=asset,
                    label=game_name,
                    vn=vn,
                )
            except Exception as exc:
                self._on_status("vndb", False, f"cover lookup failed: {exc}")
                if vn is None:
                    return Cover(source="none")
        if vn is not None:
            return cover_from_vn(vn, allow_nsfw=allow_nsfw, default_asset_key=asset)
        return Cover(source="none")

    def _resolve_cover_for_vn_id(self, vn_id: str, game_name: str) -> Cover:
        return resolve_cover(
            "vndb", vn_id, vndb=self.vndb,
            allow_nsfw=self.config["allow_nsfw_covers"],
            default_asset_key=self.config["default_asset_key"],
            label=game_name,
        )

    def activity_for(self, snap: Snapshot) -> Activity | None:
        """Exactly what gets pushed to Discord for ``snap`` (``None`` = nothing).
        The UI's preview renders this too, so the two can't drift apart."""
        if not snap.detected or snap.privacy == "off":
            return None
        start = (snap.session_start or None) if self.config["show_elapsed"] else None
        if snap.privacy == "private":
            return Activity(
                name="Visual Novel",
                details="Reading",
                large_image=self.config["default_asset_key"],
                large_text="Visual Novel",
                small_text="via Visual Novel RPC",
                start=start,
                buttons=[],
            )
        buttons = []
        if self.config["show_vndb_button"] and snap.vn is not None and snap.privacy != "partial":
            buttons.append({"label": "View on VNDB", "url": snap.vn.vndb_url})
        state = f"Total read: {snap.playtime_text}" if snap.playtime_seconds > 0 else ""
        return Activity(
            name=snap.game_name or snap.raw_title or "Visual Novel",
            details="" if snap.privacy == "partial" else _reading_line(snap.section_label),
            state=state,
            large_image=snap.cover.discord_image or self.config["default_asset_key"],
            large_text=snap.cover.label or snap.game_name,
            small_text="via Visual Novel RPC",
            start=start,
            buttons=buttons,
        )

    def _push_presence(self, snap: Snapshot) -> None:
        if self._paused:
            return
        self.presence.set_activity(self.activity_for(snap))

    def _store(self, snap: Snapshot) -> None:
        with self._lock:
            self._snapshot = snap
        self._on_snapshot(snap)

    def _flush_playtime(self) -> None:
        """Bank whatever time has passed since the last flush for the active game."""
        with self._playtime_lock:
            self._flush_playtime_locked()

    def _flush_playtime_locked(self) -> None:
        # time spent paused was already banked at pause time, and isn't reading time
        if self._paused or not self._playtime_key or self._playtime_tick_start <= 0:
            return
        now = time.time()
        elapsed = now - self._playtime_tick_start
        self._playtime_tick_start = now
        if elapsed > 0:
            self.config.add_playtime_seconds(self._playtime_key, elapsed)

    def _playtime_loop(self) -> None:
        """Periodically save elapsed time and refresh the "total hours read" figure
        so it climbs live in the UI and on Discord while a VN stays in focus."""
        while not self._playtime_stop.wait(_PLAYTIME_FLUSH_INTERVAL):
            if self._paused or not self._playtime_key:
                continue
            with self._lock:
                snap = self._snapshot
            if not snap.detected:
                continue
            self._flush_playtime()
            total = self.config.get_playtime_seconds(game_key(snap.exe))
            new_snap = replace(snap, playtime_seconds=total, playtime_text=format_playtime(total))
            with self._lock:
                # the watcher may have stored a newer snapshot (title change, other
                # game) meanwhile -- never overwrite that with this stale copy
                if self._snapshot is not snap:
                    continue
                self._snapshot = new_snap
            self._on_snapshot(new_snap)
            self._push_presence(new_snap)

    def apply_vn_choice(self, exe: str, vn: VNResult, *, as_cover: bool = True) -> None:
        """User picked a VN in the cover dialog's VNDB tab."""
        fields = {"vndb_id": vn.id, "title": vn.title}
        if as_cover:
            fields.update(cover_source="vndb", cover_value=vn.id)
        self.config.set_game_override(exe, **fields)
        self.reload_config()

    def apply_release_cover(self, exe: str, vn: VNResult, image_url: str) -> None:
        """User picked a specific release's box art in the cover dialog."""
        self.config.set_game_override(
            exe, vndb_id=vn.id, title=vn.title, cover_source="url", cover_value=image_url
        )
        self.reload_config()

    def get_release_covers(self, vn_id: str) -> list[ReleaseCover]:
        return self.vndb.get_release_covers(vn_id)

    def apply_cover_url(self, exe: str, url: str) -> None:
        self.config.set_game_override(exe, cover_source="url", cover_value=url)
        self.reload_config()

    def apply_cover_local(self, exe: str, path: str) -> None:
        self.config.set_game_override(exe, cover_source="local", cover_value=path)
        self.reload_config()

    def set_game_privacy(self, exe: str, mode: str) -> None:
        self.config.set_game_override(exe, privacy=mode)
        self.reload_config()

    def clear_override(self, exe: str) -> None:
        self.config.clear_game_override(exe)
        self.reload_config()

    def reset_playtime(self, exe: str) -> None:
        with self._playtime_lock:
            self.config.reset_playtime(exe)
            if game_key(exe) == self._playtime_key:
                self._playtime_tick_start = time.time()
        self.reload_config()

    def search_vndb(self, query: str, limit: int = 12) -> list[VNResult]:
        return self.vndb.search_vn(query, limit=limit)


def _engine_by_name(name: str):
    from .engines import ENGINES
    for eng in ENGINES:
        if eng.name == name:
            return eng
    return None


def _guess_game_name(cleaned: str) -> str:
    head = _SECTION_TAIL.sub("", cleaned).strip(" -–—|:·•")
    return head or cleaned.strip()


def _search_query(cleaned: str) -> str:
    q = _SECTION_TAIL.sub("", cleaned)
    q = re.sub(r"\bver(?:sion)?\.?\s*[\d.;]+", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\bv?\d+[.;]\d+(?:[.;]\d+)*[a-z]?\b", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"[\[\]（）()【】]", " ", q)
    return re.sub(r"\s{2,}", " ", q).strip() or cleaned.strip()


def _preview(game: str, section: str) -> str:
    if game and section:
        return f"{game}  —  {section}"
    return game or section or ""


def _reading_line(section_label: str) -> str:
    return f"Reading — {section_label}" if section_label else "Reading"


_NAME_MATCH_THRESHOLD = 0.6


def _best_vn_match(results: list[VNResult], query: str) -> VNResult | None:
    """Prefer the candidate whose title best matches the query; if nothing is a
    confident name match, fall back to the highest-rated candidate instead of
    blindly trusting VNDB's own top search result."""
    if not results:
        return None
    q = _loose(query)
    if not q:
        return results[0]
    best_vn, best_score = results[0], 0.0
    for vn in results:
        score = max(_similarity(q, _loose(vn.title)), _similarity(q, _loose(vn.alt_title)))
        if score > best_score:
            best_vn, best_score = vn, score
    if best_score >= _NAME_MATCH_THRESHOLD:
        return best_vn
    return max(results, key=lambda vn: vn.rating or 0.0)


def _loose(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", (text or "")).lower()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _main() -> None:  # pragma: no cover
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = Config.load()

    def on_snap(s: Snapshot) -> None:
        if s.detected:
            logging.info("PRESENCE  %s | cover=%s(%s)", s.presence_text, s.cover.source, s.cover.discord_image[:60])
        else:
            logging.info("PRESENCE  (cleared)")

    def on_status(kind: str, ok: bool, msg: str) -> None:
        logging.info("[%s] %s%s", kind, "OK " if ok else "-- ", msg)

    engine = VNRPCEngine(cfg, on_snapshot=on_snap, on_status=on_status)
    engine.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":  # pragma: no cover
    _main()
