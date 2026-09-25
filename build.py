from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def main() -> int:
    keep = "--keep" in sys.argv

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is missing.  Run:  pip install -r requirements-dev.txt")
        return 1

    print(">> regenerating assets/vnrpc.ico")
    subprocess.run([sys.executable, "tools/make_icon.py"], cwd=ROOT, check=True)

    if not keep:
        for name in ("build", "dist"):
            shutil.rmtree(ROOT / name, ignore_errors=True)

    print(">> running PyInstaller")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "vnrpc.spec"],
        cwd=ROOT,
        check=True,
    )

    exe = ROOT / "dist" / "VisualNovelRPC.exe"
    if exe.exists():
        print(f"\nOK  ->  {exe}  ({exe.stat().st_size / 1_048_576:.1f} MB)")
        return 0
    print("\nBuild finished but dist/VisualNovelRPC.exe is missing.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
