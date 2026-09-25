# PyInstaller spec — build with:  python -m PyInstaller vnrpc.spec  (or: python build.py)
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
datas += collect_data_files("customtkinter")          # theme .json + assets
datas += [("assets/vnrpc.ico", "assets"), ("assets/app_icon.png", "assets")]

hiddenimports = []
hiddenimports += collect_submodules("pypresence")
hiddenimports += ["pystray._win32", "PIL._tkinter_finder"]

a = Analysis(
    ["run.pyw"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["numpy", "pytest", "tkinter.test", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VisualNovelRPC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,               # GUI app: no console window
    disable_windowed_traceback=False,
    icon="assets/vnrpc.ico",
    version=None,
)
