# AGENTS.md — mobiThrottle

Canonical onboarding for any AI agent (or human) working on this repo. `CLAUDE.md` points here.

**What it is:** a standalone, lightweight Windows app (PySide6 + pygame-ce) by TheRealKestryl that
shows a flight-stick throttle axis as a floating always-on-top bar, with a tray icon and a small
settings window. Split out of mobiOverlay's mobiThrottle module (see `docs/DECISIONS.md`).

**Design rule: stay extremely lightweight.** One bar, one settings window, two runtime deps
(+ optional `keyboard` for hotkeys). No themes, graphs, input remapping, plugins, telemetry, or
network access. Redraw only on change. Ask the owner before adding a setting.

## Layout

See `docs/ARCHITECTURE.md` for the full map. Key files: `mobithrottle/app.py` (entry + tray + teardown),
`mobithrottle/throttle.py` (bar + controller), `mobithrottle/settings_window.py`, `mobithrottle/config.py`,
`tests/test_throttle.py`, `mobithrottle.spec`, `.github/workflows/release.yml`, `.github/workflows/ci.yml`, `SECURITY.md`.

## Run from source

```powershell
py -3.12 -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m mobithrottle
```
From source, `config.json` and `.mobithrottle.lock` live in the repo root (gitignored).

## Test (exact command)

```bash
QT_QPA_PLATFORM=offscreen SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python tests/test_throttle.py
```
PowerShell: `$env:QT_QPA_PLATFORM="offscreen"; $env:SDL_VIDEODRIVER="dummy"; $env:SDL_AUDIODRIVER="dummy"; python tests\test_throttle.py`
Must end with `ALL PASSED` (exit 0). Headless smoke launch (auto-quits after 2 s, must exit 0):
```bash
QT_QPA_PLATFORM=offscreen SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy MOBITHROTTLE_SMOKE_MS=2000 python -m mobithrottle
```

## Build / release

- Local: `pip install -r requirements-build.txt` then `pyinstaller mobithrottle.spec --noconfirm`
  → `dist\mobiThrottle\mobiThrottle.exe` (onedir; keep `_internal\`). Details: `BUILD.md`.
- Release: bump `mobithrottle/__init__.py` `__version__`, commit, push tag `vX.Y.Z`. CI builds on
  windows-latest (Python 3.13), attests build provenance for exe + zip, and publishes
  `mobiThrottle-vX.Y.Z-windows.zip` + `.sha256`. CI (`ci.yml`) must be green on main first.
  Never upload locally built binaries to a release; users verify with `gh attestation verify`.

## Side-by-side testing (never disturb the owner's live copy)

- Build into `dist\` and copy to a separate folder, e.g. `C:\Users\<user>\Desktop\mobiThrottle-test\`.
  Never overwrite the live folder until the owner says so.
- Each folder has its own `config.json` and lockfile, so a test copy can't corrupt live settings —
  but the single-instance lock is per folder, so **close the live mobiThrottle before launching a
  test copy** (two copies = two possible keyboard hooks; see rule 7 below).
- While the owner still runs mobiOverlay with its built-in mobiThrottle module, hide that module's
  bar or close the overlay before testing so two bars don't fight over the same hotkeys.
- Kill only `mobiThrottle.exe` / the `python -m mobithrottle` process — never a game process.

## Safety notes specific to mobiThrottle

- No hotkeys by default → no `WH_KEYBOARD_LL` hook is ever installed unless the user sets one.
  Any hook is released on every exit path (`app._teardown`, `GlobalHotkey` atexit). Keep it that way.
- All Win32/`keyboard` use is guarded so the package imports on Linux/macOS (tests, CI).
- Passive HID reads only. Never read/write game memory, inject input, or touch game processes.

The rules below are copied verbatim from mobiOverlay's AGENTS.md. Where they say "mobiOverlay",
they apply equally to mobiThrottle (`mobiThrottle.exe` / `python -m mobithrottle`).

## HARD SAFETY RULES

These rules are non-negotiable. Violating them can corrupt the owner's live
overlay, break Star Citizen input, or cause account issues.

### 1. Never force-kill Star Citizen processes

**Never** kill `StarCitizen.exe`, `EasyAntiCheat` service, `RSI Launcher`, or
any SC-related process. Only ever kill `mobiOverlay.exe` / `python.exe` running
mobiOverlay.

If SC keyboard input is wedged (WASD/menus unresponsive), the cause is usually
a leftover `WH_KEYBOARD_LL` hook from a crashed mobiOverlay. Fix:
1. Kill mobiOverlay (Task Manager → `mobiOverlay.exe` or `python.exe`)
2. Have the user quit Star Citizen normally and relaunch

**Never casually suggest "Character Repair"** — it has a 1-hour+ wait and can
have side effects. Only mention it if the user specifically asks about it.

### 2. Never leave the packaged overlay running unattended alongside SC

The global keyboard hook can interfere with exclusive-fullscreen games. If
you're testing and need to step away, close mobiOverlay first.

### 3. Never send global hotkey keystrokes while SC may be live

Don't use `keyboard.send()`, `keybd_event()`, or similar to inject keystrokes
into a running mobiOverlay instance while SC might be active — two instances
can race on the same `WH_KEYBOARD_LL` hook, and synthetic input can trigger
unintended game actions.

### 4. Never move the overlay onto the primary/gaming monitor

The owner's primary display is their active gaming monitor. Never reposition
the mobiOverlay window there for testing. Use `PrintWindow` to capture the
overlay's content without moving it.

### 5. Never embed a shared UEX token in the distributed app

The app uses only anonymous public API endpoints. Never add auth tokens,
API keys, or credentials to code that gets committed. If auth is needed for
a future feature, it must be user-provided in Settings.

### 6. Never invent game/API logic UEX doesn't compute

Don't write custom pathfinding, commodity prediction, or market analysis that
UEX's own API doesn't provide. The modules display UEX data as-is, with only
client-side filtering/sorting.

**Explicit, documented exception: Logistics Hub's route ordering.** UEX has
no "best order to visit these stops" endpoint, so Logistics Hub builds a
distance matrix from real `terminals_distances`/`orbits_distances` calls
and solves the stop order itself (greedy nearest-neighbor + 2-opt
improvement) — the distances are real UEX data, only the ordering logic is
ours. Scoped and justified in `docs/BACKLOG.md`'s "Multi-Stop Contract
Route Optimizer" entry; this is the one deliberate carve-out from this rule,
not a precedent for inventing logic elsewhere.

### 7. Never run two mobiOverlay instances at once

The single-instance guard exists for a reason. Don't bypass it. Check for
running instances before launching another:
```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'mobiOverlay.exe' -or $_.CommandLine -like '*host*main.py*' } | Select-Object ProcessId, Name, CommandLine
```

---

