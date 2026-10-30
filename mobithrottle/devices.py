"""Joystick ownership (one _Joysticks owner, hot-plug aware) and the home/detent chirp."""

import io
import math
import struct
import wave

import pygame  # provided by the pygame-ce package (see requirements.txt)
from PySide6.QtCore import QTimer

HOME_TICK_FREQ = 1400
HOME_TICK_MS = 45


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
