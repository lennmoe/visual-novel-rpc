from __future__ import annotations

import hashlib
import io
import threading
from collections import OrderedDict
from typing import Callable

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..paths import APP_ICON_PNG, COVER_CACHE_DIR

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover
    ctk = None

_PLACEHOLDER_TOP = (43, 45, 66)
_PLACEHOLDER_BOTTOM = (28, 29, 36)
_PLACEHOLDER_FG = (110, 116, 140)

_HEADERS = {"User-Agent": "VisualNovelRPC/1.0"}
_WEB_CACHE_MAX = 64
_web_cache: "OrderedDict[str, Image.Image]" = OrderedDict()
_web_lock = threading.Lock()


# ---- building CTkImages ------------------------------------------------
def load_image(
    path_or_none: str | None, size: tuple[int, int], *, blur: bool = False, radius: int = 0
) -> "ctk.CTkImage":
    img = None
    if path_or_none:
        try:
            img = Image.open(path_or_none).convert("RGB")
        except Exception:
            img = None
    return make_ctk_image(img, size, blur=blur, radius=radius)


def make_ctk_image(
    img: "Image.Image | None", size: tuple[int, int], *, blur: bool = False, radius: int = 0
) -> "ctk.CTkImage":
    """Cover-fit ``img`` (or a placeholder) into ``size``, optionally blurred and
    with rounded corners. Must be called on the Tk thread."""
    img = _placeholder(size) if img is None else _fit(img.convert("RGB"), size)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(max(6, size[0] // 12)))
    if radius:
        img = _round(img, radius)
    return ctk.CTkImage(light_image=img, dark_image=img, size=size)


# ---- remote images -------------------------------------------------
def fetch_pil(url: str) -> "Image.Image | None":
    """Download (or fetch from the memory/disk cache) an image. Blocking."""
    if not url:
        return None
    with _web_lock:
        cached = _web_cache.get(url)
        if cached is not None:
            _web_cache.move_to_end(url)
            return cached
    disk = COVER_CACHE_DIR / f"web_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:20]}"
    data: bytes | None = None
    try:
        if disk.exists() and disk.stat().st_size > 0:
            data = disk.read_bytes()
    except OSError:
        data = None
    if data is None:
        try:
            resp = requests.get(url, timeout=15, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.content
        except requests.RequestException:
            return None
        try:
            disk.write_bytes(data)
        except OSError:
            pass
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGB")
    except Exception:
        return None
    with _web_lock:
        _web_cache[url] = img
        while len(_web_cache) > _WEB_CACHE_MAX:
            _web_cache.popitem(last=False)
    return img


def fetch_image_async(
    url: str,
    size: tuple[int, int],
    callback: Callable[["ctk.CTkImage | None"], None],
    *,
    widget=None,
    blur: bool = False,
    radius: int = 0,
) -> None:
    """Download ``url`` off the UI thread, then hand a sized CTkImage to
    ``callback`` *on the Tk thread* (via ``widget.after``) -- skipped entirely
    if ``widget`` was destroyed in the meantime."""
    def deliver(pil: "Image.Image | None") -> None:
        if widget is not None and not _alive(widget):
            return
        callback(make_ctk_image(pil, size, blur=blur, radius=radius) if pil is not None else None)

    _run_async(url, deliver, widget)


def fetch_full_image_async(url: str, callback: Callable[["Image.Image | None"], None], *, widget=None) -> None:
    """Like fetch_image_async, but hands back the full-resolution PIL image
    (e.g. to feed into the crop dialog) instead of a pre-shrunk CTkImage."""
    def deliver(pil: "Image.Image | None") -> None:
        if widget is not None and not _alive(widget):
            return
        callback(pil.copy() if pil is not None else None)

    _run_async(url, deliver, widget)


def set_label_image_async(label, url: str, size: tuple[int, int], *, blur: bool = False, radius: int = 0) -> None:
    """Show a placeholder in ``label`` right away, then the downloaded image."""
    label.configure(image=make_ctk_image(None, size, radius=radius))
    fetch_image_async(url, size, lambda img: img and label.configure(image=img),
                      widget=label, blur=blur, radius=radius)


def _run_async(url: str, deliver: Callable[["Image.Image | None"], None], widget) -> None:
    def worker() -> None:
        pil = fetch_pil(url)
        if widget is None:
            deliver(pil)
            return
        try:
            widget.after(0, lambda: deliver(pil))
        except Exception:  # widget/app already gone
            pass

    threading.Thread(target=worker, daemon=True).start()


def _alive(widget) -> bool:
    try:
        return bool(widget.winfo_exists())
    except Exception:
        return False


# ---- tray / app icon --------------------------------------------------
def tray_image(size: int = 64) -> Image.Image:
    """The app's icon (tray icon, window icon, and the source for the .exe icon)."""
    try:
        img = Image.open(APP_ICON_PNG).convert("RGBA")
        return img.resize((size, size), Image.LANCZOS)
    except Exception:
        return _fallback_glyph(size)


def app_icon_image(size: int, radius: int = 0) -> "ctk.CTkImage":
    """The app icon as a (optionally rounded) CTkImage, for headers."""
    img = tray_image(size * 2)
    if radius:
        img = _round(img, radius * 2)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def _fallback_glyph(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=size // 6, fill=(88, 101, 242, 255))
    # a simple open-book glyph
    m = size // 2
    d.line([m, size * 0.28, m, size * 0.74], fill=(255, 255, 255, 255), width=max(2, size // 20))
    d.arc([size * 0.16, size * 0.28, m, size * 0.78], 300, 60, fill=(255, 255, 255, 255), width=max(2, size // 20))
    d.arc([m, size * 0.28, size * 0.84, size * 0.78], 120, 240, fill=(255, 255, 255, 255), width=max(2, size // 20))
    return img


# ---- pixel helpers ---------------------------------------------------
def _fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new = img.resize((max(1, round(src_w * scale)), max(1, round(src_h * scale))), Image.LANCZOS)
    left = (new.width - target_w) // 2
    top = (new.height - target_h) // 2
    return new.crop((left, top, left + target_w, top + target_h))


def _round(img: Image.Image, radius: int) -> Image.Image:
    # draw the mask at 4x and shrink it for smooth (anti-aliased) corners
    w, h = img.size
    big = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(big).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1], radius=radius * 4, fill=255)
    mask = big.resize((w, h), Image.LANCZOS)
    out = img.convert("RGBA")
    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))  # keep existing transparency
    return out


def _placeholder(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, _PLACEHOLDER_BOTTOM)
    d = ImageDraw.Draw(img)
    for y in range(h):  # soft vertical gradient
        t = y / max(1, h - 1)
        d.line([0, y, w, y], fill=tuple(round(a + (b - a) * t) for a, b in zip(_PLACEHOLDER_TOP, _PLACEHOLDER_BOTTOM)))
    # an open book, centred
    s = min(w, h) * 0.36
    cx, cy = w / 2, h / 2
    lw = max(1, round(min(w, h) / 50))
    left = [(cx, cy - s * 0.32), (cx - s * 0.5, cy - s * 0.42), (cx - s * 0.5, cy + s * 0.32), (cx, cy + s * 0.42)]
    right = [(cx, cy - s * 0.32), (cx + s * 0.5, cy - s * 0.42), (cx + s * 0.5, cy + s * 0.32), (cx, cy + s * 0.42)]
    d.line(left + [left[0]], fill=_PLACEHOLDER_FG, width=lw, joint="curve")
    d.line(right + [right[0]], fill=_PLACEHOLDER_FG, width=lw, joint="curve")
    return img
