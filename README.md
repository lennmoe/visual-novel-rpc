# Visual Novel RPC

A small Windows tray app that watches the **active window title** of a running
visual novel and publishes it as **Discord Rich Presence**:

```
Aoi Tori
Reading — The First Three Days [2/3]
Total read: 12h 40m
```

Name on top, current section (`Prologue`, `Common Route`, `Chapter 4`, `Yuzu
Route`, `Kokoro — Chapter 1`, `Good Ending`, …) underneath, total time spent in
that VN (tracked automatically, persists across sessions), and a cover image.

## Features

- **Auto-detect** the VN window (scores known engines: Ren'Py, KiriKiri,
  TyranoScript, SiglusEngine, RealLive, Artemis, YU-RIS, NScripter, Unity), or
  pick one manually — the manual picker filters out Discord, Spotify, browsers,
  Steam, editors and other obvious noise so you're only choosing between
  plausible VN windows.
- **Section parsing** from the title, EN/FR/JP: prologue・epilogue・opening,
  `chapter/act/episode/part N`, `第N章`, `Day N` / `N日目`, `X Route` /
  `Xルート` / `X編`, `Name, Chapter N`, common / true route, `good/bad/true
  ending`, `~subtitle~`. Known title noise (resolution, version tags, age
  ratings like `R18`, and a couple of Shift-JIS mojibake artifacts old
  engines produce) is stripped first. Add your own regex rules in Settings.
- **Time read**, tracked automatically per VN and shown live in the presence
  and in the app (updates roughly once a minute while a VN is focused, pauses
  when you pause the app).
- **Cover** per game, from any of:
  - **VNDB search** — type the title, pick the best match (VNDB's own
    relevance ranking, name-similarity, and VNDB rating as a tie-breaker all
    feed into the auto-pick when you don't choose manually), or browse every
    release's box art via **Covers…**.
  - **Image URL** — any public jpg/png/webp; this is what Discord shows.
  - **Local file** — shown in the app; Discord can't display local files, so
    the presence falls back to the default asset key (see below).
  - **Crop…** is available on all three sources (VNDB results, release
    covers, URL, local file) — drag out the exact area of the picture you
    want used as the cover, ratio locked to the Discord cover shape by
    default (toggle off for a free crop). A cropped image is always stored
    locally, so — same as a plain local-file cover — it shows in the app but
    falls back to the default asset key on Discord.
- **Steam-aware naming** — if a detected game is an installed Steam app, its
  library name (read from Steam's own local files, no network/API calls) is
  used as the game name and VNDB search query whenever the window title alone
  isn't enough. Toggle under Settings → *Use Steam library names*.
- **Library** — every VN the app has ever tracked, with total time read and a
  one-click **Play** to relaunch it (remembers the exe path automatically the
  next time that VN is detected running).
- **Per-game privacy** — the cover dialog's top bar sets how much of a game is
  shared on Discord: **Full** (name + section + cover), **Partial** (name +
  cover, no chapter/route), **Private** (generic "Visual Novel" only), or
  **Off** (no presence at all for that game).
- NSFW-flagged VNDB covers are blurred in the app and never sent to Discord
  unless you opt in under Settings.
- **Launch at Windows startup** — optional toggle in Settings (packaged .exe
  only; writes a per-user registry entry, no admin rights needed).

## Run from source

```
pip install -r requirements.txt
python -m vnrpc
```

Python 3.10+ (developed on 3.14). Windows only (uses Win32 via `ctypes`).

## Build the .exe

```
pip install -r requirements-dev.txt
python build.py
```

Output: `dist\VisualNovelRPC.exe` — a single self-contained file, no Python needed
on the target machine. `build.py` regenerates the icon and runs `vnrpc.spec`.
Close any running instance first — PyInstaller can't overwrite a locked exe.

## First-time Discord setup

The app ships with a working Application ID, but the cover-fallback image and any
engine icons live on *your* Discord application:

1. <https://discord.com/developers/applications> → **New Application**.
2. Copy its **Application ID** into the app's **Settings → Discord Application ID**
   (**Test** confirms the local Discord client is reachable).
3. **Rich Presence → Art Assets** → upload an image named **`vn_cover`** (the
   fallback used when a cover is a local file or has no usable URL). The key is
   configurable as *Default Discord asset key* in Settings.
4. Discord desktop must be running, with *Activity Privacy → Share your detected
   activities* enabled.

VNDB lookups use the public read API — no account or token.

## Testing without a VN

```
python tools/fake_vn_window.py --title "Grisaia no Kajitsu - Yumiko Route - Chapter 4"
python tools/fake_vn_window.py --game "Sugar*Style" --cycle
python -m pytest -q
```

## Config & data

Everything lives under `%APPDATA%\VisualNovelRPC\`:

| Path | |
|---|---|
| `config.yaml` | global settings |
| `games\<title>.yaml` | one hand-editable file per tracked VN — named after its title once VNDB/Steam/you have identified it, falls back to the exe name until then. Matching a running game back to its file doesn't depend on the filename (a hidden `_key` field does that), so renaming the title — or the file itself — is safe. |
| `cache\vndb\` | cached VNDB search results and downloaded covers |
| `cache\covers\local\` | locally stored / cropped cover images |

Older installs that still have a single `settings.json` are migrated to this
layout automatically the first time the app runs; the old file is left in
place untouched as a safety net.

## Layout

| Path | |
|---|---|
| `vnrpc/window_watcher.py`, `winapi.py` | enumerate windows, track the focused VN |
| `vnrpc/engines.py` | engine signatures + title-noise cleaners |
| `vnrpc/title_parser.py` | title → section label (rule list) |
| `vnrpc/vndb.py` | VNDB Kana API client (cached, throttled) |
| `vnrpc/covers.py` | resolve VNDB / URL / local cover |
| `vnrpc/steam.py` | match a running exe to an installed Steam app (local files only) |
| `vnrpc/presence.py` | Discord RPC connection + rate limiting |
| `vnrpc/autostart.py` | "launch at Windows startup" registry toggle |
| `vnrpc/paths.py` | filesystem locations (`%APPDATA%`, bundled assets) |
| `vnrpc/config.py` | settings + per-game YAML persistence |
| `vnrpc/core.py` | engine that wires it together, emits `Snapshot`s |
| `vnrpc/app.py`, `vnrpc/ui/` | CustomTkinter window + tray |
| `vnrpc/ui/library_dialog.py` | every tracked VN, with time read + relaunch |
| `vnrpc/ui/cover_dialog.py`, `release_dialog.py` | pick/browse a cover (VNDB, URL, local) |
| `vnrpc/ui/crop_dialog.py` | drag-to-crop any cover image |
| `run.pyw`, `vnrpc.spec`, `build.py` | packaging |

The `*.js` files in the repo root are the earlier per-VN prototypes and are not
used by the app.
