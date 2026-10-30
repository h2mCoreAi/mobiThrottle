"""Where mobiThrottle keeps things on disk.

- app_root(): persistent storage (config.json, lockfile). The exe's own
  folder when frozen (PyInstaller onedir), the repo root from source.
- assets_dir(): bundled read-only assets (fonts, icon). Inside _internal/
  when frozen (sys._MEIPASS), mobithrottle/assets/ from source.
"""
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "mobithrottle" / "assets"
    return Path(__file__).resolve().parent / "assets"
