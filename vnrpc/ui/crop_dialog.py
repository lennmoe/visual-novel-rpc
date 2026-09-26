from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageEnhance, ImageTk

from . import theme as t

CANVAS_MAX = (460, 460)
HANDLE = 5
MIN_SIZE = 12
_CANVAS_BG = "#0B0C0E"


class CropDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        image: Image.Image,
        *,
        aspect: float,
        on_done: Callable[["Image.Image | None"], None],
    ) -> None:
        super().__init__(master)
        t.setup_window(self, title="Crop cover", resizable=False, modal_for=master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._apply())

        self._src = image.convert("RGB")
        self._on_done = on_done
        self._aspect = aspect
        self._sel: tuple[float, float, float, float] | None = None
        self._prev_sel: tuple[float, float, float, float] | None = None
        self._drag_start: tuple[int, int] | None = None
        self._moving = False
        self._finished = False

        self._scale, disp_w, disp_h = self._fit_scale(self._src.size, CANVAS_MAX)
        self._disp_size = (disp_w, disp_h)
        self._disp_img = self._src.resize((disp_w, disp_h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(ImageEnhance.Brightness(self._disp_img).enhance(0.35))
        self._sel_photo: ImageTk.PhotoImage | None = None

        frame = t.card(self)
        frame.pack(padx=16, pady=(16, 10))
        self.canvas = tk.Canvas(frame, width=disp_w, height=disp_h, highlightthickness=0,
                                cursor="crosshair", bg=_CANVAS_BG, bd=0)
        self.canvas.pack(padx=10, pady=10)
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_hover)

        t.muted(self, "Drag to select · drag inside the selection to move it", size=11,
                anchor="center", justify="center").pack(fill="x", padx=16)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(8, 16))
        self.lock_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(bar, text="Lock cover ratio", variable=self.lock_var, font=t.font(12),
                        text_color=t.TEXT, fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER,
                        border_color=t.BORDER, checkbox_width=20, checkbox_height=20,
                        corner_radius=5).pack(side="left")
        t.primary_button(bar, "Apply crop", self._apply, width=110).pack(side="right")
        t.secondary_button(bar, "Cancel", self._cancel, width=80).pack(side="right", padx=6)
        t.secondary_button(bar, "Reset", self._select_all, width=70).pack(side="right")

        self._select_all()

    @staticmethod
    def _fit_scale(size: tuple[int, int], box: tuple[int, int]) -> tuple[float, int, int]:
        w, h = size
        bw, bh = box
        scale = min(bw / w, bh / h, 1.0)
        return scale, max(1, round(w * scale)), max(1, round(h * scale))

    def _select_all(self) -> None:
        w, h = self._disp_size
        if w / h > self._aspect:
            nh, nw = h, h * self._aspect
        else:
            nw, nh = w, w / self._aspect
        x0, y0 = (w - nw) / 2, (h - nh) / 2
        self._sel = (x0, y0, x0 + nw, y0 + nh)
        self._draw_sel()

    def _inside_sel(self, x: float, y: float) -> bool:
        if not self._sel:
            return False
        x0, y0, x1, y1 = self._sel
        return x0 <= x <= x1 and y0 <= y <= y1

    def _on_hover(self, event) -> None:
        self.canvas.configure(cursor="fleur" if self._inside_sel(event.x, event.y) else "crosshair")

    def _on_press(self, event) -> None:
        self._prev_sel = self._sel
        self._drag_start = (event.x, event.y)
        self._moving = self._inside_sel(event.x, event.y)

    def _on_drag(self, event) -> None:
        if not self._drag_start:
            return
        w, h = self._disp_size
        x0, y0 = self._drag_start
        if self._moving and self._prev_sel:
            px0, py0, px1, py1 = self._prev_sel
            dx = max(-px0, min(w - px1, event.x - x0))
            dy = max(-py0, min(h - py1, event.y - y0))
            self._sel = (px0 + dx, py0 + dy, px1 + dx, py1 + dy)
            self._draw_sel()
            return
        ex = max(0, min(w, event.x))
        ey = max(0, min(h, event.y))
        if self.lock_var.get():
            dx, dy = ex - x0, ey - y0
            if abs(dx) / self._aspect >= abs(dy):
                width = abs(dx)
                height = width / self._aspect
            else:
                height = abs(dy)
                width = height * self._aspect
            sx = 1 if dx >= 0 else -1
            sy = 1 if dy >= 0 else -1
            max_w = x0 if sx < 0 else w - x0
            max_h = y0 if sy < 0 else h - y0
            k = min(1.0, max_w / width if width else 1.0, max_h / height if height else 1.0)
            width, height = width * k, height * k
            ex, ey = x0 + sx * width, y0 + sy * height
        self._sel = (min(x0, ex), min(y0, ey), max(x0, ex), max(y0, ey))
        self._draw_sel()

    def _on_release(self, _event) -> None:
        self._drag_start = None
        self._moving = False
        if self._sel and (self._sel[2] - self._sel[0] < MIN_SIZE or self._sel[3] - self._sel[1] < MIN_SIZE):
            self._sel = self._prev_sel
            self._draw_sel()

    def _draw_sel(self) -> None:
        self.canvas.delete("sel")
        if not self._sel:
            return
        x0, y0, x1, y1 = self._sel
        box = (round(x0), round(y0), round(x1), round(y1))
        if box[2] > box[0] and box[3] > box[1]:
            self._sel_photo = ImageTk.PhotoImage(self._disp_img.crop(box))
            self.canvas.create_image(box[0], box[1], anchor="nw", image=self._sel_photo, tags="sel")
        self.canvas.create_rectangle(x0, y0, x1, y1, outline="white", width=2, tags="sel")
        for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            self.canvas.create_rectangle(
                cx - HANDLE, cy - HANDLE, cx + HANDLE, cy + HANDLE, fill=t.ACCENT, outline="white", tags="sel"
            )

    def _apply(self) -> None:
        if not self._sel:
            return
        x0, y0, x1, y1 = self._sel
        sw, sh = self._src.size
        box = (
            max(0, round(x0 / self._scale)), max(0, round(y0 / self._scale)),
            min(sw, round(x1 / self._scale)), min(sh, round(y1 / self._scale)),
        )
        self._finish(self._src.crop(box))

    def _cancel(self) -> None:
        self._finish(None)

    def _finish(self, result: "Image.Image | None") -> None:
        if self._finished:
            return
        self._finished = True
        on_done = self._on_done
        self.destroy()
        on_done(result)
