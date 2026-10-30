"""Color, font and style constants matching the approved design mockup.

Vendored from mobiOverlay host/theme.py (commit 55532f3) so mobiThrottle
keeps the same MobiGlas palette. Bundled fonts: mobithrottle/assets/fonts/.
"""

# Backgrounds — sampled directly from a live MobiGlas (in-game device
# menu) screenshot, 2026-09-04, not guessed. MobiGlas runs a blue-gray
# palette, not the teal-black this started as: BG_VOID matched what we
# already had almost exactly (real deep-space bg sampled at #03080d), but
# BG_PANEL/BG_PANEL_HEADER/BORDER_FLAT were all shifted meaningfully
# bluer and lighter to match (panel body sampled at #202832).
BG_VOID = "#04080d"
BG_PANEL = "#1a212b"
BG_PANEL_HEADER = "#141a22"
BORDER_FLAT = "#2a3540"

# Corner radius applied to every bordered box (cards, buttons, panels,
# combos, rows...) and to the main window's own outer shape (including
# the stowed pill — same constant, same radius everywhere on purpose).
# Sized to roughly match the in-game MobiGlas UI's own panel radius
# (checked against a live screenshot, 2026-09-04) — MobiGlas runs
# noticeably softer/rounder than a typical desktop app.
RADIUS = 10

# Primary accent — MobiGlas's panel borders/chrome are a pale ice-blue
# glow (sampled ~#87bee6), not teal; its "tracked/active" status text runs
# a brighter mint-teal (sampled ~#57f3d0, close to the old value here) but
# that's a secondary status color there, not the dominant chrome color —
# shifting the primary accent to ice-blue is what actually reads as
# "part of MobiGlas" rather than a green HUD sitting next to it.
ACCENT_CYAN = "#6ec8ff"
ACCENT_CYAN_DIM = "#16303f"
BORDER_CYAN = "rgba(110, 200, 255, 0.55)"

# Alert / error accent (amber)
ACCENT_AMBER = "#ffb443"

# Text — MobiGlas body text carries a blue-white tint (sampled ~#e4e7f3),
# not the teal-white this started as; muted/dim shifted the same
# direction, into the same blue-gray family as the backgrounds above.
TEXT_PRIMARY = "#e4e9f5"
TEXT_MUTED = "#8194a6"
TEXT_DIM = "#48586a"

# Fonts (bundled, see mobithrottle/assets/fonts/)
FONT_DISPLAY = "Orbitron"
FONT_MONO = "Share Tech Mono"

CARD_HEADER_HEIGHT = 34


# Global font-size multiplier applied to every stylesheet (fixed; mirrors
# mobiOverlay's default "Normal" so the splash renders identically).
FONT_SCALE = 1.15


def fpx(base_px: int) -> int:
    """Scale a base pixel font size by the current FONT_SCALE."""
    return max(1, round(base_px * FONT_SCALE))


def text_style(
    size: int,
    color: str | None = None,
    family: str | None = None,
    weight: str | int | None = None,
    letter_spacing: int | None = None,
) -> str:
    """Plain label text: color/font/size, optional weight and letter-spacing."""
    parts = [f"color: {color};"] if color else []
    parts.append(f'font-family: "{family or FONT_MONO}";')
    if weight:
        parts.append(f"font-weight: {weight};")
    parts.append(f"font-size: {fpx(size)}px;")
    if letter_spacing:
        parts.append(f"letter-spacing: {letter_spacing}px;")
    return " ".join(parts)


def field_style(
    widget: str,
    color: str,
    size: int,
    padding: str | None = None,
    family: str | None = None,
    weight: str | int | None = None,
    drop_down: int | None = None,
) -> str:
    """Dark input-field style for QComboBox / QLineEdit / QTextEdit / QListWidget.
    `drop_down` sets the combo arrow column width."""
    border = f"border: 1px solid {BORDER_FLAT}; border-radius: {RADIUS}px;"
    if padding:
        border += f" padding: {padding};"
    font = f'font-family: "{family or FONT_MONO}";'
    if weight:
        font += f" font-weight: {weight};"
    font += f" font-size: {fpx(size)}px;"
    out = (
        f"\n    {widget} {{\n        background: {BG_VOID}; color: {color};\n"
        f"        {border}\n        {font}\n    }}\n"
    )
    if drop_down:
        out += f"    {widget}::drop-down {{ width: {drop_down}px; border: none; }}\n"
    return out
