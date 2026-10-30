# Architecture

```
mobithrottle/
  __main__.py        python -m mobithrottle -> app.main()
  app.py             entry: single-instance guard, fonts, splash, controller, settings window,
                     tray, teardown wiring (aboutToQuit / atexit / SIGINT+SIGTERM / excepthook)
  throttle.py        ThrottleController (replaces ModuleBase): settings, poll + reconnect timers,
                     hotkeys, build_settings(layout); re-exports the names below for compatibility
  bar.py             _ThrottleBar floating frameless always-on-top bar, Win32 click-through,
                     colour helpers, default bar position
  devices.py         _Joysticks single owner (hot-plug, never re-inits), list/find_joystick, chirp
  widgets.py         settings-panel styles, _Stepper, _HotkeyField
  detect.py          detent_crossed / pick_axis / AxisDetector (v1 additions)
  settings_window.py card-styled window hosting build_settings(); close = hide to tray
  splash.py          mobiOverlay's splash, same style, "mobiThrottle / by TheRealKestryl"
  config.py          flat config.json next to exe (frozen) / repo root (source); atomic save
  paths.py           app_root() (persistent) vs assets_dir() (bundled)
  single_instance.py lockfile guard (.mobithrottle.lock), vendored from mobiOverlay
  hotkey.py          GlobalHotkey (WH_KEYBOARD_LL via `keyboard`), vendored, Win32 guarded
  theme.py           MobiGlas palette/fonts, vendored
  icon.py            draws the tray/app icon
  assets/            fonts (OFL), mobithrottle.png/.ico
tests/test_throttle.py   headless script-style tests
mobithrottle.spec        PyInstaller onedir; entry script mobithrottle_entry.py
```

## Runtime flow

1. `SingleInstance` lock → if held, show a message and exit 1.
2. Splash (plain frameless QWidget, not QSplashScreen — see splash.py) while config loads.
3. `ThrottleController(config)` creates the bar, a 60 Hz axis poll timer and a
   `refresh_interval_seconds` (5 s) reconnect timer. `SettingsWindow` calls `build_settings()`.
4. Tray menu: Show Settings / Toggle Bar / Toggle Click-Through / Quit.
   Quit goes through `app.request_quit()` (see DECISIONS: Qt 6 quit() is cancelled by a window
   that ignores close).
5. On any exit path `_teardown()` → `controller.shutdown()` stops timers and unhooks both
   GlobalHotkeys. Idempotent.

## Joystick logic

- Passive pygame-ce reads only (`get_axis`). Never any game-process access.
- Reduced re-init (from mobiOverlay 55532f3): restarting pygame's joystick subsystem blocks the GUI
  ~0.25 s, so with no device the reconnect check only rescans on SDL `JOYDEVICEADDED`, on explicit
  request (Apply/Detect/read failure), or every `JOYSTICK_RESCAN_SECONDS` (60 s).
- Redraw only when the axis value changes (`_ThrottleBar.set_value`); the home-flash pop schedules
  its own two repaints.

## Config keys

Same keys/defaults as the overlay module's `DEFAULTS` (flat, not nested under `modules.mobi_throttle`)
plus `detent_1`, `detent_2` (axis value −1..1 or null), `detent_1_chirp`, `detent_2_chirp` (false).
`x`/`y` are filled on first run with a spot on a non-primary monitor.
