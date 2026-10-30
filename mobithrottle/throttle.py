"""mobiThrottle core: the floating throttle-axis bar + its settings controls.

Ported from mobiOverlay's modules/mobi_throttle/module.py (commit 55532f3).
The floating _ThrottleBar, chirp, joystick (re)connect logic and every card
control are carried over as-is; only the ModuleBase/card plumbing was
replaced by ThrottleController + build_settings() (hosted by
settings_window.SettingsWindow). v1 additions: detents and auto-detect.
Passive HID reads only — never touches any game process.
"""

import ctypes
import io
import math
import struct
import sys
import time
import wave

import pygame  # provided by the pygame-ce package (see requirements.txt)
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QWidget,
)

from . import theme
from .hotkey import GlobalHotkey

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
HOME_TICK_FREQ = 1400
HOME_TICK_MS = 45
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


_chirp_sound = None  # lazily-initialized pygame.mixer.Sound


def _generate_chirp_wav(freq_hz: int = 1400, duration_ms: int = 45, volume: float = 0.3) -> bytes:
    """Generates a short sine-wave chirp as an in-memory WAV file.
    Uses pygame.mixer for playback (routes through WASAPI shared-mode on
    Windows), which keeps audio working even when a game has exclusive
    focus — unlike winsound.Beep which uses the legacy PC speaker and
    silently fails in that scenario."""
    sample_rate = 22050
    n_samples = int(sample_rate * duration_ms / 1000)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        fade = 1.0
        fade_samples = int(0.005 * sample_rate)
        if i < fade_samples:
            fade = i / fade_samples
        elif i > n_samples - fade_samples:
            fade = (n_samples - i) / fade_samples
        val = math.sin(2 * math.pi * freq_hz * t) * volume * fade
        samples.append(int(val * 32767))

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f'<{len(samples)}h', *samples))
    return buf.getvalue()


def _init_chirp_sound():
    """Lazily initialize the pygame mixer and chirp sound once."""
    global _chirp_sound
    if _chirp_sound is not None:
        return True
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        wav_data = _generate_chirp_wav(HOME_TICK_FREQ, HOME_TICK_MS, volume=0.35)
        _chirp_sound = pygame.mixer.Sound(io.BytesIO(wav_data))
        return True
    except Exception:
        return False


def play_home_tick(count: int):
    """Plays the home-chirp sound `count` times with brief gaps between.
    Non-blocking: schedules playback via pygame.mixer channels, which mix
    and play asynchronously. Falls back gracefully (silent) if mixer fails."""
    if count <= 0:
        return
    if not _init_chirp_sound():
        return

    gap_ms = 60
    chirp_ms = HOME_TICK_MS
    for i in range(count):
        delay = i * (chirp_ms + gap_ms)
        QTimer.singleShot(delay, lambda: _chirp_sound.play() if _chirp_sound else None)


class _Joysticks:
    """Single owner of every pygame Joystick object.

    Crash fix (2026-10-30): the old code called pygame.joystick.quit()/init()
    on every rescan, Refresh, Apply and Detect while the controller's 60 Hz
    _poll still held (and read) a Joystick from before the re-init. SDL frees
    the device on quit; a later get_axis on the stale handle is a
    use-after-free -> 0xc0000005 in python314.dll. Now the subsystem is
    initialised exactly once and never quit while the app runs; devices are
    opened once and tracked by SDL instance id via JOYDEVICEADDED/REMOVED.
    pump() is the only place the event queue is pumped/drained."""

    def __init__(self):
        self.devices = {}  # instance_id -> Joystick
        self.changed = False

    def ensure(self):
        if not pygame.joystick.get_init():
            pygame.joystick.init()
            for i in range(pygame.joystick.get_count()):
                self._open(i)
            # init posts ADDED for devices already present; we just opened them.
            pygame.event.pump()
            pygame.event.clear(pygame.JOYDEVICEADDED)

    def _open(self, index):
        try:
            j = pygame.joystick.Joystick(index)
            self.devices[j.get_instance_id()] = j
            self.changed = True
        except Exception:
            pass

    def pump(self):
        """Pump SDL once and apply hot-plug events. Returns True if the
        device set changed since the last call."""
        self.ensure()
        pygame.event.pump()
        for e in pygame.event.get((pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED)):
            if e.type == pygame.JOYDEVICEADDED:
                self._open(e.device_index)
            else:
                self.devices.pop(getattr(e, "instance_id", None), None)
                self.changed = True
        changed, self.changed = self.changed, False
        return changed

    def listing(self):
        self.ensure()
        out = []
        for iid, j in sorted(self.devices.items()):
            try:
                guid = j.get_guid()
            except AttributeError:  # pragma: no cover
                guid = None
            out.append(
                {"index": iid, "name": j.get_name(), "guid": guid, "numaxes": j.get_numaxes(), "joy": j}
            )
        return out


JOYSTICKS = _Joysticks()


def list_joysticks():
    return [{k: v for k, v in d.items() if k != "joy"} for d in JOYSTICKS.listing()]


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


def find_joystick(device_guid, reinit=True):
    """Configured device by saved GUID, else first device with an axis.
    `reinit` is ignored (kept for API compatibility) — see _Joysticks."""
    for d in JOYSTICKS.listing():
        if device_guid:
            if d["guid"] == device_guid:
                return d["joy"]
        elif d["numaxes"] > 0:
            return d["joy"]
    return None


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


_TOGGLE_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_CYAN}; border-radius: {theme.RADIUS}px; padding: 6px 0;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px; letter-spacing: 1px;
    }}
    QPushButton:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
"""
_SMALL_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 3px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
    }}
    QPushButton:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
"""
_HEADER_LABEL_STYLE = theme.text_style(10, color=theme.ACCENT_CYAN, family=theme.FONT_DISPLAY, weight=700)
_LABEL_STYLE = theme.text_style(9, color=theme.TEXT_MUTED)
_STATUS_STYLE = theme.text_style(9, color=theme.TEXT_PRIMARY)
_COMBO_STYLE = theme.field_style('QComboBox', theme.TEXT_PRIMARY, 9, padding='3px 18px 3px 6px', drop_down=16)
_STEPPER_BTN_STYLE = f"""
    QPushButton {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(13)}px; font-weight: 700;
        padding: 0;
    }}
    QPushButton:hover {{ background: {theme.ACCENT_CYAN_DIM}; }}
    QPushButton:pressed {{ background: {theme.ACCENT_CYAN}; color: {theme.BG_VOID}; }}
"""
_STEPPER_VALUE_STYLE = f"""
    color: {theme.TEXT_PRIMARY}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(10)}px;
    background: {theme.BG_VOID}; border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px;
"""
_CHECK_STYLE = f'color: {theme.TEXT_MUTED}; font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;'
_HOTKEY_FIELD_STYLE = f"""
    QLineEdit {{
        background: {theme.BG_VOID}; color: {theme.ACCENT_CYAN};
        border: 1px solid {theme.BORDER_FLAT}; border-radius: {theme.RADIUS}px; padding: 4px 6px;
        font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;
    }}
"""


def _section_header(text):
    label = QLabel(text)
    label.setStyleSheet(_HEADER_LABEL_STYLE)
    return label


def _hline():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"background: {theme.BORDER_FLAT}; max-height: 1px; border: none;")
    return line


class _Stepper(QWidget):
    """A value with big [-]/[+] buttons instead of a QSpinBox's native
    up/down arrows — those arrows are tiny (a handful of px tall,
    typically shorter than half the field height) and hard to hit
    reliably, reported directly by the user after the card shipped with
    QSpinBox/QDoubleSpinBox everywhere. These buttons are full-size,
    themed, and impossible to miss."""

    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, step: float, value: float, decimals: int = 0):
        super().__init__()
        self._min, self._max, self._step, self._decimals = minimum, maximum, step, decimals
        self._value = value

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.minus_btn = QPushButton("−")
        self.minus_btn.setStyleSheet(_STEPPER_BTN_STYLE)
        self.minus_btn.setFixedSize(26, 24)
        self.minus_btn.clicked.connect(lambda: self._step_by(-1))
        layout.addWidget(self.minus_btn)

        self.value_label = QLabel()
        self.value_label.setStyleSheet(_STEPPER_VALUE_STYLE)
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFixedSize(44, 24)
        layout.addWidget(self.value_label)

        self.plus_btn = QPushButton("+")
        self.plus_btn.setStyleSheet(_STEPPER_BTN_STYLE)
        self.plus_btn.setFixedSize(26, 24)
        self.plus_btn.clicked.connect(lambda: self._step_by(1))
        layout.addWidget(self.plus_btn)

        self._render()

    def _step_by(self, direction: int):
        self.setValue(self._value + direction * self._step)

    def _render(self):
        text = f"{self._value:.{self._decimals}f}" if self._decimals else str(int(round(self._value)))
        self.value_label.setText(text)

    def value(self):
        return int(round(self._value)) if self._decimals == 0 else round(self._value, self._decimals)

    def setValue(self, value: float, emit: bool = True):
        clamped = max(self._min, min(self._max, value))
        clamped = round(clamped, self._decimals) if self._decimals else round(clamped)
        if clamped == self._value:
            self._render()
            return
        self._value = clamped
        self._render()
        if emit:
            self.valueChanged.emit(self._value)


class _HotkeyField(QLineEdit):
    """Click, then press a key combo — captured via the module's own
    GlobalHotkey.capture_combo(), same pattern as main_window.py's
    _HotkeyField for the app-wide Stow/Deploy hotkey."""

    def __init__(self, hotkey: GlobalHotkey, initial_display: str, on_applied):
        super().__init__()
        self._hotkey = hotkey
        self._on_applied = on_applied
        self._capturing = False
        self._capture_handles = []  # keeps in-flight capture signal-holders alive
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(_HOTKEY_FIELD_STYLE)
        self._current_display = initial_display
        self.setText(initial_display or "Click to set…")

    def mousePressEvent(self, event):
        if self._capturing:
            return
        self._capturing = True
        self.setText("Press keys...")
        handle = self._hotkey.capture_combo(self._on_captured, self._on_capture_failed)
        self._capture_handles.append(handle)

    def _on_captured(self, combo):
        self._capturing = False
        if not combo or combo.lower() == "esc":
            # Escape cancels rather than becoming the hotkey, same as the
            # host's Stow/Deploy field.
            self.setText(self._current_display or "Click to set…")
            return
        self._current_display = combo
        self.setText(combo)
        self._on_applied(combo)

    def _on_capture_failed(self, _message):
        self._capturing = False
        self.setText(self._current_display or "Click to set…")


class ThrottleController(QObject):
    """Owns the bar, the poll/reconnect timers, hotkeys and settings —
    replaces mobiOverlay's ModuleBase subclass. build_settings() populates
    any QVBoxLayout with exactly the controls the overlay card had."""

    bar_visibility_changed = Signal(bool)
    click_through_changed = Signal(bool)

    module_id = "mobi_throttle"
    display_name = (
        f'<span style="color:{theme.TEXT_PRIMARY};">mobi</span>'
        f'<span style="color:{theme.ACCENT_CYAN};">Throttle</span>'
    )

    DEFAULTS = {
        "device_guid": None,
        "device_name": None,
        "axis_index": 0,
        "axis_reverse": False,
        "orientation": "vertical",
        "width": 60,
        "height": 260,
        "bg_color": theme.BG_PANEL,
        "line_color": theme.ACCENT_CYAN,
        "bg_opacity": 0.85,
        "line_opacity": 1.0,
        "bar_visible": True,
        "click_through": False,
        "home_chirp_enabled": True,
        "home_chirp_count": 1,
        "home_chirp_cooldown": 2.0,
        "position_1": None,
        "position_2": None,
        "position_1_enabled": True,
        "position_2_enabled": True,
        # No hotkeys by default: GlobalHotkey only installs its low-level
        # keyboard hook once a combo is set, so a user who never sets one
        # (most users, with no throttle at all) never gets a hook from this
        # module. Existing installs keep whatever combo is already saved.
        "toggle_hotkey": "",
        "toggle_hotkey_display": "",
        "position_hotkey": "",
        "position_hotkey_display": "",
        "position_hold_ms": 0,
        # Reconnect-check cadence — decoupled from the bar's own 60Hz poll
        # timer (see refresh()); much shorter than the host's 300s default
        # so plugging the device back in doesn't take minutes to notice.
        "refresh_interval_seconds": 5,
        # v1 additions (not in the overlay module). Detents are axis values
        # in -1..1, None = not set; chirping on a detent crossing is opt-in.
        "detent_1": None,
        "detent_2": None,
        "detent_1_chirp": False,
        "detent_2_chirp": False,
    }

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.settings = config.settings
        for key, value in self.DEFAULTS.items():
            self.settings.setdefault(key, value)
        if "x" not in self.settings or "y" not in self.settings:
            self.settings["x"], self.settings["y"] = _default_bar_position()
        self.first_run = not self.settings.get("device_guid") and not config.existed
        self.request_refresh = self._reconnect_tick
        self._settings_parent = None
        self.status_label = None
        self._detector = None
        self._prev_value = 0.0

        if not pygame.get_init():
            pygame.init()

        self._device = None
        self._prev_in_home = True
        self._last_chirp_time = 0.0
        self._flash_until = 0.0
        self._position_index = 0
        self._device_list = []

        self._bar = _ThrottleBar(self)
        self._bar.setVisible(self.settings["bar_visible"])

        self._toggle_hotkey = GlobalHotkey()
        self._position_hotkey = GlobalHotkey()
        self._apply_hotkeys()

        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(int(1000 / AXIS_POLL_HZ))

        # Reconnect check, decoupled from the 60 Hz poll (what the overlay
        # host's refresh cycle did for the module).
        self._reconnect_timer = QTimer()
        self._reconnect_timer.timeout.connect(self._reconnect_tick)
        self._reconnect_timer.start(max(1, int(self.settings["refresh_interval_seconds"])) * 1000)
        QTimer.singleShot(0, self._reconnect_tick)

    def _set_status(self, text):
        if self.status_label is not None:
            self.status_label.setText(text)

    def _reconnect_tick(self):
        try:
            self.refresh()
        except RuntimeError as exc:
            self._set_status(str(exc))

    # -- persistence ------------------------------------------------------
    def _save(self):
        self.config.save()

    # -- card ---------------------------------------------------------
    def build_settings(self, layout, parent=None):
        """Same controls/styling as the overlay module's create_card()."""
        self._settings_parent = parent

        self.status_label = QLabel(RECONNECT_STATUS_UNAVAILABLE)
        self.status_label.setStyleSheet(_STATUS_STYLE)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setStyleSheet(_TOGGLE_BTN_STYLE)
        self.toggle_btn.clicked.connect(self._on_toggle_bar_clicked)
        layout.addWidget(self.toggle_btn)
        self._update_toggle_btn_text()

        self.click_through_check = QCheckBox("Click-through (disable drag/resize)")
        self.click_through_check.setStyleSheet(_CHECK_STYLE)
        self.click_through_check.setChecked(self.settings["click_through"])
        self.click_through_check.toggled.connect(self._on_click_through_toggled)
        layout.addWidget(self.click_through_check)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("DEVICE"))

        device_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setStyleSheet(_COMBO_STYLE)
        device_row.addWidget(self.device_combo, 1)
        refresh_devices_btn = QPushButton("Refresh")
        refresh_devices_btn.setStyleSheet(_SMALL_BTN_STYLE)
        refresh_devices_btn.clicked.connect(self._refresh_device_list)
        device_row.addWidget(refresh_devices_btn)
        self.detect_btn = QPushButton("Detect")
        self.detect_btn.setStyleSheet(_SMALL_BTN_STYLE)
        self.detect_btn.setToolTip(
            "Move your throttle through its range for ~3 s; picks the device + axis that moved most"
        )
        self.detect_btn.clicked.connect(self.start_detect)
        device_row.addWidget(self.detect_btn)
        layout.addLayout(device_row)

        axis_row = QHBoxLayout()
        axis_row.addWidget(self._label("Axis:"))
        self.axis_spin = _Stepper(0, 15, 1, self.settings["axis_index"])
        axis_row.addWidget(self.axis_spin)
        self.axis_reverse_check = QCheckBox("Reverse")
        self.axis_reverse_check.setStyleSheet(_CHECK_STYLE)
        self.axis_reverse_check.setChecked(self.settings["axis_reverse"])
        axis_row.addWidget(self.axis_reverse_check)
        axis_row.addStretch()
        layout.addLayout(axis_row)

        apply_device_btn = QPushButton("APPLY DEVICE")
        apply_device_btn.setStyleSheet(_TOGGLE_BTN_STYLE)
        apply_device_btn.clicked.connect(self._on_apply_device_clicked)
        layout.addWidget(apply_device_btn)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("APPEARANCE"))

        orientation_row = QHBoxLayout()
        orientation_row.addWidget(self._label("Orientation:"))
        self.orientation_combo = QComboBox()
        self.orientation_combo.setStyleSheet(_COMBO_STYLE)
        self.orientation_combo.addItems(["Vertical", "Horizontal"])
        self.orientation_combo.setCurrentText(
            "Horizontal" if self.settings["orientation"] == "horizontal" else "Vertical"
        )
        self.orientation_combo.currentTextChanged.connect(self._on_orientation_changed)
        orientation_row.addWidget(self.orientation_combo, 1)
        layout.addLayout(orientation_row)

        layout.addWidget(self._label("Background opacity:"))
        self.bg_opacity_slider = self._opacity_slider(
            self.settings["bg_opacity"], self._on_bg_opacity_changed
        )
        layout.addWidget(self.bg_opacity_slider)

        layout.addWidget(self._label("Line opacity:"))
        self.line_opacity_slider = self._opacity_slider(
            self.settings["line_opacity"], self._on_line_opacity_changed
        )
        layout.addWidget(self.line_opacity_slider)

        colors_row = QHBoxLayout()
        self.line_color_btn = self._color_button(self.settings["line_color"], self._on_pick_line_color)
        colors_row.addWidget(self._label("Line"))
        colors_row.addWidget(self.line_color_btn)
        self.bg_color_btn = self._color_button(self.settings["bg_color"], self._on_pick_bg_color)
        colors_row.addWidget(self._label("Background"))
        colors_row.addWidget(self.bg_color_btn)
        colors_row.addStretch()
        layout.addLayout(colors_row)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("HOTKEYS"))

        toggle_hotkey_row = QHBoxLayout()
        toggle_hotkey_row.addWidget(self._label("Toggle bar:"))
        self.toggle_hotkey_field = _HotkeyField(
            self._toggle_hotkey, self.settings["toggle_hotkey_display"], self._on_toggle_hotkey_applied
        )
        toggle_hotkey_row.addWidget(self.toggle_hotkey_field, 1)
        layout.addLayout(toggle_hotkey_row)

        pos_hotkey_row = QHBoxLayout()
        pos_hotkey_row.addWidget(self._label("Toggle position:"))
        self.position_hotkey_field = _HotkeyField(
            self._position_hotkey, self.settings["position_hotkey_display"], self._on_position_hotkey_applied
        )
        pos_hotkey_row.addWidget(self.position_hotkey_field, 1)
        layout.addLayout(pos_hotkey_row)

        hold_row = QHBoxLayout()
        hold_row.addWidget(self._label("Hold time (ms):"))
        self.hold_ms_spin = _Stepper(0, 5000, 50, self.settings["position_hold_ms"])
        self.hold_ms_spin.valueChanged.connect(self._on_hold_ms_changed)
        hold_row.addWidget(self.hold_ms_spin)
        hold_row.addStretch()
        layout.addLayout(hold_row)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("POSITIONS"))

        grid = QGridLayout()
        grid.addWidget(self._label("SCM Mode:"), 0, 0)
        scm_set = QPushButton("Set")
        scm_set.setStyleSheet(_SMALL_BTN_STYLE)
        scm_set.clicked.connect(lambda: self._save_position("position_1"))
        grid.addWidget(scm_set, 0, 1)
        scm_go = QPushButton("Go")
        scm_go.setStyleSheet(_SMALL_BTN_STYLE)
        scm_go.clicked.connect(lambda: self._go_to_position("position_1", 0))
        grid.addWidget(scm_go, 0, 2)
        self.scm_enabled_check = QCheckBox("Enabled")
        self.scm_enabled_check.setStyleSheet(_CHECK_STYLE)
        self.scm_enabled_check.setChecked(self.settings["position_1_enabled"])
        self.scm_enabled_check.toggled.connect(
            lambda v: self._on_position_enabled_toggled("position_1_enabled", v)
        )
        grid.addWidget(self.scm_enabled_check, 0, 3)

        grid.addWidget(self._label("NAV Mode:"), 1, 0)
        nav_set = QPushButton("Set")
        nav_set.setStyleSheet(_SMALL_BTN_STYLE)
        nav_set.clicked.connect(lambda: self._save_position("position_2"))
        grid.addWidget(nav_set, 1, 1)
        nav_go = QPushButton("Go")
        nav_go.setStyleSheet(_SMALL_BTN_STYLE)
        nav_go.clicked.connect(lambda: self._go_to_position("position_2", 1))
        grid.addWidget(nav_go, 1, 2)
        self.nav_enabled_check = QCheckBox("Enabled")
        self.nav_enabled_check.setStyleSheet(_CHECK_STYLE)
        self.nav_enabled_check.setChecked(self.settings["position_2_enabled"])
        self.nav_enabled_check.toggled.connect(
            lambda v: self._on_position_enabled_toggled("position_2_enabled", v)
        )
        grid.addWidget(self.nav_enabled_check, 1, 3)
        layout.addLayout(grid)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("HOME CHIRP"))

        chirp_row = QHBoxLayout()
        self.chirp_enabled_check = QCheckBox("Enabled")
        self.chirp_enabled_check.setStyleSheet(_CHECK_STYLE)
        self.chirp_enabled_check.setChecked(self.settings["home_chirp_enabled"])
        self.chirp_enabled_check.toggled.connect(self._on_chirp_enabled_toggled)
        chirp_row.addWidget(self.chirp_enabled_check)
        chirp_row.addWidget(self._label("Beeps:"))
        self.chirp_count_spin = _Stepper(1, 10, 1, self.settings["home_chirp_count"])
        self.chirp_count_spin.valueChanged.connect(self._on_chirp_count_changed)
        chirp_row.addWidget(self.chirp_count_spin)
        layout.addLayout(chirp_row)

        cooldown_row = QHBoxLayout()
        cooldown_row.addWidget(self._label("Cooldown (s):"))
        self.cooldown_spin = _Stepper(0.0, 10.0, 0.5, self.settings["home_chirp_cooldown"], decimals=1)
        self.cooldown_spin.valueChanged.connect(self._on_cooldown_changed)
        cooldown_row.addWidget(self.cooldown_spin)
        cooldown_row.addStretch()
        layout.addLayout(cooldown_row)

        layout.addWidget(_hline())
        layout.addWidget(_section_header("DETENTS"))
        self._detent_widgets = {}
        for n in (1, 2):
            key = f"detent_{n}"
            row = QHBoxLayout()
            row.addWidget(self._label(f"Detent {n}:"))
            value_label = self._label("")
            value_label.setMinimumWidth(40)
            row.addWidget(value_label)
            set_btn = QPushButton("Set")
            set_btn.setStyleSheet(_SMALL_BTN_STYLE)
            set_btn.setToolTip("Mark the current throttle position")
            set_btn.clicked.connect(lambda _=False, k=key: self._set_detent(k))
            row.addWidget(set_btn)
            clr_btn = QPushButton("Clear")
            clr_btn.setStyleSheet(_SMALL_BTN_STYLE)
            clr_btn.clicked.connect(lambda _=False, k=key: self._clear_detent(k))
            row.addWidget(clr_btn)
            chirp = QCheckBox("Chirp")
            chirp.setStyleSheet(_CHECK_STYLE)
            chirp.setChecked(bool(self.settings[f"{key}_chirp"]))
            chirp.toggled.connect(lambda v, k=key: self._on_detent_chirp_toggled(k, v))
            row.addWidget(chirp)
            row.addStretch()
            layout.addLayout(row)
            self._detent_widgets[key] = value_label
        self._render_detents()

        self._refresh_device_list()
        if self._device is not None:
            self._set_status(f"Connected: {self.settings['device_name']}")

    def _label(self, text):
        label = QLabel(text)
        label.setStyleSheet(_LABEL_STYLE)
        return label

    def _opacity_slider(self, initial, on_changed):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(round(initial * 100))
        slider.valueChanged.connect(on_changed)
        return slider

    def _color_button(self, hex_color, on_clicked):
        btn = QPushButton()
        btn.setFixedSize(28, 20)
        btn.setStyleSheet(
            f"background: {hex_color}; border: 1px solid {theme.BORDER_FLAT}; border-radius: 4px;"
        )
        btn.clicked.connect(on_clicked)
        return btn

    # -- device -----------------------------------------------------
    def _refresh_device_list(self):
        self._device_list = list_joysticks()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("Auto (first detected)")
        selected = 0
        current_guid = self.settings.get("device_guid")
        for i, d in enumerate(self._device_list, start=1):
            self.device_combo.addItem(f"[{d['index']}] {d['name']} ({d['numaxes']} axes)")
            if current_guid and d["guid"] == current_guid:
                selected = i
        self.device_combo.setCurrentIndex(selected)
        self.device_combo.blockSignals(False)

    def _on_apply_device_clicked(self):
        selection = self.device_combo.currentIndex()
        axis = self.axis_spin.value()
        if selection <= 0:
            self.settings["device_guid"] = None
            self.settings["device_name"] = None
        else:
            entry = self._device_list[selection - 1]
            self.settings["device_guid"] = entry["guid"]
            self.settings["device_name"] = entry["name"]
            axis = min(axis, max(0, entry["numaxes"] - 1))
            self.axis_spin.setValue(axis)
        self.settings["axis_index"] = axis
        self.settings["axis_reverse"] = self.axis_reverse_check.isChecked()
        self._save()
        # Force an immediate reconnect against the new selection instead of
        # waiting for the next refresh_interval_seconds tick.
        self._device = None
        if self.request_refresh is not None:
            self.request_refresh()

    def _try_connect(self):
        # Cheap: device set is maintained by hot-plug events, no re-init.
        self._device = find_joystick(self.settings.get("device_guid"))
        if self._device is not None:
            self.settings["device_name"] = self._device.get_name()
            self._save()
            self._set_status(f"Connected: {self.settings['device_name']}")

    # -- polling / drawing ------------------------------------------------
    def _poll(self):
        try:
            if (
                JOYSTICKS.pump()
                and self._device is not None
                and self._device not in JOYSTICKS.devices.values()
            ):
                self._device = None  # unplugged: never touch its handle again
                self._set_status(RECONNECT_STATUS_UNAVAILABLE)
        except Exception:
            return
        if self._device is None or self._detector is not None:
            return
        try:
            raw = self._device.get_axis(self.settings["axis_index"])
        except Exception:
            # Force the next refresh()'s _try_connect to rescan instead of
            # sitting idle until JOYSTICK_RESCAN_SECONDS (stick still
            # plugged in after a transient HID read failure).
            self._device = None
            self._set_status(RECONNECT_STATUS_UNAVAILABLE)
            return
        value = -raw if self.settings["axis_reverse"] else raw
        self._bar.set_value(value)
        self._check_home_chirp(value)

    def _check_home_chirp(self, value):
        now = time.time()
        in_home = abs(value) < DEADZONE
        if in_home and not self._prev_in_home:
            self._flash_until = now + HOME_FLASH_DURATION
            # The bar only repaints on value changes now, so schedule the
            # pop-in and pop-out repaints of the home flash explicitly.
            self._bar.update()
            QTimer.singleShot(int(HOME_FLASH_DURATION * 1000) + 20, self._bar.update)
            if (
                self.settings["home_chirp_enabled"]
                and now - self._last_chirp_time >= self.settings["home_chirp_cooldown"]
            ):
                play_home_tick(self.settings["home_chirp_count"])
                self._last_chirp_time = now
        self._prev_in_home = in_home
        for key in ("detent_1", "detent_2"):
            pos = self.settings.get(key)
            if (
                pos is not None
                and self.settings.get(f"{key}_chirp")
                and detent_crossed(self._prev_value, value, pos)
            ):
                play_home_tick(1)
        self._prev_value = value

    def is_home_flashing(self):
        return time.time() < self._flash_until

    # -- bar geometry / visibility -----------------------------------------
    def on_bar_moved(self, x, y):
        self.settings["x"], self.settings["y"] = x, y
        self._save()

    def on_bar_resized(self, w, h):
        self.settings["width"], self.settings["height"] = w, h
        self._save()

    def _update_toggle_btn_text(self):
        self.toggle_btn.setText("HIDE BAR" if self.settings["bar_visible"] else "SHOW BAR")

    def _on_toggle_bar_clicked(self):
        self._set_bar_visible(not self.settings["bar_visible"])

    def _set_bar_visible(self, visible):
        self.settings["bar_visible"] = visible
        self._save()
        self._bar.setVisible(visible)
        if self.status_label is not None:
            self._update_toggle_btn_text()
        self.bar_visibility_changed.emit(visible)

    def _toggle_bar_visibility(self):
        # Called from the keyboard-hook thread via GlobalHotkey's Qt signal
        # marshaling — safe to touch Qt widgets here, same as the host's
        # own Stow/Deploy hotkey callback.
        self._set_bar_visible(not self.settings["bar_visible"])

    def _on_click_through_toggled(self, enabled):
        # Requested directly by the user: an accidental left-click-drag on
        # the bar mid-flight was moving it while playing. With this on,
        # every mouse event passes straight through to the game — the bar
        # can't be dragged or resized until it's switched back off.
        self.settings["click_through"] = enabled
        self._save()
        self._bar.set_click_through(enabled)
        self.click_through_changed.emit(enabled)

    def toggle_click_through(self):
        new = not self.settings["click_through"]
        if self.status_label is not None:
            self.click_through_check.setChecked(new)  # fires the handler
        else:
            self._on_click_through_toggled(new)

    def toggle_bar(self):
        self._set_bar_visible(not self.settings["bar_visible"])

    # -- orientation / appearance -------------------------------------------
    def _on_orientation_changed(self, text):
        new_orientation = "horizontal" if text == "Horizontal" else "vertical"
        if new_orientation == self.settings["orientation"]:
            return
        self.settings["orientation"] = new_orientation
        self._bar.apply_orientation_swap()
        self._save()

    def _on_bg_opacity_changed(self, value):
        self.settings["bg_opacity"] = value / 100
        self._save()
        self._bar.update()

    def _on_line_opacity_changed(self, value):
        self.settings["line_opacity"] = value / 100
        self._save()
        self._bar.update()

    def _on_pick_line_color(self):
        color = QColorDialog.getColor(
            QColor(self.settings["line_color"]), self._settings_parent, "Line color"
        )
        if color.isValid():
            self.settings["line_color"] = color.name()
            self.line_color_btn.setStyleSheet(
                f"background: {color.name()}; border: 1px solid {theme.BORDER_FLAT}; border-radius: 4px;"
            )
            self._save()
            self._bar.update()

    def _on_pick_bg_color(self):
        color = QColorDialog.getColor(
            QColor(self.settings["bg_color"]), self._settings_parent, "Background color"
        )
        if color.isValid():
            self.settings["bg_color"] = color.name()
            self.bg_color_btn.setStyleSheet(
                f"background: {color.name()}; border: 1px solid {theme.BORDER_FLAT}; border-radius: 4px;"
            )
            self._save()
            self._bar.update()

    # -- hotkeys ------------------------------------------------------
    def _apply_hotkeys(self):
        self._toggle_hotkey.set_hotkey(self.settings["toggle_hotkey"], self._toggle_hotkey_triggered)
        self._position_hotkey.set_hotkey(self.settings["position_hotkey"], self._position_hotkey_triggered)

    def _toggle_hotkey_triggered(self):
        self._toggle_bar_visibility()

    def _position_hotkey_triggered(self):
        self._toggle_position()

    def _on_toggle_hotkey_applied(self, combo):
        self.settings["toggle_hotkey"] = combo
        self.settings["toggle_hotkey_display"] = combo
        self._toggle_hotkey.set_hotkey(combo, self._toggle_hotkey_triggered)
        self._save()

    def _on_position_hotkey_applied(self, combo):
        self.settings["position_hotkey"] = combo
        self.settings["position_hotkey_display"] = combo
        self._position_hotkey.set_hotkey(combo, self._position_hotkey_triggered)
        self._save()

    def _on_hold_ms_changed(self, value):
        # GlobalHotkey doesn't support hold-to-trigger itself (the app-wide
        # Stow/Deploy hotkey never needed it) — held here and honored by
        # _toggle_position's own delay via a QTimer.singleShot instead of
        # extending the shared primitive for one caller.
        # int(): _Stepper.valueChanged is declared Signal(float), so Qt
        # coerces even a whole-number Python int to float on the way
        # through — cast back for a step-size setting that should stay int.
        self.settings["position_hold_ms"] = int(value)
        self._save()

    # -- positions ------------------------------------------------------
    def _save_position(self, key):
        self.settings[key] = {"x": self._bar.x(), "y": self._bar.y()}
        self._save()

    def _go_to_position(self, key, index):
        pos = self.settings.get(key)
        if pos is None:
            return
        self._bar.move(pos["x"], pos["y"])
        self.settings["x"], self.settings["y"] = pos["x"], pos["y"]
        self._save()
        self._position_index = index

    def _toggle_position(self):
        hold_ms = self.settings.get("position_hold_ms", 0)
        if hold_ms > 0:
            QTimer.singleShot(hold_ms, self._toggle_position_now)
        else:
            self._toggle_position_now()

    def _toggle_position_now(self):
        target_index = 1 - self._position_index
        key = "position_1" if target_index == 0 else "position_2"
        enabled_key = "position_1_enabled" if target_index == 0 else "position_2_enabled"
        if not self.settings.get(enabled_key, True):
            return  # the other position is disabled — nothing to toggle to
        self._go_to_position(key, target_index)

    def _on_position_enabled_toggled(self, key, value):
        other_key = "position_2_enabled" if key == "position_1_enabled" else "position_1_enabled"
        other_check = self.nav_enabled_check if key == "position_1_enabled" else self.scm_enabled_check
        if not value and not self.settings.get(other_key, True):
            # At least one position must always stay enabled.
            other_check.setChecked(True)
            self.settings[other_key] = True
        self.settings[key] = value
        self._save()

    # -- home chirp ------------------------------------------------------
    def _on_chirp_enabled_toggled(self, value):
        self.settings["home_chirp_enabled"] = value
        self._save()

    def _on_chirp_count_changed(self, value):
        # See _on_hold_ms_changed's comment — Signal(float) coerces int to
        # float in transit; cast back since this is a whole beep count.
        self.settings["home_chirp_count"] = int(value)
        self._save()

    def _on_cooldown_changed(self, value):
        self.settings["home_chirp_cooldown"] = round(value, 1)
        self._save()

    # -- module contract --------------------------------------------------
    def refresh(self):
        """Reconnect check only — the bar's own 60Hz poll timer (see
        __init__) drives the actual axis reads, decoupled from the host's
        refresh cycle. Raising here (no device found) puts this card into
        the host's normal error state with a Retry button, same as any
        other module's failed refresh."""
        if self._device is None:
            self._try_connect()
        if self._device is None:
            hint = self.settings.get("device_name") or "any joystick"
            raise RuntimeError(f"No device found ({hint}). Connect it, then Apply Device or Retry.")

    # -- detents (v1) ---------------------------------------------------
    def _render_detents(self):
        for key, label in getattr(self, "_detent_widgets", {}).items():
            v = self.settings.get(key)
            label.setText("—" if v is None else f"{v:+.2f}")

    def _set_detent(self, key):
        self.settings[key] = round(self._bar.value, 3)
        self._save()
        self._render_detents()
        self._bar.update()

    def _clear_detent(self, key):
        self.settings[key] = None
        self._save()
        self._render_detents()
        self._bar.update()

    def _on_detent_chirp_toggled(self, key, value):
        self.settings[f"{key}_chirp"] = bool(value)
        self._save()

    # -- auto-detect (v1) -------------------------------------------------
    def start_detect(self):
        if self._detector is not None:
            return
        self._set_status(
            "Move only your throttle through its range, then leave it away from where it started…"
        )
        if getattr(self, "detect_btn", None) is not None:
            self.detect_btn.setEnabled(False)
        self._detector = AxisDetector(self._on_detect_done)
        self._detector.start()

    def _on_detect_done(self, result):
        self._detector = None
        if getattr(self, "detect_btn", None) is not None:
            self.detect_btn.setEnabled(True)
        if result is None:
            self._set_status("No movement detected — try Detect again")
            return
        guid, name, axis = result
        self.settings["device_guid"] = guid
        self.settings["device_name"] = name
        self.settings["axis_index"] = axis
        self._save()
        if self.status_label is not None:
            self.axis_spin.setValue(axis, emit=False)
            self._refresh_device_list()
        self._device = None
        self._reconnect_tick()

    def shutdown(self):
        """Releases the two OS-level global keyboard hooks this module
        owns — required before a Relaunch spawns a new process, same
        reasoning as host/main_window.py's own Stow/Deploy hotkey (see
        ModuleBase.shutdown's docstring)."""
        self._poll_timer.stop()
        self._reconnect_timer.stop()
        if self._detector is not None:
            self._detector.cancel()
        self._toggle_hotkey.shutdown()
        self._position_hotkey.shutdown()


# -- pure helpers for v1 features (unit-tested) -----------------------------
DETECT_SECONDS = 3.0
DETECT_MIN_TRAVEL = 0.25  # an axis must sweep at least this much (of 2.0)


def detent_crossed(prev: float, cur: float, pos: float) -> bool:
    """True when the axis moved across (or onto) `pos` between two polls."""
    if prev == cur:
        return False
    lo, hi = (prev, cur) if prev < cur else (cur, prev)
    return lo < pos <= hi if cur > prev else lo <= pos < hi


DETECT_CENTER_BAND = 0.15  # |final - start| below this = sprang back


def pick_axis(ranges: dict, min_travel: float = DETECT_MIN_TRAVEL, ends: dict = None):
    """ranges: {key: (min_seen, max_seen)}; ends (optional): {key: (start, last)}.
    Prefers throttle-like axes: moved >= min_travel AND ended away from where
    it started (a throttle stays put; a sprung stick axis returns to its start).
    Falls back to the largest sweep only if no axis stayed put."""

    def best_of(keys):
        best, travel = None, min_travel
        for k in keys:
            lo, hi = ranges[k]
            if hi - lo > travel:
                best, travel = k, hi - lo
        return best

    if ends:
        stayed = [k for k in ranges if k in ends and abs(ends[k][1] - ends[k][0]) >= DETECT_CENTER_BAND]
        k = best_of(stayed)
        if k is not None:
            return k
    return best_of(ranges)


class AxisDetector(QObject):
    """Samples every axis for DETECT_SECONDS; reports (guid, name, axis) of
    the most throttle-like axis (see pick_axis), or None. Uses the shared
    Joystick objects; never re-inits pygame and never pumps events itself
    (the controller's poll timer pumps; it skips axis reads during detect)."""

    def __init__(self, on_done):
        super().__init__()
        self._on_done = on_done
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sample)
        self._ranges = {}
        self._ends = {}
        self._devices = {}
        self._started = 0.0

    def start(self):
        try:
            self._devices = {d["index"]: d["joy"] for d in JOYSTICKS.listing()}
        except Exception:
            self._devices = {}
        self._started = time.monotonic()
        self._timer.start(30)

    def _sample(self):
        live = set(JOYSTICKS.devices)
        for i, j in list(self._devices.items()):
            if i not in live:  # unplugged mid-detect: forget it
                self._devices.pop(i, None)
                continue
            try:
                for a in range(j.get_numaxes()):
                    v = j.get_axis(a)
                    lo, hi = self._ranges.get((i, a), (v, v))
                    self._ranges[(i, a)] = (min(lo, v), max(hi, v))
                    start = self._ends.get((i, a), (v, v))[0]
                    self._ends[(i, a)] = (start, v)
            except Exception:
                pass
        if time.monotonic() - self._started >= DETECT_SECONDS:
            self._finish()

    def _finish(self):
        self._timer.stop()
        key = pick_axis(self._ranges, ends=self._ends)
        result = None
        if key is not None and key[0] in self._devices:
            j = self._devices[key[0]]
            try:
                guid = j.get_guid()
            except AttributeError:
                guid = None
            result = (guid, j.get_name(), key[1])
        self._devices = {}
        self._on_done(result)

    def cancel(self):
        self._timer.stop()
