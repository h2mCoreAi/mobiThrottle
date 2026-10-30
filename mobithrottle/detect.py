"""Pure detent/auto-detect helpers and the AxisDetector (unit-tested)."""

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from .devices import JOYSTICKS

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


def pick_axis(ranges: dict, min_travel: float = DETECT_MIN_TRAVEL, ends: dict | None = None) -> object | None:
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

    def __init__(self, on_done: Callable[[object | None], None]) -> None:
        super().__init__()
        self._on_done = on_done
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sample)
        self._ranges = {}
        self._ends = {}
        self._devices = {}
        self._started = 0.0

    def start(self) -> None:
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

    def cancel(self) -> None:
        self._timer.stop()


REST_WINDOW = 30  # samples (~0.5 s at 60 Hz)
REST_SPAN = 0.05  # a window this still counts as "at rest"


class AxisStats:
    """Display-only readout fed by the controller's existing 60 Hz poll:
    raw value, min/max seen, jitter while at rest, and a one-line hint.
    O(REST_WINDOW) per sample; no timers or threads of its own."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.raw: float | None = None
        self.lo = self.hi = None
        self.rest_value: float | None = None
        self.rest_jitter: float | None = None
        self._window: list[float] = []

    def add(self, raw: float) -> None:
        self.raw = raw
        self.lo = raw if self.lo is None else min(self.lo, raw)
        self.hi = raw if self.hi is None else max(self.hi, raw)
        self._window.append(raw)
        if len(self._window) > REST_WINDOW:
            self._window.pop(0)
        if len(self._window) == REST_WINDOW:
            span = max(self._window) - min(self._window)
            if span < REST_SPAN:
                self.rest_jitter = span
                self.rest_value = sum(self._window) / REST_WINDOW

    def suggested_deadzone(self, minimum: float) -> float:
        if self.rest_jitter is None:
            return minimum
        return max(minimum, math.ceil(round(self.rest_jitter * 150, 6)) / 100)  # 1.5x jitter, rounded up

    def suggestion(self, reverse: bool, minimum_deadzone: float) -> str:
        if self.raw is None:
            return "Move the throttle to see readings."
        if self.rest_value is None:
            return "Hold the throttle still for a moment to measure rest jitter."
        shown = -self.rest_value if reverse else self.rest_value
        if shown > 0.6:
            hint = "Rests at the far end: if that's idle, tick Reverse."
        elif shown < -0.6:
            hint = "Rests at the near end: direction looks right."
        else:
            hint = "Rests near centre: tick Reverse only if forward moves the bar backward."
        return f"{hint} Suggested deadzone ≥ {self.suggested_deadzone(minimum_deadzone):.2f}."

    def text(self, reverse: bool, minimum_deadzone: float) -> str:
        def f(v):
            return "—" if v is None else f"{v:+.3f}"

        jitter = "—" if self.rest_jitter is None else f"{self.rest_jitter:.3f}"
        return (
            f"raw {f(self.raw)}   min {f(self.lo)}   max {f(self.hi)}   rest jitter {jitter}\n"
            + self.suggestion(reverse, minimum_deadzone)
        )
