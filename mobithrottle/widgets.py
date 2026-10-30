"""Shared settings-panel styles and small custom widgets (stepper, hotkey field)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from . import theme
from .hotkey import GlobalHotkey

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
