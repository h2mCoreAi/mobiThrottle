"""Draws the app icon (cyan throttle bar on a dark rounded tile) with Qt —
no Pillow dependency. `python -m mobithrottle.icon` regenerates
assets/mobithrottle.png and assets/mobithrottle.ico (Qt writes ICO)."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen

from . import theme
from .paths import assets_dir


def render(size: int = 256) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    p.setBrush(QColor(theme.BG_PANEL))
    p.setPen(QPen(QColor(theme.ACCENT_CYAN), 6 * s))
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 48 * s, 48 * s)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(theme.ACCENT_CYAN_DIM).lighter(160), 6 * s))
    p.drawRoundedRect(QRectF(98 * s, 36 * s, 60 * s, 184 * s), 22 * s, 22 * s)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.ACCENT_CYAN))
    p.drawRoundedRect(QRectF(84 * s, 100 * s, 88 * s, 26 * s), 10 * s, 10 * s)
    p.end()
    return img


def app_icon() -> QIcon:
    path = assets_dir() / "mobithrottle.png"
    if path.exists():
        return QIcon(str(path))
    from PySide6.QtGui import QPixmap

    return QIcon(QPixmap.fromImage(render()))


if __name__ == "__main__":
    import sys

    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv)
    out = assets_dir()
    render(256).save(str(out / "mobithrottle.png"))
    render(256).save(str(out / "mobithrottle.ico"))
    print("wrote", out)
