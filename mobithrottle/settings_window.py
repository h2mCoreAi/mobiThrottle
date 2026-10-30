"""Settings window — replaces the mobiOverlay card. A normal (framed) window
whose body is styled like an overlay card (BG_PANEL, cyan border, header
strip with the two-tone mobiThrottle title) and holds exactly the card's
controls via ThrottleController.build_settings(). Closing hides to tray."""

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from . import theme
from .throttle import ThrottleController


class _CardFrame(QFrame):
    pass


class SettingsWindow(QWidget):
    def __init__(self, controller: ThrottleController, icon=None) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("mobiThrottle — Settings")
        if icon is not None:
            self.setWindowIcon(icon)
        self.setStyleSheet(f"SettingsWindow {{ background: {theme.BG_VOID}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        card = _CardFrame()
        card.setStyleSheet(f"""
            _CardFrame {{
                background: {theme.BG_PANEL};
                border: 1px solid {theme.BORDER_CYAN};
                border-radius: {theme.RADIUS}px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("hdr")
        header.setFixedHeight(theme.CARD_HEADER_HEIGHT)
        header.setStyleSheet(f"""
            QFrame#hdr {{
                background: {theme.BG_PANEL_HEADER};
                border-top-left-radius: {theme.RADIUS}px;
                border-top-right-radius: {theme.RADIUS}px;
                border-bottom: 1px solid {theme.BORDER_FLAT};
            }}
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 10, 0)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {theme.ACCENT_CYAN}; font-size: {theme.fpx(9)}px;")
        hl.addWidget(dot)
        title = QLabel(controller.display_name)
        title.setTextInteractionFlags(Qt.NoTextInteraction)
        title.setStyleSheet(
            f'font-family: "{theme.FONT_DISPLAY}"; font-weight: 700; font-size: {theme.fpx(11)}px;'
        )
        hl.addWidget(title)
        hl.addStretch()
        byline = QLabel(
            f'<span style="color:{theme.TEXT_MUTED};">by </span>'
            f'<span style="color:{theme.ACCENT_CYAN};">TheRealKestryl</span>'
        )
        byline.setStyleSheet(f'font-family: "{theme.FONT_MONO}"; font-size: {theme.fpx(9)}px;')
        hl.addWidget(byline)
        card_layout.addWidget(header)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(8)
        controller.build_settings(body_layout, self)
        body_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        scroll.setWidget(body)
        card_layout.addWidget(scroll)
        outer.addWidget(card)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.resize(420, 760)

    def show_and_raise(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def toggle_visible(self) -> None:
        """Single left-click on the tray icon."""
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_and_raise()

    def changeEvent(self, event) -> None:
        # Minimize = hide to tray: a hidden top-level window has no taskbar
        # button, so the button exists only while settings are open. Deferred
        # because hiding inside the state-change handler confuses Windows.
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self._hide_minimized)

    def _hide_minimized(self):
        if self.isMinimized():
            self.hide()
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)

    allow_close = False  # set by app.request_quit()

    def closeEvent(self, event) -> None:
        # Close = hide to tray; Quit lives in the tray menu.
        if self.allow_close:
            event.accept()
            return
        event.ignore()
        self.hide()
