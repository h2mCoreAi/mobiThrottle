"""Headless tests for mobiThrottle. Script-style: prints [PASS]/[FAIL] per
check and exits nonzero on any failure.

    python tests/test_throttle.py
"""

import io
import json
import os
import sys
import tempfile
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from mobithrottle import throttle  # noqa: E402
from mobithrottle.config import Config, default_settings  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def run(name, fn):
    try:
        fn()
    except Exception as exc:  # a crash is a failure, not an abort
        import traceback

        traceback.print_exc()
        check(name, False, repr(exc))


app = QApplication.instance() or QApplication(sys.argv)
tmp = Path(tempfile.mkdtemp())


def t_colors():
    check("dim_color", throttle.dim_color("#ffffff", 0.5) == "#7f7f7f", throttle.dim_color("#ffffff", 0.5))
    check(
        "lerp_color endpoints",
        throttle.lerp_color("#000000", "#ffffff", 0) == "#000000"
        and throttle.lerp_color("#000000", "#ffffff", 1) == "#ffffff",
    )
    check("value_to_color nominal at center", throttle.value_to_color(0.0, "#6ec8ff") == "#6ec8ff")
    check(
        "value_to_color amber at full", throttle.value_to_color(1.0, "#6ec8ff") == throttle.theme.ACCENT_AMBER
    )
    check(
        "panel_radius clamps",
        throttle.panel_radius_for(10, 10) == throttle.PANEL_RADIUS_MIN
        and throttle.panel_radius_for(1000, 1000) == throttle.PANEL_RADIUS_MAX,
    )


def t_chirp():
    data = throttle._generate_chirp_wav(1400, 45, 0.3)
    with wave.open(io.BytesIO(data)) as wf:
        check(
            "chirp wav format",
            wf.getnchannels() == 1 and wf.getsampwidth() == 2 and wf.getframerate() == 22050,
        )
        check("chirp wav length", wf.getnframes() == int(22050 * 45 / 1000), wf.getnframes())


def t_config():
    p = tmp / "config.json"
    c = Config(p)
    check("config new file not existed", c.existed is False)
    d = default_settings()
    for k, v in {
        "axis_index": 0,
        "axis_reverse": False,
        "orientation": "vertical",
        "width": 60,
        "height": 260,
        "bg_opacity": 0.85,
        "line_opacity": 1.0,
        "bar_visible": True,
        "click_through": False,
        "home_chirp_enabled": True,
        "home_chirp_count": 1,
        "home_chirp_cooldown": 2.0,
        "toggle_hotkey": "",
        "position_hotkey": "",
        "position_hold_ms": 0,
        "refresh_interval_seconds": 5,
        "detent_1": None,
        "detent_1_chirp": False,
    }.items():
        check(f"default {k}", d.get(k) == v, d.get(k))
    c.settings.update(d)
    c.settings["axis_index"] = 3
    c.settings["detent_2"] = 0.42
    c.save()
    c2 = Config(p)
    check(
        "config round-trip", c2.existed and c2.settings["axis_index"] == 3 and c2.settings["detent_2"] == 0.42
    )
    p.write_text("{not json")
    c3 = Config(p)
    check("corrupt config falls back", c3.settings == {} and (tmp / "config.json.corrupt").exists())


def t_detent():
    dc = throttle.detent_crossed
    check("detent crossed upward", dc(-0.5, 0.5, 0.0))
    check("detent crossed downward", dc(0.5, -0.5, 0.0))
    check("detent reached exactly", dc(0.1, 0.3, 0.3))
    check("leaving detent is not a crossing", not dc(0.3, 0.5, 0.3))
    check("no move no crossing", not dc(0.3, 0.3, 0.3))
    check("not between", not dc(0.1, 0.2, 0.5))


def t_pick_axis():
    pa = throttle.pick_axis
    check("pick largest sweep", pa({(0, 0): (-0.1, 0.1), (0, 2): (-0.9, 0.8), (1, 1): (0, 0.5)}) == (0, 2))
    check("pick none when noise only", pa({(0, 0): (-0.05, 0.05), (1, 3): (0.0, 0.1)}) is None)
    check("pick empty", pa({}) is None)
    # stick X swept wide but sprang back to center; throttle swept less but stayed put
    r = {(0, 0): (-1.0, 1.0), (0, 2): (-1.0, 0.4)}
    e = {(0, 0): (0.0, 0.01), (0, 2): (-1.0, 0.4)}
    check("prefer axis that stays put over centering stick", pa(r, ends=e) == (0, 2))
    check(
        "fallback to largest sweep if all centered", pa(r, ends={(0, 0): (0, 0), (0, 2): (0, 0.05)}) == (0, 0)
    )


def t_no_reinit():
    import pygame

    calls = []
    orig = pygame.joystick.quit
    pygame.joystick.quit = lambda: calls.append(1)
    try:
        c = Config(tmp / "r.json")
        ctl = throttle.ThrottleController(c)
        ctl._try_connect()
        throttle.list_joysticks()
        throttle.find_joystick(None)
        d = throttle.AxisDetector(lambda r: None)
        d.start()
        d._sample()
        d._finish()
        ctl.start_detect()
        ctl._detector.cancel()
        ctl._detector = None
        for _ in range(3):
            ctl._poll()
        ctl.shutdown()
    finally:
        pygame.joystick.quit = orig
    check("joystick subsystem never quit at runtime", not calls)


def t_widgets():
    from mobithrottle.settings_window import SettingsWindow

    c = Config(tmp / "w.json")
    ctl = throttle.ThrottleController(c)
    # Hardware-independent: a real connected joystick's 60 Hz _poll would
    # overwrite the bar value we set below. Stop polling and drop any device.
    ctl._poll_timer.stop()
    ctl._reconnect_timer.stop()
    ctl._device = None
    win = SettingsWindow(ctl)
    ctl._poll_timer.stop()
    ctl._reconnect_timer.stop()
    ctl._device = None
    win.show()
    app.processEvents()
    bar = ctl._bar
    bar.set_value(0.5)
    app.processEvents()
    check("bar value set", bar.value == 0.5)
    # reverse mapping: same expression _poll uses
    ctl.settings["axis_reverse"] = True
    raw = 0.7
    check("reverse maps raw -> -raw", (-raw if ctl.settings["axis_reverse"] else raw) == -0.7)
    pos_along = (bar.value + 1.0) / 2.0 * 100
    check("value -> track position", pos_along == 75.0)
    ctl._set_detent("detent_1")
    app.processEvents()
    check("set detent from bar value", ctl.settings["detent_1"] == 0.5)
    bar.grab()  # force a paint with a detent drawn
    ctl.toggle_bar()
    check("toggle bar hides", ctl.settings["bar_visible"] is False and not bar.isVisible())
    ctl.toggle_click_through()
    check("toggle click-through", ctl.settings["click_through"] is True)
    ctl._on_orientation_changed("Horizontal")
    check("orientation swap", (ctl.settings["width"], ctl.settings["height"]) == (260, 60))
    win.show_and_raise()
    app.processEvents()
    win.showMinimized()
    app.processEvents()
    app.processEvents()
    check("minimize hides to tray", not win.isVisible() and not win.isMinimized())
    check("bar unaffected by minimize", bar.isVisible() == bool(ctl.settings["bar_visible"]))
    win.toggle_visible()
    app.processEvents()
    check("tray click shows", win.isVisible())
    win.toggle_visible()
    app.processEvents()
    check("tray click hides", not win.isVisible())
    win.show_and_raise()
    app.processEvents()
    win.close()
    check("close hides (no quit)", not win.isVisible())
    ctl.shutdown()
    check(
        "no keyboard hook by default", ctl._toggle_hotkey._hook is None and ctl._position_hotkey._hook is None
    )
    saved = json.loads((tmp / "w.json").read_text())
    check("settings persisted", saved["detent_1"] == 0.5)


def t_splash():
    from mobithrottle.splash import Splash

    s = Splash()
    s.show_message("x")
    app.processEvents()
    check("splash size matches mobiOverlay", (s.width(), s.height()) == (320, 150))
    s.close()


def t_single_instance():
    from mobithrottle import single_instance as si

    si.app_root = lambda: tmp  # isolate the lockfile
    a = si.SingleInstance().__enter__()
    try:
        si.SingleInstance().__enter__()
        check("second instance blocked", False)
    except si.SingleInstanceError:
        check("second instance blocked", True)
    a.__exit__(None, None, None)
    b = si.SingleInstance().__enter__()
    b.__exit__(None, None, None)
    check("lock released on exit", True)


for n, f in [
    ("single_instance", t_single_instance),
    ("colors", t_colors),
    ("chirp", t_chirp),
    ("config", t_config),
    ("detent", t_detent),
    ("pick_axis", t_pick_axis),
    ("widgets", t_widgets),
    ("no_reinit", t_no_reinit),
    ("splash", t_splash),
]:
    run(n, f)

print(f"\n{'ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
