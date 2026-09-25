from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from vnrpc.ui.images import tray_image  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "vnrpc.ico")
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    base = tray_image(256)
    base.save(OUT, sizes=[(s, s) for s in SIZES])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
