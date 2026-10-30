"""mobiThrottle core: the floating throttle-axis bar + its settings controls.

Ported from mobiOverlay's modules/mobi_throttle/module.py (commit 55532f3).
The floating _ThrottleBar, chirp, joystick (re)connect logic and every card
control are carried over as-is; only the ModuleBase/card plumbing was
replaced by ThrottleController + build_settings() (hosted by
settings_window.SettingsWindow). v1 additions: detents and auto-detect.
Passive HID reads only — never touches any game process.

Layout: bar.py (floating bar widget), devices.py (joysticks + chirp),
widgets.py (settings styles/widgets), detect.py (detents + auto-detect);
this module keeps ThrottleController and re-exports the rest.
"""

import time

import pygame  # provided by the pygame-ce package (see requirements.txt)
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
)

from . import theme

# Split 2026-10-30 (behavior-preserving). Names below are re-exported so
# `from mobithrottle import throttle; throttle.X` keeps working.
from .bar import (  # noqa: F401
    AXIS_POLL_HZ,
    DEADZONE,
    HOME_FLASH_DURATION,
    PANEL_RADIUS_MAX,
    PANEL_RADIUS_MIN,
    RECONNECT_STATUS_UNAVAILABLE,
    _default_bar_position,
    _ThrottleBar,
    dim_color,
    lerp_color,
    panel_radius_for,
    value_to_color,
)
from .detect import (  # noqa: F401
    DETECT_MIN_TRAVEL,
    DETECT_SECONDS,
    AxisDetector,
    AxisStats,
    detent_crossed,
    pick_axis,
)
from .devices import (  # noqa: F401
    HOME_TICK_FREQ,
    HOME_TICK_MS,
    JOYSTICKS,
    _generate_chirp_wav,
    find_joystick,
    list_joysticks,
    play_home_tick,
)
from .hotkey import GlobalHotkey
from .widgets import (
    _CHECK_STYLE,
    _COMBO_STYLE,
    _LABEL_STYLE,
    _SMALL_BTN_STYLE,
    _STATUS_STYLE,
    _TOGGLE_BTN_STYLE,
    _hline,
    _HotkeyField,
    _section_header,
    _Stepper,
)


class ThrottleController(QObject):
    """Owns the bar, the poll/reconnect timers, hotkeys and settings —
    replaces mobiOverlay's ModuleBase subclass. build_settings() populates
    any QVBoxLayout with exactly the controls the overlay card had."""

    bar_visibility_changed = Signal(bool)
    click_through_changed = Signal(bool)
    # Emitted when an auto-detect finishes: (guid, name, axis) or None.
    detect_finished = Signal(object)

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
        # Indicator turns green above zero / red below (track unchanged).
        "centre_zero_colors": False,
    }

    def __init__(self, config) -> None:
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
        self.axis_stats = AxisStats()

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
    def build_settings(self, layout, parent=None) -> None:
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

        self.centre_zero_check = QCheckBox("Centre-zero colours")
        self.centre_zero_check.setStyleSheet(_CHECK_STYLE)
        self.centre_zero_check.setToolTip("Indicator green above zero, red below; line colour near zero")
        self.centre_zero_check.setChecked(self.settings["centre_zero_colors"])
        self.centre_zero_check.toggled.connect(self.set_centre_zero_colors)
        layout.addWidget(self.centre_zero_check)

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
        entry = self._device_list[selection - 1] if selection > 0 else None
        axis = self.apply_device(entry, self.axis_spin.value(), self.axis_reverse_check.isChecked())
        self.axis_spin.setValue(axis)

    def apply_device(self, entry: dict | None, axis: int, reverse: bool) -> int:
        """Select a device (a list_joysticks() entry, or None = auto/first)
        plus axis/reverse, save, and reconnect. Returns the clamped axis.
        Shared by the settings window and the setup guide."""
        if entry is None:
            self.settings["device_guid"] = None
            self.settings["device_name"] = None
        else:
            self.settings["device_guid"] = entry["guid"]
            self.settings["device_name"] = entry["name"]
            axis = min(axis, max(0, entry["numaxes"] - 1))
        self.settings["axis_index"] = axis
        self.settings["axis_reverse"] = bool(reverse)
        self._save()
        self.axis_stats.reset()
        # Force an immediate reconnect against the new selection instead of
        # waiting for the next refresh_interval_seconds tick.
        self._device = None
        if self.request_refresh is not None:
            self.request_refresh()
        return axis

    def set_centre_zero_colors(self, enabled: bool) -> None:
        self.settings["centre_zero_colors"] = bool(enabled)
        self._save()
        self._bar.update()

    def set_axis_reverse(self, reverse: bool) -> None:
        self.settings["axis_reverse"] = bool(reverse)
        self._save()

    @property
    def current_value(self) -> float:
        """Latest axis value as drawn on the bar (reverse already applied)."""
        return self._bar.value

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
        self.axis_stats.add(raw)
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

    def is_home_flashing(self) -> bool:
        return time.time() < self._flash_until

    # -- bar geometry / visibility -----------------------------------------
    def on_bar_moved(self, x, y) -> None:
        self.settings["x"], self.settings["y"] = x, y
        self._save()

    def on_bar_resized(self, w, h) -> None:
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

    def toggle_click_through(self) -> None:
        new = not self.settings["click_through"]
        if self.status_label is not None:
            self.click_through_check.setChecked(new)  # fires the handler
        else:
            self._on_click_through_toggled(new)

    def toggle_bar(self) -> None:
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
            self.set_line_color(color.name())

    def set_line_color(self, hex_color: str) -> None:
        self.settings["line_color"] = hex_color
        if getattr(self, "line_color_btn", None) is not None:
            self.line_color_btn.setStyleSheet(
                f"background: {hex_color}; border: 1px solid {theme.BORDER_FLAT}; border-radius: 4px;"
            )
        self._save()
        self._bar.update()

    def _on_pick_bg_color(self):
        color = QColorDialog.getColor(
            QColor(self.settings["bg_color"]), self._settings_parent, "Background color"
        )
        if color.isValid():
            self.set_bg_color(color.name())

    def set_bg_color(self, hex_color: str) -> None:
        self.settings["bg_color"] = hex_color
        if getattr(self, "bg_color_btn", None) is not None:
            self.bg_color_btn.setStyleSheet(
                f"background: {hex_color}; border: 1px solid {theme.BORDER_FLAT}; border-radius: 4px;"
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
    def refresh(self) -> None:
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
    def start_detect(self) -> None:
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
            self.detect_finished.emit(None)
            return
        guid, name, axis = result
        self.settings["device_guid"] = guid
        self.settings["device_name"] = name
        self.settings["axis_index"] = axis
        self._save()
        self.axis_stats.reset()
        if self.status_label is not None:
            self.axis_spin.setValue(axis, emit=False)
            self._refresh_device_list()
        self._device = None
        self._reconnect_tick()
        self.detect_finished.emit(result)

    def sync_settings_widgets(self) -> None:
        """Re-read settings into the settings-window controls (after the
        setup guide changed them). Signals blocked: values are already saved."""
        if self.status_label is None:
            return
        on = self.settings
        pairs = (
            (self.click_through_check, lambda w: w.setChecked(on["click_through"])),
            (self.axis_reverse_check, lambda w: w.setChecked(on["axis_reverse"])),
            (
                self.orientation_combo,
                lambda w: w.setCurrentText("Horizontal" if on["orientation"] == "horizontal" else "Vertical"),
            ),
            (self.bg_opacity_slider, lambda w: w.setValue(round(on["bg_opacity"] * 100))),
            (self.line_opacity_slider, lambda w: w.setValue(round(on["line_opacity"] * 100))),
            (self.chirp_enabled_check, lambda w: w.setChecked(on["home_chirp_enabled"])),
            (self.centre_zero_check, lambda w: w.setChecked(on["centre_zero_colors"])),
        )
        for widget, apply in pairs:
            widget.blockSignals(True)
            apply(widget)
            widget.blockSignals(False)
        self.axis_spin.setValue(on["axis_index"], emit=False)
        self.chirp_count_spin.setValue(on["home_chirp_count"], emit=False)
        self.toggle_hotkey_field.setText(on["toggle_hotkey_display"] or "Click to set…")
        self.position_hotkey_field.setText(on["position_hotkey_display"] or "Click to set…")
        for which in ("line", "bg"):
            getattr(self, f"{which}_color_btn").setStyleSheet(
                f"background: {on[which + '_color']}; border: 1px solid {theme.BORDER_FLAT}; border-radius: 4px;"
            )
        self._update_toggle_btn_text()
        self._render_detents()
        self._refresh_device_list()

    def shutdown(self) -> None:
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
