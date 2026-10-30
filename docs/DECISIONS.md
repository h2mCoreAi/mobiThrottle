# Decisions

Append-only. Newest at bottom. Short entries — rationale, not essays.

- **2026-10-30 — Split from mobiOverlay's mobiThrottle module at commit `55532f3165ec8800517c24069802115c1bcfe93e`.**
  Source: `modules/mobi_throttle/module.py` (1098-line version with the reduced joystick re-init),
  plus vendored `host/theme.py`, `host/hotkey.py`, `host/single_instance.py`, `host/splash.py`.
  Chosen over the older Tkinter ThrottleWatch (no per-pixel alpha, needed SetWindowRgn hacks, no
  WASAPI-safe chirp). Goal: develop mobiThrottle independently so it never affects the overlay
  framework; the module will be removed from mobiOverlay once this app is signed off.

- **2026-10-30 — ModuleBase/card replaced by ThrottleController + SettingsWindow.**
  `build_settings(layout)` is the old `create_card()` body with identical controls and styles; the
  window just reproduces the card chrome (BG_PANEL, header strip, two-tone title). The overlay
  host's error-state/Retry for a missing device becomes a status line + 5 s reconnect timer.

- **2026-10-30 — Own tray icon and config.json.** The overlay deliberately dropped ThrottleWatch's
  tray; as a standalone app it needs one again. Config is flat, same keys as the module so an
  overlay user can paste their `modules.mobi_throttle` section into config.json.

- **2026-10-30 — Quit uses app.exit(0) via request_quit(), not QApplication.quit().** Qt 6's
  quit() asks visible windows to close and is cancelled if one ignores the close event; the
  settings window ignores close (hide to tray), so Quit silently did nothing while it was open
  (caught by the headless smoke test).

- **2026-10-30 — Redraw only on value change.** The module repainted every 60 Hz poll. Now
  `set_value` skips identical values; the home flash schedules its own repaints. Near-zero idle CPU.

- **2026-10-30 — v1 additions approved by the owner: detents + auto-detect.** Max 2 detents, drawn
  as thin amber lines, optional chirp on crossing (reuses play_home_tick), off by default. Detect
  samples all axes of all sticks for 3 s and picks the largest sweep (≥ 0.25); runs automatically
  on first run. Deliberately no themes, graphs, remapping, plugins or online features.

- **2026-10-30 — Author branding is TheRealKestryl** (LICENSE, docs, tray tooltip, splash).

## 2026-10-30 — Joystick lifecycle: init once, never re-init (crash fix)
- Symptom (Mitch's PC, Win onedir, Py 3.14.7, pygame-ce 2.5.8): tracked briefly, stopped, then APPCRASH 0xc0000005 in python314.dll ~2 min after launch.
- Cause (high confidence by code inspection; not reproduced on hardware): `_reinit_joysticks()` called `pygame.joystick.quit()/init()` on every 60 s rescan, every Refresh/Apply, and at Detect start, while the 60 Hz `_poll` and the detector kept reading `Joystick` objects opened before the re-init. Quit closes the SDL devices under those handles → stale reads (the "stopped tracking") and eventually a use-after-free in native code (the access violation). Two callers (poll + detector + `joystick_plugged_in`) also pumped/drained the event queue independently.
- Fix: one `_Joysticks` owner. Subsystem initialised once; devices opened once and keyed by SDL instance id; hot-plug via JOYDEVICEADDED/REMOVED; `_poll` is the only pump; axis reads pause during detect; a removed device's handle is dropped and never touched. Regression test asserts `pygame.joystick.quit` is never called at runtime.
- Added `mobiThrottle-crash.log` next to the exe (faulthandler, all threads + excepthook) so any future native crash leaves a Python stack.

## 2026-10-30 — Auto-detect prefers throttle-like axes
- First run picked VKB Gladiator EVO L axis 0 (stick X) because it swept widest. Now `pick_axis` prefers axes that moved ≥0.25 AND ended ≥0.15 away from their start (throttles stay put, sprung stick axes return to center); falls back to largest sweep only if every axis sprang back.
- This only chooses the auto-detect default. Device/axis selection stays fully generic: any SDL-visible controller/HID device and any axis index can be picked manually in settings.

## 2026-10-30 — Build size: slim PySide6, keep the stack
- Spec now excludes every Qt module except QtCore/QtGui/QtWidgets, drops opengl32sw/d3dcompiler, Qt translations, all image-format plugins except qico, unused platform plugins on Windows (qwindows only), tkinter/unittest/pydoc/etc., and pygame docs/examples/tests (replaced `collect_all('pygame')` with PyInstaller's built-in pygame hook). UPX/strip stay off: UPX on Qt DLLs causes AV false positives and broken plugins; strip is a no-op on Windows.
- Measured on Linux box: 228 MB → 166 MB (Linux bundles ICU 39 MB + GTK that Windows doesn't). Windows estimate: ~55–70 MB unzipped (from ~155), ~25–30 MB zipped — verify on the next Windows build.
- Library comparison / verdict — keep PySide6 + pygame-ce, add nothing:
  - pysdl2 (zlib-licensed SDL wrapper): same SDL2.dll underneath (~2–3 MB), so ~10 MB saved at most vs pygame-ce, but ctypes calls bypass pygame's handle bookkeeping (more crash risk, not less) and we'd lose pygame.mixer for the chirp. Not worth it.
  - Raw XInput: Xbox-class pads only; VKB/Virpil/Thrustmaster throttles are DirectInput HID — would break generic support. Raw DirectInput/HID via ctypes: lots of new native code = more crash risk.
  - Tkinter/Win32 UI instead of Qt: biggest possible size cut, but a full rewrite of bar/settings/splash/tray and loses the per-pixel-alpha bar and identical mobiOverlay splash. Rejected for now; slimming Qt gets most of the win.

## 2026-10-30 — Minimize hides settings to tray; single-click tray toggles
- Minimizing the settings window hides it (deferred from changeEvent), so it leaves the taskbar. A hidden top-level window has no taskbar button, so the button exists only while settings are open. That's the cleanest Windows behavior and needs no Qt.Tool flag, which would cost the window its title bar and Alt-Tab behavior. The throttle bar is a separate window and is unaffected.
- Single left-click on the tray icon (`Trigger`) toggles settings: show+raise+activate, or hide. DoubleClick is no longer handled because Windows emits Trigger on double-click too. Tray menu, close→hide, and request_quit are unchanged.
- Build hygiene: `*.whl` gitignored; a stray PySDL2 wheel was committed by mistake and removed. Never commit build artifacts.

## 2026-10-30 — Releases built and attested by GitHub only
- Owner requirement: downloaders must be able to verify the exe was compiled by GitHub from public source with nothing injected.
- `release.yml` (v* tags + workflow_dispatch) builds on windows-latest/Python 3.13, runs tests, builds the spec, zips, writes `.sha256`, and signs SLSA build provenance for `mobiThrottle.exe` and the zip via `actions/attest-build-provenance@v2` (Sigstore, OIDC). Users run `gh attestation verify <zip> --repo h2mCoreAi/mobiThrottle`.
- `ci.yml` runs tests + a PyInstaller smoke build on push/PR to main.
- Code signing (Authenticode) not added: needs a paid cert; attestations give provenance for free. Revisit if SmartScreen warnings become a support issue.
- `SECURITY.md` added (private advisory reporting).

## 2026-10-30 — CI supply-chain hardening
- Actions pinned to commit SHAs (tags are mutable; a hijacked tag could inject code into an attested build). Dependabot keeps them current weekly.
- Hash-locked deps (`requirements*.lock`, uv pip compile for windows/py3.13) installed with `--require-hashes --no-deps`, so a compromised PyPI release can't slip into a release build silently. Dropped the unpinned `pip install --upgrade pip` step.
- Least privilege: top-level `contents: read`; write scopes only on the release job. Concurrency: CI cancel-in-progress per ref, release queued never cancelled.
- Note: the lock pulls pyside6-addons/webengine/pdf wheels (the `PySide6` meta-package depends on them). They're installed on the runner but excluded from the bundle by the spec. Switching to `pyside6-essentials` only would speed CI; deferred as a separate change.

## 2026-10-30 — Code cleanup (behavior-preserving)
- `pyproject.toml` holds ruff config (E,F,W,I,UP,B,SIM; line length 110; quotes preserved). CI `lint` job runs `ruff check` + `ruff format --check` with ruff hash-locked in `requirements-lint.lock`.
- Removed dead code: unused theme helpers vendored from mobiOverlay (font-scale options, grid snap, row/action styles), write-only `_rescan_requested`/`_joysticks_scanned_at`, unused `joystick_plugged_in`, `_ThrottleBar.apply_geometry`, unused rescan constants.
- Split the 1.4k-line throttle.py into bar.py / devices.py / widgets.py / detect.py. Code moved verbatim (line-multiset check: every original line present); throttle.py re-exports the moved names so `throttle.X` callers/tests still work.
- Public functions type-hinted. No feature or UI changes.

## 2026-10-30 — In-app Setup Guide replaces silent first-run auto-detect
- Built into the app (not a companion exe): reuses the bundled Qt (a few KB), shares the live stick input and the same config, no second process fighting over the device.
- First run (no config.json yet; `controller.first_run`) opens the guide instead of auto-starting Detect; reopenable from Settings → SETUP GUIDE. An existing config without a device does not reopen it every launch.
- Apply-as-you-go: every control calls the same ThrottleController setters/handlers as the settings window and saves immediately, so the bar reacts live. **Cancel (or the window X) keeps changes already made** — nothing to revert, and the guide never leaves settings half-written. Settings-window widgets are re-synced on close (`sync_settings_widgets`).
- Joysticks: the guide never calls pygame; device lists via `list_joysticks()`, detect via `controller.start_detect()` (AxisDetector on the shared `_Joysticks` owner) and the new `detect_finished` signal; the live preview reads `controller.current_value`. Test asserts `pygame.joystick.quit` is never called.
- Refactors for reuse (no behavior change): `apply_device()`, `set_axis_reverse()`, `set_line_color()/set_bg_color()`, `current_value`, `build_card()`, `schedule_first_run()`.

## 2026-10-30 — Centre-zero indicator, axis readout, disconnect alert
- **Centre-zero colours** (`centre_zero_colors`, default off): only the moving indicator changes colour — `FORWARD_COLOR` #5ee08a above zero, `REVERSE_COLOR` #ff6b5a below, the line colour within `ZERO_BAND` (= home `DEADZONE`). Fixed colours, no extra pickers (fewer options). Zero point is 0.0: mobiThrottle has no separate home-position setting (home chirp already uses centre/0), so there is nothing else to key off. Track/ticks unchanged. One checkbox in Settings → Appearance and in the guide's Colors step.
- **Axis readout** (guide Axis + Direction steps): `detect.AxisStats` is fed the raw value in the existing 60 Hz `_poll` (O(30) per sample, no new threads/timers). The label refreshes every 8th tick of the guide's existing LiveBar timer (~4 Hz). Shows raw, min/max, rest jitter (span of a still 0.5 s window) and a hint: rests at far end → suggest Reverse; suggested deadzone = max(0.03, 1.5× jitter). Display-only — there is no deadzone setting; it is advice. Stats reset on device/axis change and detect.
- **Disconnect alert** (`disconnect_alert`, default on): triggers only on the selected device's JOYDEVICEREMOVED, as already detected by the single `_Joysticks` owner's pump in `_poll` (not on transient read errors). Bar greys (`DISCONNECTED_COLOR`, 45% opacity) and plays one 520 Hz/170 ms tone (home tick is 1400 Hz/45 ms) once per disconnect; `_try_connect` restores the look on reconnect. Never re-inits joysticks (tested).
