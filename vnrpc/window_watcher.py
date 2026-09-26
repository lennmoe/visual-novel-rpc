from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .engines import BLACKLIST_EXE, Engine, detect_engine, is_blacklisted
from .winapi import WindowInfo, get_window_title, is_window, list_top_level_windows

_KNOWN_GAME_SCORE = 1000


@dataclass
class TargetState:
    hwnd: int
    pid: int
    exe: str
    exe_path: str
    raw_title: str
    engine_name: str = ""

    def key(self) -> tuple:
        return (self.hwnd, self.raw_title)


ChangeCallback = Callable[["TargetState | None"], None]


class WindowWatcher:
    def __init__(
        self,
        on_change: ChangeCallback,
        *,
        poll_interval: float = 1.0,
    ) -> None:
        self._on_change = on_change
        self._poll = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        self._mode = "auto"
        self._manual_exe = ""
        self._manual_title_contains = ""
        self._blacklist: frozenset[str] = BLACKLIST_EXE
        self._known_paths: frozenset[str] = frozenset()

        self._locked_hwnd: int | None = None
        self._locked_engine: Engine | None = None
        self._last_key: tuple | None = None

    def configure(
        self,
        *,
        mode: str,
        manual_exe: str = "",
        manual_title_contains: str = "",
        blacklist: frozenset[str] = BLACKLIST_EXE,
    ) -> None:
        with self._lock:
            self._mode = mode if mode in ("auto", "manual") else "auto"
            self._manual_exe = (manual_exe or "").strip().lower()
            self._manual_title_contains = (manual_title_contains or "").strip().lower()
            self._blacklist = blacklist
            self._locked_hwnd = None
            self._locked_engine = None

    def set_known_paths(self, paths) -> None:
        """Exe paths of the VNs in the Library. Unlike :meth:`configure` this keeps
        the current lock: it's called whenever a newly detected game is saved."""
        with self._lock:
            self._known_paths = frozenset(os.path.normcase(p) for p in paths if p)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="window-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def poke(self) -> None:
        """Force an immediate re-evaluation (e.g. after the user picks a window)."""
        self._last_key = None

    @staticmethod
    def list_windows() -> list[WindowInfo]:
        return list_top_level_windows()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                pass
            self._stop.wait(self._poll)

    def _tick(self) -> None:
        with self._lock:
            mode = self._mode
            manual_exe = self._manual_exe
            manual_title = self._manual_title_contains
            blacklist = self._blacklist
            known_paths = self._known_paths

        if self._locked_hwnd and is_window(self._locked_hwnd):
            title = get_window_title(self._locked_hwnd)
            if title.strip():
                self._emit(self._locked_hwnd, title, mode)
            return
        if self._locked_hwnd:
            self._locked_hwnd = None
            self._locked_engine = None

        windows = list_top_level_windows()
        windows = [w for w in windows if not is_blacklisted(w.exe, blacklist)]
        target = (
            self._pick_auto(windows, known_paths) if mode == "auto"
            else self._pick_manual(windows, manual_exe, manual_title)
        )
        if target is None:
            if self._last_key is not None:
                self._last_key = None
                self._on_change(None)
            return
        win, engine = target
        self._locked_hwnd = win.hwnd
        self._locked_engine = engine
        self._emit(win.hwnd, win.title, mode, win=win, engine=engine)

    def _emit(
        self,
        hwnd: int,
        title: str,
        mode: str,
        *,
        win: WindowInfo | None = None,
        engine: Engine | None = None,
    ) -> None:
        key = (hwnd, title)
        if key == self._last_key:
            return
        self._last_key = key
        if win is None:
            win = _find(hwnd)
        if win is None:
            return
        engine = engine or self._locked_engine
        self._on_change(
            TargetState(
                hwnd=hwnd,
                pid=win.pid,
                exe=win.exe,
                exe_path=win.exe_path,
                raw_title=title,
                engine_name=engine.name if engine else "",
            )
        )

    def _pick_auto(
        self, windows: list[WindowInfo], known_paths: frozenset[str] = frozenset()
    ) -> tuple[WindowInfo, Engine | None] | None:
        best: tuple[WindowInfo, Engine | None] | None = None
        best_score = 0
        for win in windows:
            engine, score = detect_engine(win)
            if win.exe_path and os.path.normcase(win.exe_path) in known_paths:
                score = _KNOWN_GAME_SCORE
            if score > best_score:
                best, best_score = (win, engine), score
        return best

    def _pick_manual(
        self, windows: list[WindowInfo], manual_exe: str, manual_title: str
    ) -> tuple[WindowInfo, Engine | None] | None:
        if not manual_exe:
            return None
        for win in windows:
            if win.exe.lower() != manual_exe:
                continue
            if manual_title and manual_title not in win.title.lower():
                continue
            engine, _ = detect_engine(win)
            return win, engine
        return None


def _find(hwnd: int) -> WindowInfo | None:
    for win in list_top_level_windows():
        if win.hwnd == hwnd:
            return win
    return None
