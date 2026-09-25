from __future__ import annotations

import os
from tkinter import messagebox

import customtkinter as ctk

from ..core import VNRPCEngine, format_playtime
from ..covers import cached_cover_for_entry
from . import theme as t
from .images import load_image

THUMB = (60, 84)


class LibraryDialog(ctk.CTkToplevel):
    def __init__(self, master, engine: VNRPCEngine) -> None:
        super().__init__(master)
        self.engine = engine
        t.setup_window(self, title="Library", geometry="660x600", minsize=(540, 420), modal_for=master)
        self.bind("<Escape>", lambda _e: self.destroy())

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(18, 10))
        ctk.CTkLabel(head, text="Library", font=t.font(20, "bold"), text_color=t.TEXT).pack(side="left")
        self.search = t.entry(head, placeholder_text="Filter…", width=200)
        self.search.pack(side="right")
        self.search.bind("<KeyRelease>", lambda _e: self._reload())
        self.summary = t.muted(self, "")
        self.summary.pack(fill="x", padx=20, pady=(0, 8))

        self.list_box = t.scrollable(self)
        self.list_box.pack(fill="both", expand=True, padx=12, pady=(0, 14))

        self._reload()

    def _reload(self) -> None:
        for w in self.list_box.winfo_children():
            w.destroy()

        games = self.engine.config.all_games()
        total = sum(int(e.get("playtime_seconds", 0)) for e in games.values())
        count = len(games)
        self.summary.configure(
            text=f"{count} game{'s' if count != 1 else ''}  ·  {format_playtime(total)} read in total"
            if count else ""
        )

        needle = self.search.get().strip().lower()
        entries = [
            (key, entry) for key, entry in games.items()
            if not needle or needle in (entry.get("title") or key).lower() or needle in key
        ]
        entries.sort(key=lambda kv: int(kv[1].get("playtime_seconds", 0)), reverse=True)

        if not entries:
            msg = ("No match." if needle else
                   "Nothing here yet — start a visual novel with Visual Novel RPC running.")
            t.muted(self.list_box, msg, anchor="center", justify="center").pack(pady=40)
            return

        top = max(1, max(int(e.get("playtime_seconds", 0)) for _, e in entries))
        for key, entry in entries:
            self._row(key, entry, top)

    def _row(self, key: str, entry: dict, top: int) -> None:
        row = t.card(self.list_box, corner_radius=10)
        row.pack(fill="x", pady=5, padx=6)
        row.grid_columnconfigure(1, weight=1)

        thumb = ctk.CTkLabel(row, text="", image=load_image(cached_cover_for_entry(entry), THUMB, radius=6))
        thumb.grid(row=0, column=0, rowspan=3, padx=12, pady=12)

        name = entry.get("title") or key
        seconds = int(entry.get("playtime_seconds", 0))
        ctk.CTkLabel(row, text=t.ellipsize(name, 60), anchor="w", font=t.font(14, "bold"),
                     text_color=t.TEXT).grid(row=0, column=1, sticky="sw", pady=(14, 0))
        sub = f"{format_playtime(seconds)} read"
        if entry.get("vndb_id"):
            sub += f"   ·   {entry['vndb_id']}"
        t.muted(row, sub).grid(row=1, column=1, sticky="w")

        bar = ctk.CTkProgressBar(row, height=4, corner_radius=2, progress_color=t.ACCENT,
                                 fg_color=t.SURFACE_ALT)
        bar.set(seconds / top)
        bar.grid(row=2, column=1, sticky="new", pady=(6, 14))

        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.grid(row=0, column=2, rowspan=3, padx=12)
        exe_path = entry.get("path", "")
        play = t.primary_button(btns, "▶  Play", lambda p=exe_path: self._launch(p), width=86)
        play.pack(side="left")
        if not exe_path:
            play.configure(state="disabled", fg_color=t.SURFACE_ALT, text_color_disabled=t.SUBTLE)
        t.danger_button(btns, "Remove", lambda k=key, n=name: self._remove(k, n), width=80).pack(
            side="left", padx=(8, 0)
        )

    def _launch(self, exe_path: str) -> None:
        if not exe_path or not os.path.isfile(exe_path):
            messagebox.showerror(
                "Play", "This game's executable can't be found anymore\n"
                "(it may have moved or been uninstalled).", parent=self,
            )
            return
        try:
            # many engines load their data relative to the working directory,
            # so start the game from its own folder
            os.startfile(exe_path, cwd=os.path.dirname(exe_path))
        except OSError as exc:
            messagebox.showerror("Play", f"Couldn't launch it: {exc}", parent=self)

    def _remove(self, key: str, name: str) -> None:
        if not messagebox.askyesno(
            "Remove", f'Remove "{name}" from the library?\n\n'
            "Its saved playtime, cover and privacy settings are forgotten.\n"
            "Nothing is uninstalled.",
            parent=self,
        ):
            return
        self.engine.clear_override(key)
        self._reload()
