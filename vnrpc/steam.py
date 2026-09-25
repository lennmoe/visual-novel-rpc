from __future__ import annotations

import re
import winreg
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass
class SteamApp:
    appid: str
    name: str
    install_dir: Path


def steam_path() -> Path | None:
    for hive, sub in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ):
        try:
            with winreg.OpenKey(hive, sub) as key:
                value, _ = winreg.QueryValueEx(key, "SteamPath")
        except OSError:
            continue
        path = Path(value)
        if path.is_dir():
            return path
    return None


def _library_folders(base: Path) -> list[Path]:
    libs = [base]
    vdf = base / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return libs
    for m in re.finditer(r'"path"\s*"([^"]+)"', text):
        path = Path(m.group(1).replace("\\\\", "\\"))
        if path.is_dir():
            libs.append(path)
    return libs


def _vdf_value(text: str, key: str) -> str:
    m = re.search(rf'"{re.escape(key)}"\s*"([^"]*)"', text, re.IGNORECASE)
    return m.group(1) if m else ""


def _parse_manifest(path: Path) -> SteamApp | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    appid = _vdf_value(text, "appid")
    name = _vdf_value(text, "name")
    installdir = _vdf_value(text, "installdir")
    if not (appid and name and installdir):
        return None
    return SteamApp(appid=appid, name=name, install_dir=path.parent / "common" / installdir)


@lru_cache(maxsize=1)
def installed_apps() -> tuple[SteamApp, ...]:
    """Every Steam app installed across all libraries, cached for the process lifetime."""
    base = steam_path()
    if base is None:
        return ()
    apps: list[SteamApp] = []
    for lib in _library_folders(base):
        steamapps_dir = lib / "steamapps"
        if not steamapps_dir.is_dir():
            continue
        for manifest in steamapps_dir.glob("appmanifest_*.acf"):
            app = _parse_manifest(manifest)
            if app:
                apps.append(app)
    return tuple(apps)


def app_for_exe(exe_path: str) -> SteamApp | None:
    """Which installed Steam app (if any) a running exe belongs to."""
    if not exe_path:
        return None
    try:
        exe = Path(exe_path).resolve()
    except OSError:
        return None
    for app in installed_apps():
        try:
            if exe.is_relative_to(app.install_dir.resolve()):
                return app
        except (OSError, ValueError):
            continue
    return None
