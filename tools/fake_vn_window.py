from __future__ import annotations

import argparse
import tkinter as tk

CYCLE = [
    "{game} - Prologue",
    "{game} - Common Route",
    "{game} - Chapter 2",
    "{game} - Yuzu Route - Chapter 4",
    "{game} - Good Ending",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="Sugar*Style - prologue01", help="initial window title")
    ap.add_argument("--game", default="Sugar*Style", help="game name used by the cycle buttons")
    ap.add_argument("--cycle", action="store_true", help="auto-advance the title every 8 s")
    args = ap.parse_args()

    root = tk.Tk()
    root.title(args.title)
    root.geometry("460x180")

    state = {"i": 0}
    label = tk.Label(root, text=args.title, wraplength=440, font=("Segoe UI", 11))
    label.pack(pady=16, padx=12)

    def set_title(text: str) -> None:
        root.title(text)
        label.config(text=text)

    def advance() -> None:
        state["i"] = (state["i"] + 1) % len(CYCLE)
        set_title(CYCLE[state["i"]].format(game=args.game))

    def custom() -> None:
        set_title(entry.get())

    row = tk.Frame(root)
    row.pack()
    tk.Button(row, text="Next section", command=advance).pack(side="left", padx=4)
    entry = tk.Entry(row, width=32)
    entry.insert(0, args.title)
    entry.pack(side="left", padx=4)
    tk.Button(row, text="Set", command=custom).pack(side="left", padx=4)

    if args.cycle:
        def tick() -> None:
            advance()
            root.after(8000, tick)
        root.after(8000, tick)

    root.mainloop()


if __name__ == "__main__":
    main()
