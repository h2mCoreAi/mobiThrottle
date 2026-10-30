"""First-run Setup Guide: a step-by-step wizard over the same settings the
settings window edits.

Apply-as-you-go: every control writes through ThrottleController (the same
setters/handlers the settings window uses) and saves immediately, so the bar
reacts live. Cancel just closes the guide; changes already made are kept.
Device reads go through the single shared _Joysticks owner (via the
controller and AxisDetector); the guide never touches pygame directly.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .devices import list_joysticks, play_home_tick
from .settings_window import build_card
from .throttle import ThrottleController
from .widgets import (
    _CHECK_STYLE,
    _COMBO_STYLE,
    _LABEL_STYLE,
    _SMALL_BTN_STYLE,
    _STATUS_STYLE,
    _TOGGLE_BTN_STYLE,
    _HotkeyField,
    _section_header,
    _Stepper,
)

LIVE_REFRESH_MS = 33
_EXPLAIN_STYLE = theme.text_style(10, color=theme.TEXT_PRIMARY)


class LiveBar(QWidget):
    """Small horizontal preview of the current axis value (-1..+1)."""

    def __init__(self, source: Callable[[], float]) -> None:
        super().__init__()
        self._source = source
        self.value = 0.0
        self.setFixedHeight(22)
        self.setMinimumWidth(220)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(LIVE_REFRESH_MS)

    def tick(self) -> None:
        try:
            v = float(self._source())
        except Exception:
            v = 0.0
        if v != self.value:
            self.value = v
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QColor(theme.BORDER_FLAT))
        p.setBrush(QColor(theme.BG_VOID))
        p.drawRoundedRect(r, 5, 5)
        mid = r.center().x()
        x = r.left() + (self.value + 1.0) / 2.0 * r.width()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT_CYAN_DIM))
        p.drawRect(int(min(mid, x)), r.top() + 3, int(abs(x - mid)), r.height() - 6)
        p.setBrush(QColor(theme.ACCENT_CYAN))
        p.drawRect(int(x) - 2, r.top() + 2, 4, r.height() - 4)
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawLine(mid, r.top() + 2, mid, r.bottom() - 2)


class _Step(QWidget):
    """One page: title, one-sentence explanation, then its controls."""

    title = ""
    explain = ""

    def __init__(self, guide: "SetupGuide") -> None:
        super().__init__()
        self.guide = guide
        self.ctl: ThrottleController = guide.controller
        self.s = self.ctl.settings
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        self.body.addWidget(_section_header(self.title.upper()))
        text = QLabel(self.explain)
        text.setWordWrap(True)
        text.setStyleSheet(_EXPLAIN_STYLE)
        self.body.addWidget(text)
        self.build()
        self.body.addStretch()

    def build(self) -> None:
        pass

    def entered(self) -> None:
        """Called each time the step becomes visible."""

    def label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_STYLE)
        lbl.setWordWrap(True)
        return lbl

    def button(self, text: str, slot, style: str = _SMALL_BTN_STYLE) -> QPushButton:
        b = QPushButton(text)
        b.setStyleSheet(style)
        b.clicked.connect(slot)
        return b

    def check(self, text: str, checked: bool, slot) -> QCheckBox:
        c = QCheckBox(text)
        c.setStyleSheet(_CHECK_STYLE)
        c.setChecked(bool(checked))
        c.toggled.connect(slot)
        return c

    def row(self, *widgets) -> QHBoxLayout:
        r = QHBoxLayout()
        for w in widgets:
            r.addWidget(w)
        r.addStretch()
        self.body.addLayout(r)
        return r


class WelcomeStep(_Step):
    title = "Welcome"
    explain = (
        "mobiThrottle shows your throttle position as a small always-on-top bar; "
        "this guide sets it up in about a minute, and every change applies as you go."
    )

    def build(self) -> None:
        self.body.addWidget(
            self.label(
                "Use Next and Back to move between steps, Skip to leave a step as it is, "
                "and Cancel to close the guide at any time (anything already set is kept). "
                "You can reopen it later from Settings → Setup guide."
            )
        )


class DeviceStep(_Step):
    title = "Device"
    explain = "Pick the controller your throttle is on; plug it in and press Refresh if it isn't listed."

    def build(self) -> None:
        self.combo = QComboBox()
        self.combo.setStyleSheet(_COMBO_STYLE)
        self.combo.activated.connect(self._apply)
        self.row(self.combo, self.button("Refresh", self.reload))
        self._devices: list[dict] = []

    def entered(self) -> None:
        self.reload()

    def reload(self) -> None:
        self._devices = list_joysticks()
        self.combo.clear()
        self.combo.addItem("Auto (first detected)")
        selected = 0
        for i, d in enumerate(self._devices, start=1):
            self.combo.addItem(f"{d['name']} ({d['numaxes']} axes)")
            if d["guid"] and d["guid"] == self.s.get("device_guid"):
                selected = i
        self.combo.setCurrentIndex(selected)

    def _apply(self, index: int) -> None:
        entry = self._devices[index - 1] if 0 < index <= len(self._devices) else None
        self.ctl.apply_device(entry, self.s["axis_index"], self.s["axis_reverse"])


class AxisStep(_Step):
    title = "Throttle axis"
    explain = (
        "Press Detect and move only your throttle through its range, then leave it away from "
        "where it started; or pick the axis by hand and watch the bar."
    )

    def build(self) -> None:
        self.detect_btn = self.button("Detect", self.detect, _TOGGLE_BTN_STYLE)
        self.body.addWidget(self.detect_btn)
        self.axis_combo = QComboBox()
        self.axis_combo.setStyleSheet(_COMBO_STYLE)
        self.axis_combo.activated.connect(self._apply_axis)
        self.row(self.label("Axis:"), self.axis_combo)
        self.live = LiveBar(lambda: self.ctl.current_value)
        self.body.addWidget(self.live)
        self.status = QLabel("")
        self.status.setStyleSheet(_STATUS_STYLE)
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.ctl.detect_finished.connect(self._on_detected)

    def entered(self) -> None:
        self._fill_axes()

    def _numaxes(self) -> int:
        for d in list_joysticks():
            if d["guid"] == self.s.get("device_guid"):
                return max(1, d["numaxes"])
        return 16

    def _fill_axes(self) -> None:
        self.axis_combo.clear()
        for a in range(self._numaxes()):
            self.axis_combo.addItem(f"Axis {a}")
        self.axis_combo.setCurrentIndex(min(self.s["axis_index"], self.axis_combo.count() - 1))

    def _apply_axis(self, index: int) -> None:
        entry = next((d for d in list_joysticks() if d["guid"] == self.s.get("device_guid")), None)
        self.ctl.apply_device(entry, index, self.s["axis_reverse"])

    def detect(self) -> None:
        self.detect_btn.setEnabled(False)
        self.status.setText("Move only your throttle now…")
        self.ctl.start_detect()

    def _on_detected(self, result) -> None:
        self.detect_btn.setEnabled(True)
        if result is None:
            self.status.setText("No movement detected — try Detect again, or pick the axis by hand.")
            return
        _guid, name, axis = result
        self.status.setText(f"Found: {name}, axis {axis}.")
        self._fill_axes()


class DirectionStep(_Step):
    title = "Direction"
    explain = "Push your throttle forward: does the bar move the way you expect? If not, tick Reverse."

    def build(self) -> None:
        self.live = LiveBar(lambda: self.ctl.current_value)
        self.body.addWidget(self.live)
        self.reverse = self.check("Reverse", self.s["axis_reverse"], self.ctl.set_axis_reverse)
        self.row(self.reverse)

    def entered(self) -> None:
        self.reverse.blockSignals(True)
        self.reverse.setChecked(self.s["axis_reverse"])
        self.reverse.blockSignals(False)


class LayoutStep(_Step):
    title = "Orientation & size"
    explain = "Choose a vertical or horizontal bar; drag the bar to move it and drag its edges to resize it."

    def build(self) -> None:
        self.combo = QComboBox()
        self.combo.setStyleSheet(_COMBO_STYLE)
        self.combo.addItems(["Vertical", "Horizontal"])
        self.combo.setCurrentText("Horizontal" if self.s["orientation"] == "horizontal" else "Vertical")
        self.combo.currentTextChanged.connect(self.ctl._on_orientation_changed)
        self.row(self.label("Orientation:"), self.combo)
        if not self.s["bar_visible"]:
            self.body.addWidget(self.button("Show bar", lambda: self.ctl._set_bar_visible(True)))


class ColorsStep(_Step):
    title = "Colors & opacity"
    explain = "Set the bar's line and background colors and how see-through each one is."

    def build(self) -> None:
        self.line_btn = self.button("Line color…", lambda: self._pick("line"))
        self.bg_btn = self.button("Background color…", lambda: self._pick("bg"))
        self.row(self.line_btn, self.bg_btn)
        self.body.addWidget(self.label("Line opacity:"))
        self.line_slider = self._slider(self.s["line_opacity"], self.ctl._on_line_opacity_changed)
        self.body.addWidget(self.line_slider)
        self.body.addWidget(self.label("Background opacity:"))
        self.bg_slider = self._slider(self.s["bg_opacity"], self.ctl._on_bg_opacity_changed)
        self.body.addWidget(self.bg_slider)
        self.centre_zero = self.check(
            "Centre-zero colours (indicator green above zero, red below)",
            self.s["centre_zero_colors"],
            self.ctl.set_centre_zero_colors,
        )
        self.body.addWidget(self.centre_zero)

    def _slider(self, initial: float, slot) -> QSlider:
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 100)
        sl.setValue(round(initial * 100))
        sl.valueChanged.connect(slot)
        return sl

    def _pick(self, which: str) -> None:
        color = QColorDialog.getColor(QColor(self.s[f"{which}_color"]), self, "Choose color")
        if color.isValid():
            getattr(self.ctl, f"set_{which}_color")(color.name())


class ChirpStep(_Step):
    title = "Home chirp"
    explain = "A short beep when the throttle returns to center (zero), so you can find it without looking."

    def build(self) -> None:
        self.enabled = self.check("Enabled", self.s["home_chirp_enabled"], self.ctl._on_chirp_enabled_toggled)
        self.count = _Stepper(1, 10, 1, self.s["home_chirp_count"])
        self.count.valueChanged.connect(self.ctl._on_chirp_count_changed)
        self.row(self.enabled, self.label("Beeps:"), self.count)
        self.body.addWidget(self.button("Test", lambda: play_home_tick(self.s["home_chirp_count"])))


class DetentsStep(_Step):
    title = "Detents (optional)"
    explain = "Mark up to two throttle positions (for example your afterburner gate) to show on the bar."

    def build(self) -> None:
        self.live = LiveBar(lambda: self.ctl.current_value)
        self.body.addWidget(self.live)
        self.values: dict[str, QLabel] = {}
        for n in (1, 2):
            key = f"detent_{n}"
            value = self.label("")
            value.setMinimumWidth(48)
            self.values[key] = value
            self.row(
                self.label(f"Detent {n}:"),
                value,
                self.button("Set here", lambda _=False, k=key: self._set(k)),
                self.button("Clear", lambda _=False, k=key: self._clear(k)),
                self.check(
                    "Chirp", self.s[f"{key}_chirp"], lambda v, k=key: self.ctl._on_detent_chirp_toggled(k, v)
                ),
            )
        self._render()

    def _set(self, key: str) -> None:
        self.ctl._set_detent(key)
        self._render()

    def _clear(self, key: str) -> None:
        self.ctl._clear_detent(key)
        self._render()

    def _render(self) -> None:
        for key, lbl in self.values.items():
            v = self.s.get(key)
            lbl.setText("—" if v is None else f"{v:+.2f}")


class HotkeysStep(_Step):
    title = "Hotkeys (optional)"
    explain = (
        "Optionally set keys to show/hide the bar and to swap its saved position; "
        "no keyboard hook is installed unless you set one."
    )

    def build(self) -> None:
        self.toggle_field = _HotkeyField(
            self.ctl._toggle_hotkey, self.s["toggle_hotkey_display"], self.ctl._on_toggle_hotkey_applied
        )
        self.row(self.label("Show/hide bar:"), self.toggle_field)
        self.position_field = _HotkeyField(
            self.ctl._position_hotkey, self.s["position_hotkey_display"], self.ctl._on_position_hotkey_applied
        )
        self.row(self.label("Swap position:"), self.position_field)
        self.body.addWidget(self.label("Click a field, press the keys, or press Esc to cancel."))


class ClickThroughStep(_Step):
    title = "Click-through"
    explain = (
        "Click-through lets mouse clicks pass through the bar so you can't move it by accident mid-flight."
    )

    def build(self) -> None:
        self.toggle = self.check(
            "Click-through (disable drag/resize)", self.s["click_through"], self.ctl._on_click_through_toggled
        )
        self.body.addWidget(self.toggle)
        self.body.addWidget(
            self.label(
                "To move the bar again later: click the mobiThrottle tray icon to open Settings "
                "and untick Click-through (or use the tray menu)."
            )
        )


class DoneStep(_Step):
    title = "All set"
    explain = "Here's what you set up; press Finish, and change anything later from the tray icon."

    def build(self) -> None:
        self.summary = QLabel("")
        self.summary.setStyleSheet(_STATUS_STYLE)
        self.summary.setWordWrap(True)
        self.body.addWidget(self.summary)

    def entered(self) -> None:
        s = self.s
        detents = [f"{s[k]:+.2f}" for k in ("detent_1", "detent_2") if s.get(k) is not None]
        lines = [
            f"Device: {s.get('device_name') or 'Auto (first detected)'}",
            f"Axis: {s['axis_index']}{' (reversed)' if s['axis_reverse'] else ''}",
            f"Bar: {s['orientation']}",
            f"Home chirp: {'on, ' + str(s['home_chirp_count']) + ' beep(s)' if s['home_chirp_enabled'] else 'off'}",
            f"Detents: {', '.join(detents) if detents else 'none'}",
            f"Hotkeys: {s['toggle_hotkey_display'] or '—'} / {s['position_hotkey_display'] or '—'}",
            f"Click-through: {'on' if s['click_through'] else 'off'}",
        ]
        self.summary.setText("\n".join(lines))


STEPS: tuple[type[_Step], ...] = (
    WelcomeStep,
    DeviceStep,
    AxisStep,
    DirectionStep,
    LayoutStep,
    ColorsStep,
    ChirpStep,
    DetentsStep,
    HotkeysStep,
    ClickThroughStep,
    DoneStep,
)


class SetupGuide(QWidget):
    """Wizard window. `finished` is emitted on Finish or Cancel (True = Finish)."""

    finished = Signal(bool)

    def __init__(self, controller: ThrottleController, icon=None) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("mobiThrottle — Setup guide")
        if icon is not None:
            self.setWindowIcon(icon)
        self.setStyleSheet(f"SetupGuide {{ background: {theme.BG_VOID}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        card, card_layout = build_card(controller.display_name)
        outer.addWidget(card)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 10, 14, 12)
        bl.setSpacing(10)
        self.progress = QLabel("")
        self.progress.setStyleSheet(theme.text_style(9, color=theme.TEXT_MUTED))
        bl.addWidget(self.progress)

        self.stack = QStackedWidget()
        self.steps = [cls(self) for cls in STEPS]
        for step in self.steps:
            self.stack.addWidget(step)
        bl.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        self.cancel_btn = self._nav_btn("Cancel", self.cancel)
        self.back_btn = self._nav_btn("Back", self.back)
        self.skip_btn = self._nav_btn("Skip", self.next)
        self.next_btn = self._nav_btn("Next", self.next, _TOGGLE_BTN_STYLE)
        nav.addWidget(self.cancel_btn)
        nav.addStretch()
        for b in (self.back_btn, self.skip_btn, self.next_btn):
            nav.addWidget(b)
        bl.addLayout(nav)
        card_layout.addWidget(body)
        self.resize(460, 480)
        self.go(0)

    def _nav_btn(self, text: str, slot, style: str = _SMALL_BTN_STYLE) -> QPushButton:
        b = QPushButton(text)
        b.setStyleSheet(style)
        b.setMinimumWidth(72)
        b.clicked.connect(slot)
        return b

    @property
    def index(self) -> int:
        return self.stack.currentIndex()

    def go(self, index: int) -> None:
        index = max(0, min(len(self.steps) - 1, index))
        self.stack.setCurrentIndex(index)
        last = index == len(self.steps) - 1
        self.progress.setText(f"STEP {index + 1} OF {len(self.steps)}")
        self.back_btn.setEnabled(index > 0)
        self.skip_btn.setVisible(0 < index < len(self.steps) - 1)
        self.next_btn.setText("Finish" if last else "Next")
        self.steps[index].entered()

    def next(self) -> None:
        if self.index == len(self.steps) - 1:
            self._close(True)
        else:
            self.go(self.index + 1)

    def back(self) -> None:
        self.go(self.index - 1)

    def cancel(self) -> None:
        self._close(False)

    def _close(self, completed: bool) -> None:
        self.controller.sync_settings_widgets()
        self.hide()
        self.finished.emit(completed)

    def closeEvent(self, event) -> None:
        # Window X behaves like Cancel (changes already applied are kept).
        event.accept()
        if self.isVisible():
            self.controller.sync_settings_widgets()
            self.finished.emit(False)
