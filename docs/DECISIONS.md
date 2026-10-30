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
