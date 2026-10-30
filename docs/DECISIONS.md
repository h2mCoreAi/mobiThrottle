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
