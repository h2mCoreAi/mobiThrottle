"""The floating throttle bar widget, its Win32 click-through plumbing and colour helpers."""

import ctypes
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QWidget,
)

from . import theme

if TYPE_CHECKING:
    from .throttle import ThrottleController

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
# Guarded so this imports on non-Windows (headless tests); click-through
# then falls back to Qt's WA_TransparentForMouseEvents only.
_user32 = ctypes.windll.user32 if sys.platform == "win32" else None
if _user32 is not None:
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _user32.SetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]

AXIS_POLL_HZ = 60
DEADZONE = 0.03
MIN_BAR_WIDTH = 14
MIN_BAR_HEIGHT = 14
TRACK_MARGIN = 10  # px reserved on each side of the track for tick marks
TICK_COUNT = 10  # divisions; TICK_COUNT + 1 marks drawn along the travel axis
KNOB_HALF_THICKNESS = 4
KNOB_POP_HALF_THICKNESS = 11  # briefly wider knob on a home crossing
HOME_FLASH_DURATION = 0.18  # seconds
RECONNECT_STATUS_UNAVAILABLE = "No device connected"
# Corner radius for the panel background, scaled to the bar's own size
# rather than a fixed px value — this bar is user-resizable over a wide
# range (a thin sliver up past a normal card's width), and a fixed radius
# either overwhelms a thin bar into a full pill or shrinks to invisible on
# a large one.
PANEL_RADIUS_RATIO = 0.22
PANEL_RADIUS_MIN = 8
PANEL_RADIUS_MAX = 40
KNOB_HIGHLIGHT = "#e4e9f5"


def panel_radius_for(w, h):
    return min(PANEL_RADIUS_MAX, max(PANEL_RADIUS_MIN, round(min(w, h) * PANEL_RADIUS_RATIO)))


def dim_color(hex_color, factor=0.55):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def lerp_color(hex_a, hex_b, t):
    a = tuple(int(hex_a.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(hex_b.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    r, g, bl = (round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"#{r:02x}{g:02x}{bl:02x}"


def value_to_color(abs_val, line_color):
    """The bar's own accent color (nominal) at center, gradually shifting to
    the alert amber at full deflection — mirrors MobiGlas's own
    cyan=nominal/amber=alert convention."""
    span = max(1e-9, 1.0 - DEADZONE)
    t = max(0.0, min(1.0, (abs_val - DEADZONE) / span))
    return lerp_color(line_color, theme.ACCENT_AMBER, t)


def _default_bar_position() -> tuple[int, int]:
    """Same non-primary-monitor default host/main_window.py's own window
    uses (see its _default_launch_position) — this machine's primary
    monitor is the active gaming display, and a floating bar defaulting
    there is exactly the mistake that fix exists to avoid. Only used when
    no position has ever been saved for this bar."""
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    others = [s for s in screens if s is not primary]
    target = others[0] if others else primary
    geo = target.geometry()
    return geo.x() + 100, geo.y() + 100


class _ThrottleBar(QWidget):
    """The floating bar itself — a standalone, always-on-top, frameless
    widget the card only controls (position/size/colors), same separation
    Crosshair already uses between its card and its reticle overlay.

    Unlike ThrottleWatch's Tk version, this needs only one window: Qt's
    WA_TranslucentBackground gives real per-pixel alpha compositing, so the
    same paintEvent draws the semi-transparent background panel AND the
    ticks/track/knob — no second window, no transparent-color-key, no
    Win32 SetWindowRgn panel-shaping hack.
    """

    def __init__(self, module: "ThrottleController"):
        super().__init__()
        self._module = module
        self.value = 0.0
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_offset = None
        self._resize_start = None  # (mouse_x, mouse_y, start_w, start_h)
        s = module.settings
        self.setGeometry(s["x"], s["y"], s["width"], s["height"])
        self.set_click_through(s["click_through"])

    def set_click_through(self, enabled: bool):
        """Toggles real OS-level click-through via the WS_EX_TRANSPARENT
        extended window style, set directly through Win32 rather than
        relying on Qt's WA_TransparentForMouseEvents attribute alone.

        WA_TransparentForMouseEvents is what Crosshair's reticle uses, but
        that reticle sets it once at construction and never changes it —
        here the user reported it doing nothing when *toggled* on an
        already-shown window: Qt only reliably pushes that attribute down
        into the native window's extended style at window-creation time,
        not on every later setAttribute() call on some Qt/Windows
        combinations, so a live toggle on an already-visible top-level
        widget can silently no-op. Setting the WS_EX_TRANSPARENT bit
        directly (same class of direct-Win32-API fix as this app's other
        window-shape/behavior code, e.g. host/hotkey.py's GetAsyncKeyState
        watchdog) takes effect immediately regardless of when the window
        was created — Windows checks this bit on every hit-test, live.
        """
        if _user32 is not None:
            hwnd = int(self.winId())
            style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TRANSPARENT) if enabled else (style & ~WS_EX_TRANSPARENT)
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        # Also keep Qt's own notion of this in sync (harmless, and avoids
        # Qt fighting the bit back on some future internal window-flag
        # update triggered by, say, a resize/orientation swap).
        self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)
        # Dragging/resizing is exactly what click-through disables — clear
        # any in-progress gesture so a stale offset doesn't jump the bar
        # the moment click-through is switched off again mid-drag.
        self._drag_offset = None
        self._resize_start = None

    # -- geometry persistence ------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.RightButton:
            self._resize_start = (
                event.globalPosition().x(),
                event.globalPosition().y(),
                self.width(),
                self.height(),
            )

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        elif self._resize_start is not None:
            sx, sy, sw, sh = self._resize_start
            dw = event.globalPosition().x() - sx
            dh = event.globalPosition().y() - sy
            new_w = max(MIN_BAR_WIDTH, round(sw + dw))
            new_h = max(MIN_BAR_HEIGHT, round(sh + dh))
            self.resize(new_w, new_h)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._module.on_bar_moved(self.x(), self.y())
        elif event.button() == Qt.RightButton and self._resize_start is not None:
            self._resize_start = None
            self._module.on_bar_resized(self.width(), self.height())

    # -- drawing --------------------------------------------------------
    def paintEvent(self, event):
        s = self._module.settings
        w, h = self.width(), self.height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # See host/main_window.py's paintEvent for why Source composition +
        # an explicit transparent clear matters here: without it, pixels
        # cut off by the rounded corners keep stale backing-store garbage
        # instead of being genuinely see-through.
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        bg_color = QColor(s["bg_color"])
        bg_color.setAlphaF(s["bg_opacity"])
        radius = panel_radius_for(w, h)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        painter.fillPath(bg_path, bg_color)

        painter.setOpacity(s["line_opacity"])
        vertical = s["orientation"] != "horizontal"
        length = h if vertical else w
        thickness = w if vertical else h

        def to_xy(along, cross):
            return (cross, along) if vertical else (along, cross)

        def rect_from_ac(along0, cross0, along1, cross1):
            x0, y0 = to_xy(along0, cross0)
            x1, y1 = to_xy(along1, cross1)
            return QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

        line_color = s["line_color"]
        dim = dim_color(line_color)
        cross0, cross1 = TRACK_MARGIN, thickness - TRACK_MARGIN

        # Track outline — rounded with the panel's own radius (not a
        # smaller fixed one) since its ends reach the same along=0/length
        # extremes the panel itself curves at.
        painter.setPen(QPen(QColor(dim), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect_from_ac(0, cross0, length, cross1), radius, radius)

        # Center line (full length, across the middle of the thickness).
        mid_cross = thickness / 2
        x0, y0 = to_xy(0, mid_cross)
        x1, y1 = to_xy(length, mid_cross)
        painter.setPen(QPen(QColor(dim), 2))
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        # Tick marks — skipped near the two ends when they'd fall inside
        # the panel's own rounded corner, so an outward-reaching tick line
        # doesn't poke straight through where the panel curves away.
        for i in range(TICK_COUNT + 1):
            along = i / TICK_COUNT * length
            if along < radius or along > length - radius:
                continue
            is_major = abs(along - length / 2) < 2
            tick_len = TRACK_MARGIN - 2 if is_major else TRACK_MARGIN - 5
            pen_w = 2 if is_major else 1
            color = line_color if is_major else dim
            painter.setPen(QPen(QColor(color), pen_w))
            ax0, ay0 = to_xy(along, cross0 - tick_len)
            ax1, ay1 = to_xy(along, cross0)
            painter.drawLine(QPointF(ax0, ay0), QPointF(ax1, ay1))
            bx0, by0 = to_xy(along, cross1)
            bx1, by1 = to_xy(along, cross1 + tick_len)
            painter.drawLine(QPointF(bx0, by0), QPointF(bx1, by1))

        # Detents (v1 addition): thin full-width marker lines.
        for key in ("detent_1", "detent_2"):
            d = s.get(key)
            if d is None:
                continue
            along = (d + 1.0) / 2.0 * length
            painter.setPen(QPen(QColor(theme.ACCENT_AMBER), 2))
            dx0, dy0 = to_xy(along, cross0 - 6)
            dx1, dy1 = to_xy(along, cross1 + 6)
            painter.drawLine(QPointF(dx0, dy0), QPointF(dx1, dy1))

        # Knob.
        half = KNOB_POP_HALF_THICKNESS if self._module.is_home_flashing() else KNOB_HALF_THICKNESS
        pos_along = (self.value + 1.0) / 2.0 * length
        knob_color = value_to_color(abs(self.value), line_color)
        painter.setPen(QPen(QColor(s["bg_color"]), 1))
        painter.setBrush(QColor(knob_color))
        painter.drawRoundedRect(
            rect_from_ac(pos_along - half, cross0 - 4, pos_along + half, cross1 + 4),
            theme.RADIUS,
            theme.RADIUS,
        )
        hx0, hy0 = to_xy(pos_along - half + 2, cross0 - 2)
        hx1, hy1 = to_xy(pos_along - half + 2, cross1 + 2)
        painter.setPen(QPen(QColor(KNOB_HIGHLIGHT), 1))
        painter.drawLine(QPointF(hx0, hy0), QPointF(hx1, hy1))
        painter.end()

    def set_value(self, value: float):
        # Lightweight: only repaint when the axis actually moved.
        if value == self.value:
            return
        self.value = value
        self.update()

    def apply_orientation_swap(self):
        s = self._module.settings
        s["width"], s["height"] = s["height"], s["width"]
        self.resize(s["width"], s["height"])
