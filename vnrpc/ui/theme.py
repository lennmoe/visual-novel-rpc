from __future__ import annotations

import customtkinter as ctk

from ..paths import APP_ICON_ICO

BG = ("#F2F3F5", "#111214")
SURFACE = ("#FFFFFF", "#1B1C20")        # cards
SURFACE_ALT = ("#E8E9ED", "#24262B")    # panels inside cards, inputs
SURFACE_HOVER = ("#DCDEE3", "#2E3036")
BORDER = ("#D6D8DD", "#2B2D33")
TEXT = ("#1E1F22", "#F2F3F5")
MUTED = ("#5C5F66", "#A3A7B0")
SUBTLE = ("#80848E", "#6F737C")

ACCENT = "#5865F2"
ACCENT_HOVER = "#4752C4"
ACCENT_SOFT = ("#E3E5FD", "#2A2D52")    # tinted background for accent chips
GREEN = "#23A55A"
RED = "#F23F43"
RED_HOVER = "#C9302F"
YELLOW = "#F0B232"
YELLOW_SOFT = ("#FCF1D6", "#3A3120")

RADIUS = 12


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(size=size, weight=weight)


def mono(size: int = 12) -> ctk.CTkFont:
    return ctk.CTkFont(family="Consolas", size=size)


def primary_button(parent, text: str, command=None, **kw) -> ctk.CTkButton:
    kw.setdefault("height", 34)
    return ctk.CTkButton(
        parent, text=text, command=command, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        text_color="white", corner_radius=8, font=font(13, "bold"), **kw,
    )


def secondary_button(parent, text: str, command=None, **kw) -> ctk.CTkButton:
    kw.setdefault("height", 34)
    return ctk.CTkButton(
        parent, text=text, command=command, fg_color=SURFACE_ALT, hover_color=SURFACE_HOVER,
        text_color=TEXT, border_width=1, border_color=BORDER, corner_radius=8, font=font(13), **kw,
    )


def danger_button(parent, text: str, command=None, **kw) -> ctk.CTkButton:
    kw.setdefault("height", 34)
    return ctk.CTkButton(
        parent, text=text, command=command, fg_color="transparent", hover_color=("#FBE1E2", "#3A1F22"),
        text_color=RED, border_width=1, border_color=("#F3B8BA", "#5A2A2E"), corner_radius=8,
        font=font(13), **kw,
    )


def card(parent, **kw) -> ctk.CTkFrame:
    kw.setdefault("corner_radius", RADIUS)
    return ctk.CTkFrame(parent, fg_color=SURFACE, border_width=1, border_color=BORDER, **kw)


def panel(parent, **kw) -> ctk.CTkFrame:
    kw.setdefault("corner_radius", 10)
    return ctk.CTkFrame(parent, fg_color=SURFACE_ALT, **kw)


def overline(parent, text: str, color=SUBTLE) -> ctk.CTkLabel:
    """Small all-caps section label."""
    return ctk.CTkLabel(parent, text=text.upper(), font=font(11, "bold"), text_color=color, anchor="w")


def muted(parent, text: str = "", size: int = 12, **kw) -> ctk.CTkLabel:
    kw.setdefault("anchor", "w")
    kw.setdefault("justify", "left")
    return ctk.CTkLabel(parent, text=text, font=font(size), text_color=MUTED, **kw)


def chip(parent, text: str = "", *, fg_color=ACCENT_SOFT, text_color=TEXT) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent, text=text, fg_color=fg_color, text_color=text_color, corner_radius=8,
        font=font(12, "bold"), height=26,
    )


def entry(parent, **kw) -> ctk.CTkEntry:
    kw.setdefault("height", 34)
    return ctk.CTkEntry(
        parent, fg_color=SURFACE_ALT, border_color=BORDER, border_width=1, corner_radius=8,
        text_color=TEXT, **kw,
    )


def segmented(parent, values: list[str], command=None, **kw) -> ctk.CTkSegmentedButton:
    return ctk.CTkSegmentedButton(
        parent, values=values, command=command, fg_color=SURFACE_ALT, unselected_color=SURFACE_ALT,
        unselected_hover_color=SURFACE_HOVER, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
        text_color=TEXT, corner_radius=8, font=font(12, "bold"), height=30, **kw,
    )


def switch(parent, text: str, value: bool, hint: str = "") -> ctk.CTkSwitch:
    """A labelled toggle row, optionally with a muted one-line explanation under it."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", padx=16, pady=(6, 0 if hint else 6))
    sw = ctk.CTkSwitch(
        row, text=text, font=font(13), text_color=TEXT, progress_color=ACCENT,
        button_color=("#FFFFFF", "#F2F3F5"), button_hover_color=("#FFFFFF", "#FFFFFF"),
        fg_color=("#C4C7CE", "#3A3D44"),
    )
    sw.pack(anchor="w")
    if hint:
        muted(row, hint, size=11).pack(anchor="w", padx=(50, 0), pady=(0, 4))
    if value:
        sw.select()
    else:
        sw.deselect()
    return sw


def scrollable(parent, **kw) -> ctk.CTkScrollableFrame:
    return ctk.CTkScrollableFrame(
        parent, fg_color="transparent", scrollbar_button_color=SURFACE_HOVER,
        scrollbar_button_hover_color=SUBTLE, **kw,
    )


def ellipsize(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def setup_window(win, *, title: str, geometry: str | None = None, minsize: tuple[int, int] | None = None,
                 resizable: bool = True, modal_for=None) -> None:
    """Common Toplevel setup: title, size, app icon, background, and (optionally)
    modal to ``modal_for``."""
    win.title(title)
    if geometry:  # None: size to content
        win.geometry(geometry)
    if minsize:
        win.minsize(*minsize)
    win.resizable(resizable, resizable)
    win.configure(fg_color=BG)
    set_icon(win)
    if modal_for is not None:
        win.transient(modal_for)
        # grab_set fails if the window isn't viewable yet; retry briefly
        win.after(80, lambda: _safe_grab(win))


def set_icon(win) -> None:
    # NB: iconbitmap(), not iconphoto(): CTk windows overwrite the icon ~200 ms
    # after creation with CustomTkinter's own, unless iconbitmap() was called.
    if APP_ICON_ICO.exists():
        try:
            win.iconbitmap(str(APP_ICON_ICO))
        except Exception:
            pass


def _safe_grab(win) -> None:
    try:
        if win.winfo_exists():
            win.grab_set()
            win.focus_force()
    except Exception:
        pass
