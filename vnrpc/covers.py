from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .paths import COVER_CACHE_DIR, LOCAL_COVER_DIR, ensure_dirs
from .vndb import VNDBClient, VNResult

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


@dataclass
class Cover:
    source: str = "none"
    value: str = ""
    local_path: str | None = None
    discord_image: str = ""
    display_url: str = ""
    nsfw: bool = False
    label: str = ""

    @property
    def is_empty(self) -> bool:
        return self.source == "none" or not self.value


def resolve_cover(
    source: str,
    value: str,
    *,
    vndb: VNDBClient,
    allow_nsfw: bool,
    default_asset_key: str,
    label: str = "",
    vn: VNResult | None = None,
) -> Cover:
    """``vn``: the already-resolved VN, if the caller has it -- saves a VNDB
    round-trip (this runs on every window-title change)."""
    ensure_dirs()
    source = (source or "none").lower()

    if source == "vndb" and value:
        if vn is None or vn.id != (value if value.startswith("v") else "v" + value):
            vn = vndb.get_vn(value)
        if vn is None:
            return Cover(source="none")
        nsfw = vn.is_nsfw
        usable = bool(vn.image_url) and (allow_nsfw or not nsfw)
        local = vndb.cover_path(vn.id, vn.image_url) if vn.image_url else None
        return Cover(
            source="vndb",
            value=vn.id,
            local_path=local,
            discord_image=vn.image_url if usable else default_asset_key,
            display_url=vn.image_url,
            nsfw=nsfw,
            label=label or vn.title,
        )

    if source == "url" and value:
        return Cover(
            source="url",
            value=value,
            local_path=_download_preview(value, vndb),
            discord_image=value if value.lower().startswith(("http://", "https://")) else default_asset_key,
            display_url=value,
            label=label,
        )

    if source == "local" and value:
        stored = _store_local(value)
        return Cover(
            source="local",
            value=stored or value,
            local_path=stored or value,
            discord_image=default_asset_key,
            display_url="",
            label=label,
        )

    return Cover(source="none")


def cover_from_vn(vn: VNResult, *, allow_nsfw: bool, default_asset_key: str) -> Cover:
    usable = bool(vn.image_url) and (allow_nsfw or not vn.is_nsfw)
    return Cover(
        source="vndb",
        value=vn.id,
        discord_image=vn.image_url if usable else default_asset_key,
        display_url=vn.image_url,
        nsfw=vn.is_nsfw,
        label=vn.title,
    )


def store_cropped_image(img: Image.Image) -> str:
    """Save a user-cropped cover to the local cache and return its path."""
    ensure_dirs()
    digest = hashlib.sha1(img.tobytes()).hexdigest()[:16]
    dest = LOCAL_COVER_DIR / f"crop_{digest}.png"
    if not dest.exists():
        img.convert("RGB").save(dest, "PNG")
    return str(dest)


def _store_local(path: str) -> str | None:
    src = Path(path)
    if not src.is_file() or src.suffix.lower() not in _IMAGE_EXTS:
        return None
    digest = hashlib.sha1(str(src.resolve()).encode("utf-8", "ignore")).hexdigest()[:16]
    dest = LOCAL_COVER_DIR / f"{digest}{src.suffix.lower()}"
    try:
        if not dest.exists():
            shutil.copy2(src, dest)
        return str(dest)
    except OSError:
        return str(src)


def _download_preview(url: str, vndb: VNDBClient) -> str | None:
    if not url.lower().startswith(("http://", "https://")):
        return None
    return vndb.cover_path(url_cache_key(url), url)


def url_cache_key(url: str) -> str:
    """Stem under which a ``url`` cover is cached in COVER_CACHE_DIR."""
    return "url_" + hashlib.sha1(url.encode()).hexdigest()[:12]


def cached_cover_for_entry(entry: dict) -> str | None:
    """Best-effort local cover file for a per-game config entry (Library view):
    a saved local file, or whatever got cached on disk the last time this VN's
    cover was resolved. Never touches the network."""
    source = entry.get("cover_source")
    value = entry.get("cover_value", "") or ""
    if source == "local" and value and Path(value).is_file():
        return value
    stems = []
    if source == "url" and value:
        stems.append(url_cache_key(value))
    if entry.get("vndb_id"):
        stems.append(entry["vndb_id"])
    for stem in stems:
        matches = sorted(COVER_CACHE_DIR.glob(f"{stem}.*"))
        if matches:
            return str(matches[0])
    return None
