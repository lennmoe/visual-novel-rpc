from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

try:  # pypresence is optional at import time so tests can stub it
    from pypresence import Presence
    from pypresence.exceptions import PyPresenceException
except Exception:  # pragma: no cover
    Presence = None  # type: ignore

    class PyPresenceException(Exception):
        pass


@dataclass
class Activity:
    name: str = ""                    # activity name override -> the bold header
                                      # line (otherwise Discord shows the app name)
    details: str = ""                 # first line under the header (section)
    state: str = ""                   # second line (extra detail, usually unused)
    large_image: str = ""             # http(s) URL or a Discord asset key
    large_text: str = ""
    small_image: str = ""
    small_text: str = ""
    start: int | None = None          # epoch seconds -> "elapsed" timer
    buttons: list[dict[str, str]] = field(default_factory=list)

    def to_kwargs(self) -> dict:
        kw: dict = {}
        if self.name:
            kw["name"] = self.name[:128]
        if self.details:
            kw["details"] = self.details[:128]
        if self.state:
            kw["state"] = self.state[:128]
        if self.large_image:
            kw["large_image"] = self.large_image
            kw["large_text"] = (self.large_text or self.name or self.details)[:128]
        if self.small_image:
            kw["small_image"] = self.small_image
            if self.small_text:
                kw["small_text"] = self.small_text[:128]
        if self.start:
            kw["start"] = int(self.start)
        if self.buttons:
            kw["buttons"] = self.buttons[:2]
        return kw

    def key(self) -> tuple:
        return (self.name, self.details, self.state, self.large_image, self.large_text,
                self.small_image, self.small_text, self.start,
                tuple(tuple(b.items()) for b in self.buttons))


class PresenceManager:
    def __init__(
        self,
        client_id: str,
        min_interval: float = 15.0,
        on_status: Callable[[bool, str], None] | None = None,
    ) -> None:
        self._client_id = str(client_id)
        self._min_interval = float(min_interval)
        self._on_status = on_status or (lambda connected, msg: None)

        self._rpc = None
        self._connected = False
        self._desired: Activity | None = None
        self._pushed_key: tuple | None = None
        self._last_push = 0.0
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._paused = False
        self._reconnect = False
        self._thread: threading.Thread | None = None

    # ---- public API -------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="presence", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._dirty.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._teardown()

    def set_client_id(self, client_id: str) -> None:
        client_id = str(client_id)
        with self._lock:
            if client_id == self._client_id:
                return
            self._client_id = client_id
            # the worker thread owns the connection: ask it to reconnect rather
            # than closing the socket under it from this (UI) thread
            self._reconnect = True
        self._dirty.set()

    def set_min_interval(self, seconds: float) -> None:
        self._min_interval = max(1.0, float(seconds))

    def set_activity(self, activity: Activity | None) -> None:
        with self._lock:
            self._desired = activity
        self._dirty.set()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
        self._dirty.set()

    @property
    def connected(self) -> bool:
        return self._connected

    # ---- worker ---------------------------------------------------
    def _run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            self._dirty.wait(timeout=self._min_interval)
            self._dirty.clear()
            if self._stop.is_set():
                break

            with self._lock:
                reconnect, self._reconnect = self._reconnect, False
            if reconnect:
                self._teardown()

            if not self._ensure_connected():
                self._stop.wait(backoff)  # interruptible, so quitting stays snappy
                backoff = min(backoff * 1.7, 30.0)
                continue
            backoff = 2.0

            with self._lock:
                desired = self._desired
                paused = self._paused

            try:
                if desired is None or paused:
                    if self._pushed_key is not None:
                        self._rpc.clear()
                        self._pushed_key = None
                    continue
                key = desired.key()
                if key == self._pushed_key:
                    continue
                wait = self._min_interval - (time.monotonic() - self._last_push)
                if wait > 0:
                    # come back when the rate-limit window is open
                    self._dirty.set()
                    self._stop.wait(min(wait, self._min_interval))
                    continue
                self._rpc.update(**desired.to_kwargs())
                self._pushed_key = key
                self._last_push = time.monotonic()
            except (PyPresenceException, OSError, RuntimeError, BrokenPipeError) as exc:
                self._on_status(False, f"lost Discord connection: {exc}")
                self._teardown()
                self._dirty.set()

        self._teardown()

    def _ensure_connected(self) -> bool:
        if self._connected and self._rpc is not None:
            return True
        if Presence is None:
            self._on_status(False, "pypresence not installed")
            return False
        try:
            with self._lock:
                cid = self._client_id
            self._rpc = Presence(cid)
            self._rpc.connect()
            self._connected = True
            self._pushed_key = None
            self._on_status(True, "connected to Discord")
            return True
        except (PyPresenceException, OSError, RuntimeError) as exc:
            self._rpc = None
            self._connected = False
            self._on_status(False, f"Discord not reachable: {exc}")
            return False

    def _teardown(self) -> None:
        rpc, self._rpc = self._rpc, None
        self._connected = False
        self._pushed_key = None
        if rpc is not None:
            try:
                rpc.close()
            except Exception:
                pass
