from __future__ import annotations

import threading
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk
from PIL import Image

from ..core import VNRPCEngine
from ..covers import store_cropped_image
from ..vndb import ReleaseCover, VNResult
from . import theme as t
from .crop_dialog import CropDialog
from .images import fetch_full_image_async, fetch_image_async, make_ctk_image

PREVIEW_ASPECT = 150 / 212

THUMB = (104, 146)
COLUMNS = 4

_TYPE_LABELS = {
    "pkgfront": "Front",
    "pkgback": "Back",
    "pkgside": "Side",
    "pkgmed": "Medium",
    "dig": "Digital",
}


class ReleaseCoverDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        engine: VNRPCEngine,
        exe: str,
        vn: VNResult,
        *,
        on_picked: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.engine = engine
        self.exe = exe
        self.vn = vn
        self.on_picked = on_picked
        self._covers: list[ReleaseCover] = []
        t.setup_window(self, title=f"Release covers — {vn.title}", geometry="720x640",
                       minsize=(600, 440), modal_for=master)
        self.bind("<Escape>", lambda _e: self.destroy())

        ctk.CTkLabel(self, text=t.ellipsize(vn.title, 60), font=t.font(18, "bold"), text_color=t.TEXT,
                     anchor="w").pack(fill="x", padx=20, pady=(16, 0))
        self.status = t.muted(self, "Loading releases…")
        self.status.pack(fill="x", padx=20, pady=(2, 8))

        self.grid_box = t.scrollable(self)
        self.grid_box.pack(fill="both", expand=True, padx=12, pady=(0, 14))
        for c in range(COLUMNS):
            self.grid_box.grid_columnconfigure(c, weight=1)

        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            covers = self.engine.get_release_covers(self.vn.id)
            err = ""
        except Exception as exc:
            covers, err = [], str(exc)
        try:
            self.after(0, lambda: self._show(covers, err))
        except Exception:
            pass

    def _status_text(self) -> str:
        n = len(self._covers)
        return f"{n} cover{'s' if n != 1 else ''} across this VN's releases — pick one"

    def _show(self, covers: list[ReleaseCover], err: str) -> None:
        if not self.winfo_exists():
            return
        if err:
            self.status.configure(text=f"Couldn't load releases: {err}", text_color=t.RED)
            return
        if not covers:
            self.status.configure(text="No alternate release covers found for this VN.")
            return
        self._covers = covers
        self.status.configure(text=self._status_text())

        allow_nsfw = self.engine.config["allow_nsfw_covers"]
        for i, rc in enumerate(covers):
            cell = t.card(self.grid_box, corner_radius=10)
            cell.grid(row=i // COLUMNS, column=i % COLUMNS, padx=6, pady=6, sticky="nsew")

            blur = rc.is_nsfw and not allow_nsfw
            thumb = ctk.CTkLabel(cell, text="", image=make_ctk_image(None, THUMB, radius=6))
            thumb.pack(padx=10, pady=(10, 6))
            fetch_image_async(rc.url, THUMB, lambda img, lbl=thumb: img and lbl.configure(image=img),
                              widget=thumb, blur=blur, radius=6)

            caption = _TYPE_LABELS.get(rc.type, rc.type or "Cover")
            if rc.is_nsfw:
                caption += " · NSFW"
            ctk.CTkLabel(cell, text=caption, font=t.font(12, "bold"),
                         text_color=t.YELLOW if rc.is_nsfw else t.TEXT).pack()
            t.muted(cell, t.ellipsize(rc.release_title, 44), size=10, wraplength=120,
                    anchor="center", justify="center").pack(padx=8)
            btns = ctk.CTkFrame(cell, fg_color="transparent")
            btns.pack(pady=(8, 10))
            t.primary_button(btns, "Use", lambda r=rc: self._pick(r), width=54, height=28).pack(
                side="left", padx=(0, 4))
            t.secondary_button(btns, "Crop…", lambda r=rc: self._crop(r), width=60, height=28).pack(side="left")

    def _pick(self, rc: ReleaseCover) -> None:
        if rc.is_nsfw and not self.engine.config["allow_nsfw_covers"]:
            if not messagebox.askyesno(
                "NSFW cover",
                "This release image is flagged NSFW on VNDB. It will be shown blurred in the "
                "app and NOT sent to Discord unless you enable NSFW covers in Settings."
                "\n\nUse it anyway?",
                parent=self,
            ):
                return
        self.engine.apply_release_cover(self.exe, self.vn, rc.url)
        self._finish()

    def _finish(self) -> None:
        on_picked = self.on_picked
        self.destroy()
        if on_picked:
            on_picked()

    def _crop(self, rc: ReleaseCover) -> None:
        self.status.configure(text="Fetching image to crop…")

        def done(img: "Image.Image | None") -> None:
            self.status.configure(text=self._status_text())
            if img is None:
                messagebox.showerror("Crop", "Couldn't download the image.", parent=self)
                return

            def on_done(cropped: "Image.Image | None") -> None:
                if cropped is None:
                    return
                stored = store_cropped_image(cropped)
                self.engine.apply_cover_local(self.exe, stored)
                self._finish()

            CropDialog(self, img, aspect=PREVIEW_ASPECT, on_done=on_done)

        fetch_full_image_async(rc.url, done, widget=self)
