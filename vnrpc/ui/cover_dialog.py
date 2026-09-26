from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from ..core import VNRPCEngine
from ..covers import store_cropped_image
from ..vndb import VNResult
from . import theme as t
from .crop_dialog import CropDialog
from .images import fetch_full_image_async, fetch_image_async, load_image, make_ctk_image
from .release_dialog import ReleaseCoverDialog

THUMB = (72, 102)
PREVIEW = (150, 212)

_PRIVACY_HELP = {
    "Full": "Discord shows the name, the current section and the cover.",
    "Partial": "Discord shows the name and cover, but not where you are in the story.",
    "Private": "Discord only shows a generic “Visual Novel” — no name, no cover.",
    "Off": "Nothing is shared on Discord while this game is open.",
}


class CoverDialog(ctk.CTkToplevel):
    def __init__(self, master, engine: VNRPCEngine, exe: str, game_name: str) -> None:
        super().__init__(master)
        self.engine = engine
        self.exe = exe
        t.setup_window(self, title=f"Cover & privacy — {game_name or exe}", geometry="820x700",
                       minsize=(680, 540), modal_for=master)
        self.bind("<Escape>", lambda _e: self.destroy())

        self._results: list[VNResult] = []
        self._search_gen = 0

        priv = t.card(self)
        priv.pack(fill="x", padx=16, pady=(16, 0))
        row = ctk.CTkFrame(priv, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(12, 2))
        ctk.CTkLabel(row, text="Discord privacy for this game", font=t.font(13, "bold"),
                     text_color=t.TEXT).pack(side="left")
        self.privacy = t.segmented(row, list(_PRIVACY_HELP), command=self._set_privacy)
        current = (self.engine.config.game_override(exe).get("privacy") or "full").capitalize()
        self.privacy.set(current if current in _PRIVACY_HELP else "Full")
        self.privacy.pack(side="right")
        self.privacy_help = t.muted(priv, _PRIVACY_HELP[self.privacy.get()], size=11)
        self.privacy_help.pack(fill="x", padx=16, pady=(0, 12))

        tabs = ctk.CTkTabview(
            self, fg_color=t.SURFACE, border_width=1, border_color=t.BORDER, corner_radius=t.RADIUS,
            segmented_button_fg_color=t.SURFACE_ALT, segmented_button_selected_color=t.ACCENT,
            segmented_button_selected_hover_color=t.ACCENT_HOVER,
            segmented_button_unselected_color=t.SURFACE_ALT,
            segmented_button_unselected_hover_color=t.SURFACE_HOVER, text_color=t.TEXT,
        )
        tabs.pack(fill="both", expand=True, padx=16, pady=(10, 16))
        self.tab_vndb = tabs.add("Search VNDB")
        self.tab_url = tabs.add("Image URL")
        self.tab_local = tabs.add("Local file")
        tabs.set("Search VNDB")

        self._build_vndb(game_name)
        self._build_url()
        self._build_local()

    def _set_privacy(self, value: str) -> None:
        self.privacy_help.configure(text=_PRIVACY_HELP.get(value, ""))
        self.engine.set_game_privacy(self.exe, value.lower())

    def _build_vndb(self, initial_query: str) -> None:
        top = ctk.CTkFrame(self.tab_vndb, fg_color="transparent")
        top.pack(fill="x", padx=4, pady=(4, 8))
        self.query = t.entry(top, placeholder_text="Visual novel title…")
        self.query.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.query.insert(0, initial_query or "")
        self.query.bind("<Return>", lambda _e: self._do_search())
        t.primary_button(top, "Search", self._do_search, width=100).pack(side="left")

        self.vndb_status = t.muted(self.tab_vndb, "", size=11)
        self.vndb_status.pack(fill="x", padx=6, pady=(0, 4))
        self.results_box = t.scrollable(self.tab_vndb)
        self.results_box.pack(fill="both", expand=True)
        if initial_query:
            self.after(200, self._do_search)

    def _do_search(self) -> None:
        query = self.query.get().strip()
        if not query:
            return
        self._search_gen += 1
        gen = self._search_gen
        self.vndb_status.configure(text="Searching…")
        for w in self.results_box.winfo_children():
            w.destroy()

        def worker() -> None:
            try:
                results = self.engine.search_vndb(query, limit=12)
                err = ""
            except Exception as exc:
                results, err = [], str(exc)
            try:
                self.after(0, lambda: self._show_results(gen, results, err))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _show_results(self, gen: int, results: list[VNResult], err: str) -> None:
        if gen != self._search_gen or not self.winfo_exists():
            return
        self._results = results
        if err:
            self.vndb_status.configure(text=f"Search failed: {err}", text_color=t.RED)
            return
        self.vndb_status.configure(
            text=f"{len(results)} result{'s' if len(results) != 1 else ''}" if results
            else "No results — try the original (Japanese) or a shorter title.",
            text_color=t.MUTED,
        )
        allow_nsfw = self.engine.config["allow_nsfw_covers"]
        for vn in results:
            row = t.card(self.results_box, corner_radius=10)
            row.pack(fill="x", pady=4, padx=4)
            row.grid_columnconfigure(1, weight=1)

            blur = vn.is_nsfw and not allow_nsfw
            thumb = ctk.CTkLabel(row, text="", image=make_ctk_image(None, THUMB, radius=6))
            thumb.grid(row=0, column=0, rowspan=3, padx=10, pady=10)
            if vn.image_url:
                fetch_image_async(vn.image_url, THUMB, lambda img, lbl=thumb: img and lbl.configure(image=img),
                                  widget=thumb, blur=blur, radius=6)

            name = vn.title + (f"  ({vn.year})" if vn.year else "")
            ctk.CTkLabel(row, text=t.ellipsize(name, 70), anchor="w", font=t.font(14, "bold"),
                         text_color=t.TEXT).grid(row=0, column=1, sticky="sw", pady=(12, 0))
            t.muted(row, t.ellipsize(vn.alt_title or "", 70)).grid(row=1, column=1, sticky="nw")
            meta = ctk.CTkFrame(row, fg_color="transparent")
            meta.grid(row=2, column=1, sticky="nw", pady=(4, 10))
            t.chip(meta, f" {vn.id} ", fg_color=t.SURFACE_ALT, text_color=t.MUTED).pack(side="left")
            if vn.rating:
                t.chip(meta, f" ★ {vn.rating / 10:.1f} " if vn.rating > 10 else f" ★ {vn.rating:.1f} ",
                       fg_color=t.SURFACE_ALT, text_color=t.MUTED).pack(side="left", padx=(6, 0))
            if vn.is_nsfw:
                t.chip(meta, " NSFW cover ", fg_color=t.YELLOW_SOFT, text_color=t.YELLOW).pack(
                    side="left", padx=(6, 0))

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.grid(row=0, column=2, rowspan=3, padx=10)
            t.secondary_button(btns, "Crop…", lambda v=vn: self._crop_vn(v), width=70).pack(side="left")
            t.secondary_button(btns, "Other covers…", lambda v=vn: self._browse_covers(v), width=110).pack(
                side="left", padx=6)
            t.primary_button(btns, "Use", lambda v=vn: self._pick_vn(v), width=64).pack(side="left")

    def _pick_vn(self, vn: VNResult) -> None:
        if vn.is_nsfw and not self.engine.config["allow_nsfw_covers"]:
            if not messagebox.askyesno(
                "NSFW cover",
                "VNDB flags this cover as NSFW. It will be shown blurred in the app and "
                "NOT sent to Discord unless you enable NSFW covers in Settings.\n\nUse it anyway?",
                parent=self,
            ):
                return
        self.engine.apply_vn_choice(self.exe, vn, as_cover=True)
        self.destroy()

    def _browse_covers(self, vn: VNResult) -> None:
        ReleaseCoverDialog(self, self.engine, self.exe, vn, on_picked=self.destroy)

    def _crop_vn(self, vn: VNResult) -> None:
        if not vn.image_url:
            messagebox.showwarning("Crop", "This VN has no cover image to crop.", parent=self)
            return
        self.vndb_status.configure(text="Fetching image to crop…", text_color=t.MUTED)

        def done(img: "Image.Image | None") -> None:
            self.vndb_status.configure(text=f"{len(self._results)} result(s)")
            if img is None:
                messagebox.showerror("Crop", "Couldn't download the image.", parent=self)
                return
            self._crop_then_apply(img)

        fetch_full_image_async(vn.image_url, done, widget=self)

    def _crop_then_apply(self, img: "Image.Image") -> None:
        """Open the crop dialog on a full-res image; the result is always stored
        locally and applied as a local cover (Discord can't show a cropped-on-the-
        fly remote image, so this matches the existing "local file" cover path)."""
        def on_done(cropped: "Image.Image | None") -> None:
            if cropped is None:
                return
            stored = store_cropped_image(cropped)
            self.engine.apply_cover_local(self.exe, stored)
            self.destroy()

        CropDialog(self, img, aspect=PREVIEW[0] / PREVIEW[1], on_done=on_done)

    def _build_url(self) -> None:
        self._url_cropped_path: str | None = None
        wrap = ctk.CTkFrame(self.tab_url, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=8, pady=8)
        t.muted(wrap, "Paste a direct link to a public image (jpg / png / webp). "
                      "This link is what Discord will display.", size=12).pack(fill="x", pady=(4, 8))
        self.url_entry = t.entry(wrap, placeholder_text="https://…")
        self.url_entry.pack(fill="x")
        self.url_entry.bind("<Return>", lambda _e: self._preview_url())
        self.url_preview = ctk.CTkLabel(wrap, text="", image=make_ctk_image(None, PREVIEW, radius=10))
        self.url_preview.pack(pady=16)
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack()
        t.secondary_button(btns, "Preview", self._preview_url, width=100).pack(side="left", padx=4)
        t.secondary_button(btns, "Crop…", self._crop_url, width=90).pack(side="left", padx=4)
        t.primary_button(btns, "Use this image", self._use_url, width=130).pack(side="left", padx=4)
        self.url_status = t.muted(wrap, "", size=11, anchor="center", justify="center")
        self.url_status.pack(fill="x", pady=(8, 0))

    def _preview_url(self) -> None:
        url = self.url_entry.get().strip()
        if not url.lower().startswith(("http://", "https://")):
            self.url_status.configure(text="Enter a http(s) image link.", text_color=t.RED)
            return
        self._url_cropped_path = None
        self.url_status.configure(text="Loading preview…", text_color=t.MUTED)

        def done(img) -> None:
            if img is None:
                self.url_status.configure(text="Couldn't load an image from that link.", text_color=t.RED)
                return
            self.url_status.configure(text="")
            self.url_preview.configure(image=img)

        fetch_image_async(url, PREVIEW, done, widget=self.url_preview, radius=10)

    def _crop_url(self) -> None:
        url = self.url_entry.get().strip()
        if not url.lower().startswith(("http://", "https://")):
            messagebox.showwarning("Invalid URL", "Enter a http(s) image link.", parent=self)
            return
        self.url_status.configure(text="Fetching image…", text_color=t.MUTED)

        def done(img: "Image.Image | None") -> None:
            self.url_status.configure(text="")
            if img is None:
                messagebox.showerror("Crop", "Couldn't download the image.", parent=self)
                return

            def on_done(cropped: "Image.Image | None") -> None:
                if cropped is None:
                    return
                stored = store_cropped_image(cropped)
                self._url_cropped_path = stored
                self.url_preview.configure(image=load_image(stored, PREVIEW, radius=10))
                self.url_status.configure(
                    text="Cropped. Discord can't show a cropped copy of a link, so it will "
                         "get the fallback image instead.", text_color=t.YELLOW)

            CropDialog(self, img, aspect=PREVIEW[0] / PREVIEW[1], on_done=on_done)

        fetch_full_image_async(url, done, widget=self)

    def _use_url(self) -> None:
        if self._url_cropped_path:
            self.engine.apply_cover_local(self.exe, self._url_cropped_path)
            self.destroy()
            return
        url = self.url_entry.get().strip()
        if not url.lower().startswith(("http://", "https://")):
            messagebox.showwarning("Invalid URL", "Enter a http(s) image link.", parent=self)
            return
        self.engine.apply_cover_url(self.exe, url)
        self.destroy()

    def _build_local(self) -> None:
        wrap = ctk.CTkFrame(self.tab_local, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=8, pady=8)
        t.muted(wrap, "Pick an image on your PC. It's shown in this app, but Discord can't display "
                      "local files, so your presence uses the fallback asset key from Settings.",
                size=12, wraplength=620).pack(fill="x", pady=(4, 8))
        row = ctk.CTkFrame(wrap, fg_color="transparent")
        row.pack(fill="x")
        self.local_path = t.entry(row, placeholder_text="No file selected")
        self.local_path.pack(side="left", fill="x", expand=True, padx=(0, 8))
        t.secondary_button(row, "Browse…", self._browse, width=100).pack(side="left")
        self.local_preview = ctk.CTkLabel(wrap, text="", image=make_ctk_image(None, PREVIEW, radius=10))
        self.local_preview.pack(pady=16)
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack()
        t.secondary_button(btns, "Crop…", self._crop_local, width=90).pack(side="left", padx=4)
        t.primary_button(btns, "Use this file", self._use_local, width=130).pack(side="left", padx=4)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Choose a cover image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"), ("All files", "*.*")],
        )
        if path:
            self.local_path.delete(0, tk.END)
            self.local_path.insert(0, path)
            self.local_preview.configure(image=load_image(path, PREVIEW, radius=10))

    def _crop_local(self) -> None:
        path = self.local_path.get().strip()
        if not path:
            messagebox.showwarning("No file", "Choose an image first.", parent=self)
            return
        try:
            with Image.open(path) as im:
                img = im.convert("RGB")
        except Exception as exc:
            messagebox.showerror("Crop", f"Can't open image: {exc}", parent=self)
            return

        def done(cropped: "Image.Image | None") -> None:
            if cropped is None:
                return
            stored = store_cropped_image(cropped)
            self.local_path.delete(0, tk.END)
            self.local_path.insert(0, stored)
            self.local_preview.configure(image=load_image(stored, PREVIEW, radius=10))

        CropDialog(self, img, aspect=PREVIEW[0] / PREVIEW[1], on_done=done)

    def _use_local(self) -> None:
        path = self.local_path.get().strip()
        if not path:
            messagebox.showwarning("No file", "Choose an image first.", parent=self)
            return
        try:
            with Image.open(path) as im:
                im.verify()
        except Exception:
            messagebox.showerror("Not an image", "That file can't be opened as an image.", parent=self)
            return
        self.engine.apply_cover_local(self.exe, path)
        self.destroy()
