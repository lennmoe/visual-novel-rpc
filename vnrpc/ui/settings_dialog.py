from __future__ import annotations

import json
import re
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from .. import autostart
from ..config import DEFAULTS
from ..core import VNRPCEngine
from . import theme as t


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, engine: VNRPCEngine) -> None:
        super().__init__(master)
        self.engine = engine
        self.cfg = engine.config
        t.setup_window(self, title="Settings", geometry="600x640", minsize=(520, 480), modal_for=master)

        tabs = ctk.CTkTabview(
            self, fg_color=t.SURFACE, border_width=1, border_color=t.BORDER, corner_radius=t.RADIUS,
            segmented_button_fg_color=t.SURFACE_ALT, segmented_button_selected_color=t.ACCENT,
            segmented_button_selected_hover_color=t.ACCENT_HOVER,
            segmented_button_unselected_color=t.SURFACE_ALT,
            segmented_button_unselected_hover_color=t.SURFACE_HOVER, text_color=t.TEXT,
        )
        tabs.pack(fill="both", expand=True, padx=16, pady=(12, 12))
        self._build_general(tabs.add("General"))
        self._build_rules(tabs.add("Title rules"))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 16))
        t.primary_button(bar, "Save", self._save, width=110).pack(side="right")
        t.secondary_button(bar, "Cancel", self.destroy, width=100).pack(side="right", padx=8)
        self.bind("<Escape>", lambda _e: self.destroy())

    # ---- General ---------------------------------------------
    def _build_general(self, tab) -> None:
        frame = t.scrollable(tab)
        frame.pack(fill="both", expand=True)

        # Discord
        _section(frame, "Discord")
        t.muted(frame, "Application ID", size=12).pack(fill="x", padx=16)
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4, 0))
        self.client_id = t.entry(row)
        self.client_id.insert(0, str(self.cfg["discord_client_id"]))
        self.client_id.pack(side="left", fill="x", expand=True, padx=(0, 8))
        t.secondary_button(row, "Test", self._test_connection, width=70).pack(side="left")
        self.test_lbl = t.muted(frame, "", size=11)  # packed once a test has run
        self._hint_anchor = t.muted(
            frame,
            "Create one at discord.com/developers → New Application, then paste its "
            "Application ID. No bot or OAuth needed.",
            size=11, wraplength=480,
        )
        self._hint_anchor.pack(fill="x", padx=16, pady=(6, 4))

        # Presence
        _section(frame, "Presence")
        self.show_elapsed = t.switch(frame, "Show elapsed time", self.cfg["show_elapsed"])
        self.clear_on_close = t.switch(frame, "Clear presence when the VN closes", self.cfg["clear_on_close"])
        self.show_vndb_button = t.switch(frame, 'Add a "View on VNDB" button', self.cfg["show_vndb_button"])

        # Covers & matching
        _section(frame, "Covers & matching")
        self.allow_nsfw = t.switch(
            frame, "Allow NSFW-flagged covers", self.cfg["allow_nsfw_covers"],
            hint="Off: flagged covers are blurred here and replaced by the fallback image on Discord.",
        )
        self.use_steam_names = t.switch(
            frame, "Use Steam library names", self.cfg["use_steam_names"],
            hint="Gives much better VNDB matches for games installed through Steam.",
        )

        # App
        _section(frame, "App")
        self.start_minimized = t.switch(frame, "Start minimized to the tray", self.cfg["start_minimized"])
        self.launch_at_startup = t.switch(
            frame, "Launch when Windows starts", autostart.is_enabled(),
            hint="" if autostart.supported() else "Only available in the packaged .exe build.",
        )
        if not autostart.supported():
            self.launch_at_startup.configure(state="disabled")

        # Advanced
        _section(frame, "Advanced")
        self.min_interval = _field(frame, "Min. seconds between presence updates",
                                   str(self.cfg["update_min_interval"]), width=70)
        self.asset_key = _field(frame, "Fallback Discord asset key", str(self.cfg["default_asset_key"]),
                                width=150)
        ctk.CTkFrame(frame, fg_color="transparent", height=8).pack()

    def _test_connection(self) -> None:
        if not self.test_lbl.winfo_manager():
            self.test_lbl.pack(fill="x", padx=16, pady=(4, 0), before=self._hint_anchor)
        cid = self.client_id.get().strip()
        if not cid.isdigit():
            self.test_lbl.configure(text="An Application ID is a long number.", text_color=t.RED)
            return
        self.test_lbl.configure(text="Testing…", text_color=t.MUTED)

        def worker() -> None:
            ok, msg = True, "Connected — this ID works."
            try:
                from pypresence import Presence

                rpc = Presence(cid)
                rpc.connect()
                rpc.close()
            except Exception as exc:
                ok, msg = False, f"Failed: {type(exc).__name__} (is Discord running?)"

            def show() -> None:
                if self.winfo_exists():
                    self.test_lbl.configure(text=msg, text_color=t.GREEN if ok else t.RED)
            try:
                self.after(0, show)
            except Exception:  # dialog closed meanwhile
                pass

        threading.Thread(target=worker, daemon=True).start()

    # ---- Title rules ---------------------------------------
    def _build_rules(self, frame) -> None:
        t.muted(
            frame,
            "Extra rules run before the built-in ones. One JSON object per line; "
            "the first rule whose pattern matches the window title wins.",
            size=12, wraplength=500,
        ).pack(fill="x", padx=12, pady=(10, 4))
        example = ctk.CTkLabel(
            frame, text='{"name": "part", "pattern": "part\\\\s*(?P<n>\\\\d+)", "label": "Part {n}", '
                        '"section_type": "chapter"}',
            font=t.mono(11), text_color=t.MUTED, fg_color=t.SURFACE_ALT, corner_radius=6,
            anchor="w", justify="left", wraplength=500,
        )
        example.pack(fill="x", padx=12, pady=(0, 8), ipadx=8, ipady=6)
        self.rules_text = ctk.CTkTextbox(
            frame, font=t.mono(12), fg_color=t.SURFACE_ALT, border_color=t.BORDER, border_width=1,
            corner_radius=8, text_color=t.TEXT, wrap="none",
        )
        self.rules_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        existing = self.cfg.get("title_rules") or []
        self.rules_text.insert("1.0", "\n".join(json.dumps(r, ensure_ascii=False) for r in existing))

    def _parse_rules(self) -> list[dict]:
        """Raise ValueError with a line number on anything the engine would reject."""
        out = []
        for n, line in enumerate(self.rules_text.get("1.0", tk.END).splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rule = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Line {n}: invalid JSON ({exc.msg}).") from None
            if not isinstance(rule, dict) or not isinstance(rule.get("pattern"), str):
                raise ValueError(f'Line {n}: each rule must be an object with a "pattern" string.')
            try:
                re.compile(rule["pattern"])
            except re.error as exc:
                raise ValueError(f"Line {n}: invalid regex ({exc}).") from None
            out.append(rule)
        return out

    # ---- save --------------------------------------------
    def _save(self) -> None:
        try:
            rules = self._parse_rules()
        except ValueError as exc:
            messagebox.showerror("Title rules", str(exc), parent=self)
            return
        try:
            interval = max(1, int(float(self.min_interval.get())))
        except ValueError:
            interval = DEFAULTS["update_min_interval"]

        self.cfg["discord_client_id"] = self.client_id.get().strip() or self.cfg["discord_client_id"]
        self.cfg["show_elapsed"] = bool(self.show_elapsed.get())
        self.cfg["clear_on_close"] = bool(self.clear_on_close.get())
        self.cfg["show_vndb_button"] = bool(self.show_vndb_button.get())
        self.cfg["allow_nsfw_covers"] = bool(self.allow_nsfw.get())
        self.cfg["use_steam_names"] = bool(self.use_steam_names.get())
        self.cfg["start_minimized"] = bool(self.start_minimized.get())
        self.cfg["update_min_interval"] = interval
        self.cfg["default_asset_key"] = self.asset_key.get().strip() or DEFAULTS["default_asset_key"]
        self.cfg["title_rules"] = rules
        if autostart.supported():
            try:
                autostart.set_enabled(bool(self.launch_at_startup.get()))
            except OSError as exc:
                messagebox.showwarning("Startup", f"Couldn't change the startup setting: {exc}", parent=self)
        self.cfg.save()
        self.engine.reload_config()
        self.destroy()


def _section(parent, title: str) -> None:
    t.overline(parent, title, color=t.ACCENT).pack(fill="x", padx=16, pady=(16, 6))


def _field(parent, label: str, value: str, *, width: int) -> ctk.CTkEntry:
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", padx=16, pady=4)
    ctk.CTkLabel(row, text=label, font=t.font(13), text_color=t.TEXT).pack(side="left")
    ent = t.entry(row, width=width)
    ent.insert(0, value)
    ent.pack(side="right")
    return ent
