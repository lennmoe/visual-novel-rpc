from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

from .winapi import WindowInfo

# Processes that are never a visual novel, regardless of window title.
BLACKLIST_EXE = {
    "explorer.exe", "chrome.exe", "firefox.exe", "msedge.exe", "brave.exe",
    "opera.exe", "discord.exe", "spotify.exe", "code.exe", "devenv.exe",
    "steam.exe", "steamwebhelper.exe", "obs64.exe", "obs32.exe", "notepad.exe",
    "notepad++.exe", "python.exe", "pythonw.exe", "cmd.exe", "powershell.exe",
    "windowsterminal.exe", "textinputhost.exe", "searchhost.exe",
    "applicationframehost.exe", "systemsettings.exe", "taskmgr.exe",
    "vnrpc.exe", "visualnovelrpc.exe",
}

# Data files that mark a directory as "a visual novel lives here".
VN_DATA_MARKERS = (
    ".xp3", ".rpa", ".rpyc", ".nsa", ".sar", ".dat.arc", ".pfs",
    "arc.dat", "data.xp3", "patch.xp3", "game.exe", "startup.tjs",
    "*.rgss3a", "advdata", "bgm", "scenario",
)


@dataclass
class Engine:
    name: str
    icon_key: str                       # Discord small-image asset key (optional to define)
    exe_patterns: tuple[str, ...] = ()   # regex, matched against the lowercased exe name
    class_patterns: tuple[str, ...] = ()  # regex, matched against the window class name
    dir_files: tuple[str, ...] = ()      # filenames whose presence next to the exe is a strong signal
    title_cleaners: tuple[str, ...] = field(default_factory=tuple)  # regex removed from titles

    def score(self, win: WindowInfo) -> int:
        exe = win.exe.lower()
        cls = (win.class_name or "").lower()
        pts = 0
        if any(re.search(p, exe) for p in self.exe_patterns):
            pts += 40
        if any(re.search(p, cls) for p in self.class_patterns):
            pts += 25
        if self.dir_files and win.exe_path:
            folder = os.path.dirname(win.exe_path)
            try:
                listing = {n.lower() for n in os.listdir(folder)}
            except OSError:
                listing = set()
            if any(any(f in n for n in listing) for f in self.dir_files):
                pts += 20
        return pts

    def clean_title(self, title: str) -> str:
        out = _fix_mojibake(title)
        for pat in self.title_cleaners:
            out = re.sub(pat, "", out, flags=re.IGNORECASE)
        return _tidy(out)


# Noise present in almost every VN window title, stripped for all engines.
COMMON_CLEANERS = (
    r"\s*[-–—]\s*steam\s*$",
    r"[\(\[【]?R[\-\s]?18\+?[\)\]】]?(?:版|edition)?[@＠]*",  # age-rating marker: "R18", "R18版", "(R-18)"
    r"\s*\[?\d{3,4}\s*[xX]\s*\d{3,4}\]?",          # resolution
    r"\s*\bver(?:sion)?\.?\s*\d+(?:[.;]\d+)*[a-z]?\b",  # "ver. 1.03", "version 2"
    r"\s*\[ver\.[^\]]*\]",
    r"\s*[\[(]\s*v?\d+(?:[.;]\d+)+[a-z]?\s*[\])]",   # bracketed version: "[1.05]", "(v2.0)"
    r"\s*\bv\d+(?:[.;]\d+)+[a-z]?\b",                 # "v1.00", "v1.0.3"
    r"\s*(?<![\w/])\d+[.;]\d+(?:[.;]\d+)*[a-z]?\b",   # bare version: "1.00", "1;00", "2.1.4a"
    r"\s*\bfps[:=]?\s*\d+\b",
    r"\s*\bDirect3D\b|\s*\bOpenGL\b",
    r"\s*[\[(（【]\s*[\])）】]",                      # empty brackets left by the above
)

ENGINES: tuple[Engine, ...] = (
    Engine(
        name="Ren'Py", icon_key="engine_renpy",
        # No exe_patterns: Ren'Py games are named after the game, not the
        # engine, so a wildcard here would (and used to) match every process
        # on the system. Rely on the SDL/pygame window class and the VN data
        # files Ren'Py ships (.rpa/.rpyc, game/script) instead.
        class_patterns=(r"^sdl_app$", r"pygame", r"renpy"),
        dir_files=(".rpa", ".rpyc", "renpy", "game/script"),
        title_cleaners=COMMON_CLEANERS,
    ),
    Engine(
        name="KiriKiri", icon_key="engine_kirikiri",
        exe_patterns=(r"^krkr", r"kirikiri", r"^bgi\.exe$"),
        class_patterns=(r"^tform", r"kirikiri"),
        dir_files=(".xp3", "data.xp3", "startup.tjs"),
        title_cleaners=COMMON_CLEANERS,
    ),
    Engine(
        name="TyranoScript", icon_key="engine_tyrano",
        exe_patterns=(r"nw\.exe$", r"tyrano"),
        class_patterns=(r"^nw_", r"chrome_widgetwin"),
        dir_files=("tyrano", "data/scenario"),
        title_cleaners=COMMON_CLEANERS,
    ),
    Engine(
        name="SiglusEngine", icon_key="engine_siglus",
        exe_patterns=(r"siglus", r"^gameexe"),
        dir_files=("scene.pck", "gameexe.dat"),
        title_cleaners=COMMON_CLEANERS,
    ),
    Engine(
        name="RealLive", icon_key="engine_reallive",
        exe_patterns=(r"reallive", r"^rlvm"),
        dir_files=("seen.txt", "gameexe.ini"),
        title_cleaners=COMMON_CLEANERS,
    ),
    Engine(
        name="Artemis", icon_key="engine_artemis",
        exe_patterns=(r"artemis",),
        dir_files=(".pfs", "root.pfs"),
        title_cleaners=COMMON_CLEANERS,
    ),
    Engine(
        name="YU-RIS", icon_key="engine_yuris",
        exe_patterns=(r"yuris", r"^ys_"),
        dir_files=("ysbin", "ypf"),
        title_cleaners=COMMON_CLEANERS,
    ),
    Engine(
        name="NScripter", icon_key="engine_nscripter",
        exe_patterns=(r"nscr", r"onscripter", r"ons\.exe$"),
        dir_files=("nscript.dat", "0.txt", "arc.nsa"),
        title_cleaners=COMMON_CLEANERS,
    ),
    Engine(
        name="Unity", icon_key="engine_unity",
        exe_patterns=(),
        class_patterns=(r"^unitywndclass$",),
        dir_files=("_data/globalgamemanagers", "unityplayer.dll"),
        title_cleaners=COMMON_CLEANERS,
    ),
)

_GENERIC = Engine(name="", icon_key="app", title_cleaners=COMMON_CLEANERS)


def detect_engine(win: WindowInfo) -> tuple[Engine | None, int]:
    """Return the best matching engine and its score (0 if nothing plausible)."""
    if win.exe.lower() in BLACKLIST_EXE:
        return None, 0
    best: Engine | None = None
    best_score = 0
    for eng in ENGINES:
        s = eng.score(win)
        if s > best_score:
            best, best_score = eng, s
    # Require a real signal (an exe/class pattern, or VN data files beside
    # the exe) before claiming a match, so random non-VN windows score 0.
    if best_score >= 20:
        return best, best_score
    return None, 0


def clean_title(title: str, engine: Engine | None) -> str:
    return (engine or _GENERIC).clean_title(title)


def _tidy(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = text.strip(" -–—|:·•")
    return text.strip()


# A handful of old (pre-Unicode) Japanese engines set their window title through
# the ANSI Win32 API using Shift-JIS bytes. On a Windows install whose "language
# for non-Unicode programs" isn't Japanese, GetWindowTextW's automatic ANSI->
# Unicode conversion mangles those bytes into unrelated Latin-1 characters
# before we ever see the string. Undo the byte pairs this produces in practice.
_MOJIBAKE_FIXES = {
    "\x81\x40": " ",  # Shift-JIS fullwidth space (0x8140), a very common separator
}


def _fix_mojibake(text: str) -> str:
    for bad, good in _MOJIBAKE_FIXES.items():
        text = text.replace(bad, good)
    return text
