"""App entry: single-instance guard, splash, controller + settings window,
tray icon, and hotkey teardown on every exit path.

`python -m mobithrottle` or the frozen mobiThrottle.exe both land in main().
Env MOBITHROTTLE_SMOKE_MS=<n>: quit automatically after n ms (headless
smoke test; see AGENTS.md).
"""

import atexit
import logging
import os
import signal
import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QFontDatabase
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__
from .config import Config
from .icon import app_icon
from .paths import assets_dir
from .single_instance import SingleInstance, SingleInstanceError
from .splash import set_status, show_splash

logger = logging.getLogger("mobithrottle")

_instance_lock = None
_controller = None


def load_fonts() -> None:
    for font_file in (assets_dir() / "fonts").glob("*.ttf"):
        if QFontDatabase.addApplicationFont(str(font_file)) == -1:
            logger.warning("Failed to load bundled font: %s", font_file.name)


def _teardown():
    """Release global keyboard hooks + timers. Idempotent; wired to
    aboutToQuit, atexit, SIGINT/SIGTERM and the excepthook."""
    global _controller
    c, _controller = _controller, None
    if c is not None:
        try:
            c.shutdown()
        except Exception:
            traceback.print_exc()


_crash_file = None


def _install_crash_log():
    """faulthandler -> mobiThrottle-crash.log next to the exe, so a native
    crash (e.g. an access violation in SDL) leaves a Python stack."""
    global _crash_file
    try:
        import faulthandler

        from .paths import app_root

        _crash_file = open(app_root() / "mobiThrottle-crash.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115 -- must stay open for faulthandler
        faulthandler.enable(_crash_file, all_threads=True)
    except Exception:
        _crash_file = None


def _log_exception(exc_type, exc_value, exc_tb):
    if _crash_file is not None:
        try:
            import time

            _crash_file.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} unhandled exception ---\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=_crash_file)
            _crash_file.flush()
        except Exception:
            pass


def _install_excepthook():
    def _hook(exc_type, exc_value, exc_tb):
        traceback.print_exception(exc_type, exc_value, exc_tb)
        _log_exception(exc_type, exc_value, exc_tb)
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            _teardown()

    sys.excepthook = _hook


def request_quit(app, window) -> None:
    """Quit for real. Qt 6's QApplication.quit() first asks every visible
    window to close and is cancelled if one refuses — and SettingsWindow
    refuses (close = hide to tray). So mark it closable, then exit."""
    window.allow_close = True
    window.hide()
    app.exit(0)


def _build_tray(app, controller, window, icon):
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip(f"mobiThrottle v{__version__} by TheRealKestryl")
    menu = QMenu()
    show_act = QAction("Show Settings", menu)
    show_act.triggered.connect(window.show_and_raise)
    bar_act = QAction("Toggle Bar", menu)
    bar_act.triggered.connect(controller.toggle_bar)
    ct_act = QAction("Toggle Click-Through", menu, checkable=True)
    ct_act.setChecked(bool(controller.settings["click_through"]))
    ct_act.triggered.connect(lambda _=False: controller.toggle_click_through())
    controller.click_through_changed.connect(ct_act.setChecked)
    quit_act = QAction("Quit", menu)
    quit_act.triggered.connect(lambda _=False: request_quit(app, window))
    for a in (show_act, bar_act, ct_act):
        menu.addAction(a)
    menu.addSeparator()
    menu.addAction(quit_act)
    tray.setContextMenu(menu)
    tray.activated.connect(
        # Trigger only: on Windows a double-click also emits Trigger, so handling
        # DoubleClick too would toggle twice.
        lambda reason: window.toggle_visible() if reason == QSystemTrayIcon.Trigger else None
    )
    tray._menu = menu  # keep alive
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()
    return tray


def main(argv: list[str] | None = None) -> int:
    global _instance_lock, _controller
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    _install_crash_log()
    _install_excepthook()

    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("mobiThrottle")
    app.setOrganizationName("TheRealKestryl")
    app.setQuitOnLastWindowClosed(False)  # lives in the tray

    try:
        _instance_lock = SingleInstance().__enter__()
        atexit.register(_instance_lock.__exit__, None, None, None)
    except SingleInstanceError as e:
        QMessageBox.warning(None, "mobiThrottle", str(e))
        return 1

    load_fonts()
    splash = show_splash()
    icon = app_icon()
    app.setWindowIcon(icon)

    set_status(splash, "Loading settings...")
    config = Config()
    from .settings_window import SettingsWindow
    from .throttle import ThrottleController

    set_status(splash, "Starting mobiThrottle...")
    _controller = ThrottleController(config)
    controller = _controller
    window = SettingsWindow(controller, icon)
    tray = _build_tray(app, controller, window, icon)

    app.aboutToQuit.connect(_teardown)
    atexit.register(_teardown)

    def _on_signal(*_):
        _teardown()
        request_quit(app, window)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass
    # Let Python see signals while Qt's loop runs.
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(500)

    splash.finish(window)
    # No tray available: show settings so the user can find the app. On
    # first run the setup guide opens instead (below).
    if not controller.first_run and not QSystemTrayIcon.isSystemTrayAvailable():
        window.show_and_raise()
    # First run: the setup guide replaces the old silent auto-detect.
    if controller.first_run:
        QTimer.singleShot(300, window.open_setup_guide)

    smoke_ms = int(os.environ.get("MOBITHROTTLE_SMOKE_MS", "0") or 0)
    if smoke_ms > 0:
        smoke_timer = QTimer()
        smoke_timer.setSingleShot(True)
        smoke_timer.timeout.connect(lambda: request_quit(app, window))
        smoke_timer.start(smoke_ms)

    try:
        code = app.exec()
    finally:
        _teardown()
        tray.hide()
    return code
