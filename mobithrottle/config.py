"""mobiThrottle's own config.json (next to the exe when frozen, repo root
from source). Flat dict of the same setting keys the mobiOverlay module
stored under modules.mobi_throttle — so an overlay user can paste that
section in as-is. Defaults live in ThrottleController.DEFAULTS."""
import json
import logging
import os
from pathlib import Path

from .paths import app_root

logger = logging.getLogger("mobithrottle.config")

CONFIG_FILENAME = "config.json"


def default_config_path() -> Path:
    return app_root() / CONFIG_FILENAME


def default_settings() -> dict:
    from .throttle import ThrottleController
    return dict(ThrottleController.DEFAULTS)


class Config:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_config_path()
        self.existed = self.path.exists()
        self.settings = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        # Corrupt file: keep a copy for inspection and start fresh.
        try:
            self.path.replace(self.path.with_suffix(".json.corrupt"))
        except OSError:
            pass
        logger.warning("config.json was unreadable; starting with defaults")
        return {}

    def save(self):
        """Atomic write (temp file + replace) so a crash never truncates it."""
        tmp = self.path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            logger.warning("Could not save config: %s", exc)
