"""Headless tests for the setup guide. Script-style like test_throttle.py.

python tests/test_setup_guide.py
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from mobithrottle import setup_guide as sg  # noqa: E402
from mobithrottle import throttle  # noqa: E402
from mobithrottle.config import Config  # noqa: E402
from mobithrottle.settings_window import SettingsWindow  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QApplication.instance() or QApplication(sys.argv)
tmp = Path(tempfile.mkdtemp())


def make(name="c.json"):
    """Controller + settings window with polling stopped (hardware-independent)."""
    c = Config(tmp / name)
    ctl = throttle.ThrottleController(c)
    win = SettingsWindow(ctl)
    for t in (ctl._poll_timer, ctl._reconnect_timer):
        t.stop()
    ctl._device = None
    return c, ctl, win


def step(guide, cls):
    return next(s for s in guide.steps if isinstance(s, cls))


def t_construct_and_navigate():
    _, ctl, win = make()
    g = sg.SetupGuide(ctl)
    check("11 steps", len(g.steps) == 11 and g.stack.count() == 11)
    check("starts at welcome", g.index == 0 and not g.back_btn.isEnabled() and not g.skip_btn.isVisibleTo(g))
    g.show()
    for _ in range(10):
        g.next()
    check("reaches done", g.index == 10 and g.next_btn.text() == "Finish")
    g.back()
    check("back works", g.index == 9 and g.next_btn.text() == "Next")
    g.skip_btn.click()
    check("skip advances", g.index == 10)
    results = []
    g.finished.connect(results.append)
    g.next()
    check("finish closes and reports", results == [True] and not g.isVisible())
    g.go(3)
    g.show()
    g.cancel()
    check("cancel reports False", results == [True, False])
    ctl.shutdown()


def t_writes_settings():
    c, ctl, win = make("w.json")
    g = sg.SetupGuide(ctl)
    step(g, sg.DirectionStep).reverse.setChecked(True)
    check("reverse saved", Config(c.path).settings["axis_reverse"] is True)
    step(g, sg.LayoutStep).combo.setCurrentText("Horizontal")
    check("orientation saved", Config(c.path).settings["orientation"] == "horizontal")
    colors = step(g, sg.ColorsStep)
    colors.centre_zero.setChecked(True)
    check("guide centre-zero saved", Config(c.path).settings["centre_zero_colors"] is True)
    colors.line_slider.setValue(40)
    ctl.set_line_color("#123456")
    s = Config(c.path).settings
    check("opacity + color saved", s["line_opacity"] == 0.4 and s["line_color"] == "#123456")
    chirp = step(g, sg.ChirpStep)
    chirp.enabled.setChecked(not ctl.settings["home_chirp_enabled"])
    chirp.count.setValue(3)
    check("chirp count saved", Config(c.path).settings["home_chirp_count"] == 3)
    ctl._bar.set_value(0.25)
    det = step(g, sg.DetentsStep)
    det._set("detent_1")
    check(
        "detent from live value",
        Config(c.path).settings["detent_1"] == 0.25 and "+0.25" in det.values["detent_1"].text(),
    )
    step(g, sg.ClickThroughStep).toggle.setChecked(True)
    check("click-through saved", Config(c.path).settings["click_through"] is True)
    ctl._on_toggle_hotkey_applied("ctrl+f9")
    g.go(10)
    summary = step(g, sg.DoneStep).summary.text()
    check(
        "summary reflects choices", "reversed" in summary and "horizontal" in summary and "ctrl+f9" in summary
    )
    g.cancel()
    check("cancel keeps applied changes", Config(c.path).settings["axis_reverse"] is True)
    check(
        "settings window synced",
        win.isHidden()
        and ctl.axis_reverse_check.isChecked()
        and ctl.orientation_combo.currentText() == "Horizontal"
        and ctl.click_through_check.isChecked(),
    )
    ctl._toggle_hotkey.clear()
    ctl.shutdown()


def t_live_bar_and_detect():
    _, ctl, win = make("d.json")
    g = sg.SetupGuide(ctl)
    axis = step(g, sg.AxisStep)
    ctl._bar.set_value(-0.5)
    axis.live.tick()
    check("live bar follows value", axis.live.value == -0.5)
    axis.live.grab()
    g.go(2)
    check("axis list filled", axis.axis_combo.count() >= 1)
    axis.detect()
    check("detect started on shared owner", ctl._detector is not None and not axis.detect_btn.isEnabled())
    ctl._detector.cancel()
    ctl._on_detect_done(None)
    check("detect result shown", axis.detect_btn.isEnabled() and "No movement" in axis.status.text())
    ctl._on_detect_done(("guid-x", "Test Throttle", 2))
    check("detect applies axis", ctl.settings["axis_index"] == 2 and "Test Throttle" in axis.status.text())
    ctl.shutdown()


def t_no_reinit():
    import pygame

    calls = []
    orig = pygame.joystick.quit
    pygame.joystick.quit = lambda: calls.append(1)
    try:
        _, ctl, win = make("n.json")
        g = sg.SetupGuide(ctl)
        for i in range(11):
            g.go(i)
        step(g, sg.DeviceStep).reload()
        step(g, sg.DeviceStep)._apply(0)
        ctl.shutdown()
    finally:
        pygame.joystick.quit = orig
    check("guide never re-inits joysticks", not calls)


def t_first_run_and_button():
    from mobithrottle import app as app_mod

    _, ctl, win = make("first.json")
    check("fresh config is first run", ctl.first_run)
    opened = []
    win.open_setup_guide = lambda: opened.append(1)
    check("first run schedules guide", app_mod.schedule_first_run(ctl, win, delay_ms=0))
    app.processEvents()
    check("first run opened guide", opened == [1])
    ctl.shutdown()

    c2 = Config(tmp / "second.json")
    c2.save()
    ctl2 = throttle.ThrottleController(Config(tmp / "second.json"))
    win2 = SettingsWindow(ctl2)
    check("existing config: no guide", not app_mod.schedule_first_run(ctl2, win2, delay_ms=0))
    win2.guide_btn.click()
    check(
        "settings button opens guide",
        win2.setup_guide is not None and win2.setup_guide.isVisible() and win2.setup_guide.index == 0,
    )
    win2.setup_guide.go(5)
    win2.guide_btn.click()
    check("reopen restarts at step 1", win2.setup_guide.index == 0)
    win2.setup_guide.cancel()
    ctl2.shutdown()


for name, fn in [
    ("construct_and_navigate", t_construct_and_navigate),
    ("writes_settings", t_writes_settings),
    ("live_bar_and_detect", t_live_bar_and_detect),
    ("no_reinit", t_no_reinit),
    ("first_run_and_button", t_first_run_and_button),
]:
    try:
        fn()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        check(name, False, repr(exc))

print(f"\n{'ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
