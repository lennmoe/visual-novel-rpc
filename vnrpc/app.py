from __future__ import annotations

import queue
import sys
import threading
import time
import webbrowser
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

from .config import Config
from .core import Snapshot, VNRPCEngine
from .engines import is_blacklisted
from .paths import ensure_dirs
from .presence import Activity
from .ui import theme as t
from .ui.cover_dialog import CoverDialog
from .ui.images import app_icon_image, fetch_full_image_async, make_ctk_image, tray_image
from .ui.library_dialog import LibraryDialog
from .ui.settings_dialog import SettingsDialog

COVER_SIZE = (150, 212)
THUMB_SIZE = (76, 76)
_NO_WINDOWS = "(no windows found)"
_PICK_WINDOW = "Pick the game window…"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ensure_dirs()
        self.config_data = Config.load()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title("Visual Novel RPC")
        self.geometry("700x700")
        self.minsize(620, 660)
        self.configure(fg_color=t.BG)
        t.set_icon(self)

        self._events: "queue.Queue[tuple]" = queue.Queue()
        self.engine = VNRPCEngine(
            self.config_data,
            on_snapshot=lambda s: self._events.put(("snap", s)),
            on_status=lambda kind, ok, msg: self._events.put(("status", kind, ok, msg)),
        )

        self._paused = False
        self._last_snapshot = Snapshot()
        self._activity: Activity | None = None
        self._window_map: dict[str, str] = {}
        self._dialogs: dict[str, ctk.CTkToplevel] = {}
        self._cover_key: tuple | None = ("unset",)
        self._cover_pil: Image.Image | None = None
        self._asset_thumb = app_icon_image(THUMB_SIZE[0], radius=8)

        self._build()
        self._render_snapshot(Snapshot())
        self._poll_events()
        self._tick_elapsed()

        self.engine.start()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self._tray = None
        self._tray_failed = False
        threading.Thread(target=self._start_tray, daemon=True).start()
        if self.config_data["start_minimized"]:
            self.after(300, self._hide_to_tray)

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._build_paused_banner()
        self._build_card()
        self._build_detection_bar()
        self._build_footer()
        self._sync_mode_widgets()
        if self.mode.get() == "Manual":
            self._refresh_windows()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 12))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header, text="", image=app_icon_image(40, radius=10)).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(header, text="Visual Novel RPC", font=t.font(20, "bold"), text_color=t.TEXT,
                     anchor="w").grid(row=0, column=1, sticky="sw")
        t.muted(header, "Discord Rich Presence for your visual novels").grid(row=1, column=1, sticky="nw")

        pills = ctk.CTkFrame(header, fg_color="transparent")
        pills.grid(row=0, column=2, rowspan=2, sticky="e")
        self.pill_game = _Pill(pills, "Game")
        self.pill_game.pack(side="left", padx=(0, 8))
        self.pill_discord = _Pill(pills, "Discord")
        self.pill_discord.pack(side="left")

    def _build_paused_banner(self) -> None:
        self.paused_banner = ctk.CTkFrame(self, fg_color=t.YELLOW_SOFT, corner_radius=10)
        inner = ctk.CTkFrame(self.paused_banner, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=8)
        ctk.CTkLabel(inner, text="●", text_color=t.YELLOW, font=t.font(12)).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(inner, text="Presence paused — nothing is being shared on Discord.",
                     text_color=t.TEXT, font=t.font(12)).pack(side="left")
        ctk.CTkButton(inner, text="Resume", width=80, height=26, corner_radius=7, fg_color=t.YELLOW,
                      hover_color="#D69E2B", text_color="#1E1F22", font=t.font(12, "bold"),
                      command=self._toggle_pause).pack(side="right")

    def _build_card(self) -> None:
        card = t.card(self)
        card.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        card.grid_columnconfigure(1, weight=1)
        card.grid_rowconfigure(2, weight=1)

        self.cover_label = ctk.CTkLabel(card, text="")
        self.cover_label.grid(row=0, column=0, padx=(20, 18), pady=(20, 14), sticky="n")

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=1, sticky="new", padx=(0, 20), pady=(22, 14))
        self._info = info

        self.state_label = t.overline(info, "")
        self.state_label.pack(fill="x")
        self.game_label = ctk.CTkLabel(info, text="", anchor="w", justify="left",
                                       font=t.font(22, "bold"), text_color=t.TEXT)
        self.game_label.pack(fill="x", pady=(2, 0))
        self.sub_label = t.muted(info, "")
        self.sub_label.pack(fill="x", pady=(2, 12))

        self.badges = ctk.CTkFrame(info, fg_color="transparent", height=1)
        self.badges.pack(fill="x")
        self.section_badge = t.chip(self.badges, fg_color=t.ACCENT, text_color="white")
        self.playtime_badge = t.chip(self.badges, fg_color=t.SURFACE_ALT, text_color=t.TEXT)

        self.actions = ctk.CTkFrame(info, fg_color="transparent")
        self.actions.pack(fill="x", pady=(14, 0))
        self.cover_btn = t.secondary_button(self.actions, "Change cover…", self._open_cover, width=140)
        self.cover_btn.pack(side="left")
        self.vndb_btn = t.secondary_button(self.actions, "VNDB page ↗", self._open_vndb, width=120)
        self.not_vn_btn = t.danger_button(self.actions, "Not a VN", self._blacklist_current, width=90)

        self.privacy_note = ctk.CTkLabel(info, text="", anchor="w", justify="left",
                                         font=t.font(12), text_color=t.YELLOW)

        info.bind("<Configure>", self._on_info_resize)

        preview = t.panel(card)
        preview.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 20))
        preview.grid_columnconfigure(1, weight=1)
        self._preview = preview

        head = ctk.CTkFrame(preview, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(12, 8))
        t.overline(head, "Discord preview").pack(side="left")
        t.muted(head, "what your friends see", size=11).pack(side="right")

        self.preview_thumb = ctk.CTkLabel(preview, text="")
        self.preview_thumb.grid(row=1, column=0, padx=(16, 14), pady=(0, 14), sticky="nw")

        lines = ctk.CTkFrame(preview, fg_color="transparent")
        lines.grid(row=1, column=1, sticky="nw", padx=(0, 16), pady=(0, 14))
        self.preview_name = ctk.CTkLabel(lines, text="", anchor="w", justify="left",
                                         font=t.font(14, "bold"), text_color=t.TEXT)
        self.preview_name.pack(fill="x")
        self.preview_details = t.muted(lines, "", size=12)
        self.preview_state = t.muted(lines, "", size=12)
        self.preview_elapsed = ctk.CTkLabel(lines, text="", anchor="w", font=t.font(12, "bold"),
                                            text_color=t.GREEN)
        self.preview_button = ctk.CTkLabel(lines, text="View on VNDB", fg_color=t.SURFACE_HOVER,
                                           corner_radius=6, height=24, font=t.font(11, "bold"),
                                           text_color=t.TEXT)

    def _build_detection_bar(self) -> None:
        bar = t.card(self, corner_radius=10)
        bar.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 12))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(inner, text="Detection", font=t.font(13, "bold"), text_color=t.TEXT).pack(side="left")
        self.mode = t.segmented(inner, ["Auto", "Manual"], command=self._on_mode, width=140)
        self.mode.set("Auto" if self.config_data["detection_mode"] == "auto" else "Manual")
        self.mode.pack(side="left", padx=(12, 10))

        self.mode_hint = t.muted(inner, "Finds running VN engines by itself", size=11)
        self.window_menu = ctk.CTkOptionMenu(
            inner, values=[_PICK_WINDOW], command=self._on_pick_window, width=260, height=30,
            corner_radius=8, fg_color=t.SURFACE_ALT, button_color=t.SURFACE_HOVER,
            button_hover_color=t.BORDER, text_color=t.TEXT, dropdown_fg_color=t.SURFACE,
            dropdown_hover_color=t.SURFACE_HOVER, dropdown_text_color=t.TEXT, dynamic_resizing=False,
            font=t.font(12),
        )
        self.window_menu.set(_PICK_WINDOW)
        self.refresh_btn = t.secondary_button(inner, "↻", self._refresh_windows, width=34, height=30)

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 18))
        footer.grid_columnconfigure(3, weight=1)

        self.pause_btn = t.secondary_button(footer, "Pause", self._toggle_pause, width=100)
        self.pause_btn.grid(row=0, column=0)
        t.secondary_button(footer, "Library", self._open_library, width=100).grid(row=0, column=1, padx=8)
        t.secondary_button(footer, "Settings", self._open_settings, width=100).grid(row=0, column=2)
        self.status_line = t.muted(footer, "", size=11, anchor="e", justify="right")
        self.status_line.grid(row=0, column=3, sticky="e", padx=(12, 0))

    def _on_info_resize(self, event) -> None:
        wrap = max(200, event.width - 8)
        self.game_label.configure(wraplength=wrap)
        self.sub_label.configure(wraplength=wrap)
        self.privacy_note.configure(wraplength=wrap)
        lines_wrap = max(200, self._preview.winfo_width() - THUMB_SIZE[0] - 60)
        for lbl in (self.preview_name, self.preview_details, self.preview_state):
            lbl.configure(wraplength=lines_wrap)

    def _poll_events(self) -> None:
        try:
            while True:
                evt = self._events.get_nowait()
                if evt[0] == "snap":
                    self._render_snapshot(evt[1])
                elif evt[0] == "status":
                    self._render_status(evt[1], evt[2], evt[3])
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def _render_snapshot(self, snap: Snapshot) -> None:
        self._last_snapshot = snap
        self._activity = self.engine.activity_for(snap)
        self.section_badge.pack_forget()
        self.playtime_badge.pack_forget()
        self.vndb_btn.pack_forget()
        self.not_vn_btn.pack_forget()
        self.privacy_note.pack_forget()

        if not snap.detected:
            self.state_label.configure(text="WAITING", text_color=t.SUBTLE)
            self.game_label.configure(text="No visual novel detected")
            hint = ("Start a visual novel and it'll show up here on its own."
                    if self.mode.get() == "Auto" else
                    "Pick the game's window in the Detection bar below.")
            self.sub_label.configure(text=hint)
            self.actions.pack_forget()
            self.pill_game.set_state("idle", "Game")
            self._show_cover(None, blur=False)
            self._render_preview()
            return

        self.state_label.configure(text="NOW READING", text_color=t.ACCENT)
        self.game_label.configure(text=snap.game_name or snap.raw_title)
        bits = [b for b in (snap.engine_name, snap.exe) if b]
        if snap.steam_name:
            bits.append("Steam")
        self.sub_label.configure(text="  ·  ".join(bits) or snap.raw_title)

        if snap.section_label:
            self.section_badge.configure(text=f"  {t.ellipsize(snap.section_label, 48)}  ")
            self.section_badge.pack(side="left", padx=(0, 6))
        if snap.playtime_seconds > 0:
            self.playtime_badge.configure(text=f"  {snap.playtime_text} read  ")
            self.playtime_badge.pack(side="left")

        if not self.actions.winfo_manager():
            self.actions.pack(fill="x", pady=(14, 0))
        if snap.vn:
            self.vndb_btn.pack(side="left", padx=(8, 0))
        self.not_vn_btn.pack(side="left", padx=(8, 0))

        note = {
            "partial": "Privacy: Partial — the current section isn't shared.",
            "private": "Privacy: Private — Discord only shows “Visual Novel”.",
            "off": "Privacy: Off — nothing is shared for this game.",
        }.get(snap.privacy, "")
        if note:
            self.privacy_note.configure(text=note)
            self.privacy_note.pack(fill="x", pady=(10, 0))

        self.pill_game.set_state("ok", "Game")
        blur = snap.cover.nsfw and not self.config_data["allow_nsfw_covers"]
        self._show_cover(snap.cover, blur=blur)
        self._render_preview()

    def _render_preview(self) -> None:
        act = self._activity
        for lbl in (self.preview_details, self.preview_state, self.preview_elapsed, self.preview_button):
            lbl.pack_forget()
        if act is None or self._paused:
            snap = self._last_snapshot
            if self._paused:
                why = "Presence is paused."
            elif snap.detected:
                why = "Presence is turned off for this game."
            else:
                why = "Your status clears while no visual novel is open."
            self.preview_name.configure(text="Nothing shared", text_color=t.MUTED)
            self.preview_details.configure(text=why)
            self.preview_details.pack(fill="x")
            self._refresh_preview_thumb()
            return
        self.preview_name.configure(text=act.name or "Visual Novel", text_color=t.TEXT)
        if act.details:
            self.preview_details.configure(text=act.details)
            self.preview_details.pack(fill="x")
        if act.state:
            self.preview_state.configure(text=act.state)
            self.preview_state.pack(fill="x")
        if act.start:
            self.preview_elapsed.pack(fill="x", pady=(2, 0))
            self._update_elapsed()
        if act.buttons:
            self.preview_button.configure(text=f"  {act.buttons[0]['label']}  ")
            self.preview_button.pack(anchor="w", pady=(8, 0))
        self._refresh_preview_thumb()

    def _tick_elapsed(self) -> None:
        self._update_elapsed()
        self.after(1000, self._tick_elapsed)

    def _update_elapsed(self) -> None:
        act = self._activity
        if act is None or not act.start:
            return
        secs = max(0, int(time.time()) - int(act.start))
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        self.preview_elapsed.configure(text=f"{stamp} elapsed")

    def _show_cover(self, cover, *, blur: bool) -> None:
        key = (cover.local_path, cover.display_url, blur) if cover is not None else None
        if key == self._cover_key:
            return
        self._cover_key = key
        self._cover_pil = None
        self._apply_cover(blur)
        if cover is None:
            return
        if cover.local_path:
            try:
                with Image.open(cover.local_path) as im:
                    self._cover_pil = im.convert("RGB")
            except Exception:
                self._cover_pil = None
            if self._cover_pil is not None or not cover.display_url:
                self._apply_cover(blur)
                return
        if cover.display_url:
            def done(pil: "Image.Image | None") -> None:
                if self._cover_key != key:
                    return
                self._cover_pil = pil
                self._apply_cover(blur)
            fetch_full_image_async(cover.display_url, done, widget=self)

    def _apply_cover(self, blur: bool) -> None:
        self.cover_label.configure(image=make_ctk_image(self._cover_pil, COVER_SIZE, blur=blur, radius=10))
        self._refresh_preview_thumb()

    def _refresh_preview_thumb(self) -> None:
        act = self._activity
        if act is None or self._paused:
            img = make_ctk_image(None, THUMB_SIZE, radius=8)
        elif act.large_image.startswith(("http://", "https://")) and self._cover_pil is not None:
            img = make_ctk_image(self._cover_pil, THUMB_SIZE, radius=8)
        else:
            img = self._asset_thumb
        self.preview_thumb.configure(image=img)

    def _render_status(self, kind: str, ok: bool, msg: str) -> None:
        if kind == "discord":
            self.pill_discord.set_state("ok" if ok else "bad", "Discord")
        elif kind == "game":
            return
        self.status_line.configure(text=t.ellipsize(msg, 70), text_color=t.MUTED if ok else t.SUBTLE)

    def _on_mode(self, value: str) -> None:
        self.config_data["detection_mode"] = "auto" if value == "Auto" else "manual"
        self.config_data.save()
        self.engine.reload_config()
        self._sync_mode_widgets()
        if value == "Manual":
            self._refresh_windows()
        if not self._last_snapshot.detected:
            self._render_snapshot(self._last_snapshot)

    def _sync_mode_widgets(self) -> None:
        if self.mode.get() == "Manual":
            self.mode_hint.pack_forget()
            self.window_menu.pack(side="left", fill="x", expand=True, padx=(0, 6))
            self.refresh_btn.pack(side="left")
        else:
            self.window_menu.pack_forget()
            self.refresh_btn.pack_forget()
            self.mode_hint.pack(side="left")

    def _refresh_windows(self) -> None:
        wins = self.engine.list_windows()
        self._window_map.clear()
        blacklist = self.engine.blacklist
        for w in wins:
            if is_blacklisted(w.exe, blacklist):
                continue
            label = f"{t.ellipsize(w.title, 40)}  —  {w.exe}"
            self._window_map[label] = w.exe
        self.window_menu.configure(values=list(self._window_map) or [_NO_WINDOWS])
        current = self.config_data["manual_target"].get("exe", "")
        for label, exe in self._window_map.items():
            if exe.lower() == current.lower():
                self.window_menu.set(label)
                return
        self.window_menu.set(f"{current}  (not running)" if current else _PICK_WINDOW)

    def _on_pick_window(self, label: str) -> None:
        exe = self._window_map.get(label, "")
        if not exe:
            return
        self.config_data["manual_target"] = {"exe": exe, "title_contains": ""}
        self.config_data["detection_mode"] = "manual"
        self.config_data.save()
        self.engine.reload_config()

    def _blacklist_current(self) -> None:
        exe = self._last_snapshot.exe
        if not exe or not messagebox.askyesno(
            "Not a VN", f'Never detect "{exe}" again?\n\n'
            "It's added to the blacklist (Settings → Blacklist) and hidden from the Library.",
            parent=self,
        ):
            return
        self.engine.add_to_blacklist(exe)

    def _open_vndb(self) -> None:
        vn = self._last_snapshot.vn
        if vn:
            webbrowser.open(vn.vndb_url)

    def _open_dialog(self, name: str, factory) -> None:
        """One instance per dialog: re-focus it instead of stacking copies."""
        dlg = self._dialogs.get(name)
        try:
            if dlg is not None and dlg.winfo_exists():
                dlg.deiconify()
                dlg.lift()
                dlg.focus_force()
                return
        except Exception:
            pass
        self._dialogs[name] = factory()

    def _open_cover(self) -> None:
        snap = self._last_snapshot
        if not snap.detected:
            return
        self._open_dialog("cover", lambda: CoverDialog(self, self.engine, snap.exe, snap.game_name))

    def _open_settings(self) -> None:
        self._open_dialog("settings", lambda: SettingsDialog(self, self.engine))

    def _open_library(self) -> None:
        self._open_dialog("library", lambda: LibraryDialog(self, self.engine))

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.engine.set_paused(self._paused)
        if self._paused:
            self.pause_btn.configure(text="Resume", fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER,
                                     text_color="white", border_width=0)
            self.paused_banner.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
        else:
            self.pause_btn.configure(text="Pause", fg_color=t.SURFACE_ALT, hover_color=t.SURFACE_HOVER,
                                     text_color=t.TEXT, border_width=1)
            self.paused_banner.grid_forget()
        self._render_preview()
        if self._tray is not None:
            try:
                self._tray.update_menu()
            except Exception:
                pass

    def _start_tray(self) -> None:
        try:
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem("Show", self._show_from_tray, default=True),
                pystray.MenuItem(
                    lambda _i: "Resume presence" if self._paused else "Pause presence",
                    lambda _i, _it: self.after(0, self._toggle_pause),
                ),
                pystray.MenuItem("Quit", lambda _i, _it: self.after(0, self._quit)),
            )
            self._tray = pystray.Icon("vnrpc", tray_image(64), "Visual Novel RPC", menu)
            self._tray.run()
        except Exception:
            self._tray = None
            self._tray_failed = True

    def _hide_to_tray(self) -> None:
        if self._tray_failed:
            self.iconify()
        else:
            self.withdraw()

    def _show_from_tray(self, *_a) -> None:
        self.after(0, lambda: (self.deiconify(), self.lift(), self.focus_force()))

    def _quit(self) -> None:
        try:
            if self._tray:
                self._tray.stop()
        except Exception:
            pass
        self.engine.stop()
        self.destroy()
        sys.exit(0)


class _Pill(ctk.CTkFrame):
    """Rounded status chip: a colored dot + a label."""
    _COLORS = {"ok": t.GREEN, "bad": t.RED, "idle": t.SUBTLE}

    def __init__(self, parent, text: str) -> None:
        super().__init__(parent, fg_color=t.SURFACE, border_width=1, border_color=t.BORDER,
                         corner_radius=14, height=28)
        self._dot = ctk.CTkLabel(self, text="●", font=t.font(11), text_color=t.SUBTLE, width=10)
        self._dot.pack(side="left", padx=(12, 6), pady=3)
        self._text = ctk.CTkLabel(self, text=text, font=t.font(12, "bold"), text_color=t.MUTED)
        self._text.pack(side="left", padx=(0, 12), pady=3)

    def set_state(self, state: str, text: str) -> None:
        self._dot.configure(text_color=self._COLORS.get(state, t.SUBTLE))
        self._text.configure(text=text, text_color=t.TEXT if state == "ok" else t.MUTED)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
