from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .engines import Engine, detect_engine
from .winapi import WindowInfo, get_window_title, is_window, list_top_level_windows


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

        self._locked_hwnd: int | None = None
        self._locked_engine: Engine | None = None
        self._last_key: tuple | None = None

    # ---- config ---------------------------------------------------
    def configure(self, *, mode: str, manual_exe: str = "", manual_title_contains: str = "") -> None:
        with self._lock:
            self._mode = mode if mode in ("auto", "manual") else "auto"
            self._manual_exe = (manual_exe or "").strip().lower()
            self._manual_title_contains = (manual_title_contains or "").strip().lower()
            self._locked_hwnd = None
            self._locked_engine = None

    # ---- lifecycle ---------------------------------------------
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

    # ---- helpers for the UI --------------------------------------
    @staticmethod
    def list_windows() -> list[WindowInfo]:
        return list_top_level_windows()

    # ---- worker ------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # never let the watcher thread die
                pass
            self._stop.wait(self._poll)

    def _tick(self) -> None:
        with self._lock:
            mode = self._mode
            manual_exe = self._manual_exe
            manual_title = self._manual_title_contains

        # still locked and window alive? just check for a title change.
        if self._locked_hwnd and is_window(self._locked_hwnd):
            title = get_window_title(self._locked_hwnd)
            if title.strip():
                self._emit(self._locked_hwnd, title, mode)
            # an empty title is usually a loading screen: keep the lock rather
            # than reporting the game as closed (which resets the session timer)
            return
        # lost it
        if self._locked_hwnd:
            self._locked_hwnd = None
            self._locked_engine = None

        windows = list_top_level_windows()
        target = self._pick_auto(windows) if mode == "auto" else self._pick_manual(windows, manual_exe, manual_title)
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

    def _pick_auto(self, windows: list[WindowInfo]) -> tuple[WindowInfo, Engine] | None:
        best: tuple[WindowInfo, Engine] | None = None
        best_score = 0
        for win in windows:
            engine, score = detect_engine(win)
            if engine and score > best_score:
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
