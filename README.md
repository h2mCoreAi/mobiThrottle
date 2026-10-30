# mobiThrottle

A tiny, always-on-top bar that shows your flight-stick throttle position — by **TheRealKestryl**.

Works with any joystick/throttle Windows sees (VKB, Virpil, Thrustmaster, Logitech…) and any game
(Star Citizen, DCS, Elite, MSFS…). It only *reads* the device like any game would — it never touches
any game process.

## Install

1. Download `mobiThrottle-vX.Y.Z-windows.zip` from the [Releases](../../releases) page
   (optionally check it against the `.sha256` file).
2. Extract it anywhere (e.g. `Documents\mobiThrottle`). Keep the whole folder together —
   `mobiThrottle.exe` needs the `_internal\` folder next to it.
3. Double-click `mobiThrottle.exe`.

On first run the **Setup guide** opens and walks you through 11 short steps: device, throttle
axis (Detect or pick by hand, with a live preview), direction, orientation, colors, home chirp,
detents, hotkeys and click-through. Each change applies immediately; **Cancel** closes the guide
and keeps whatever you already set. Reopen it any time from Settings → **SETUP GUIDE**.

## Using it

- **The bar** floats on top of everything. Left-drag to move it, right-drag to resize.
  The knob turns from blue (center) to amber (full deflection).
- **Tray icon** (bottom-right, near the clock): right-click for *Show Settings*, *Toggle Bar*,
  *Toggle Click-Through*, *Quit*. Double-click opens Settings. Closing Settings just hides it —
  mobiThrottle keeps running in the tray until you choose *Quit*.
- **Click-through**: turn it on once the bar is where you want it. Mouse clicks then pass straight
  through to the game, so you can't accidentally drag it mid-flight. Turn it off (tray or Settings)
  to move it again.
- **Home chirp**: a short beep when the throttle returns to center (configurable count/cooldown,
  or off). Uses normal Windows audio, so it works while a game is fullscreen.
- **Detents** (optional): move the throttle to a spot you care about (e.g. a cruise point) and click
  *Set* — an amber marker appears on the bar. Tick *Chirp* to beep when you cross it.
- **Positions**: save two bar locations (SCM / NAV) and jump between them.
- **Hotkeys** (optional, none by default): toggle the bar or swap positions from anywhere.

## Extras

- **Centre-zero colours** (Settings → Appearance, off by default): the moving indicator turns
  green above zero and red below, keeping your line colour in a small band around zero.
- **Disconnect alert** (Settings → Device, on by default): if your selected controller is
  unplugged the bar greys out and plays one low tone; it returns to normal when reconnected.
- The setup guide's Axis and Direction steps show a live readout (raw value, min/max, rest
  jitter) with a one-line hint about Reverse and a suggested deadzone.

## Settings file

Everything is saved to `config.json` **next to `mobiThrottle.exe`**. Delete it to reset to defaults.

## Troubleshooting

- *"No device found"* — plug the stick in, then click *Refresh* / *Detect* in Settings.
- *Game keyboard feels stuck after a crash* — only if you set a hotkey: close mobiThrottle
  (tray → Quit, or Task Manager → `mobiThrottle.exe`). With no hotkeys set, mobiThrottle installs
  no keyboard hook at all.
- Only one copy runs at a time; a second launch shows a message and exits.

## License

MIT — see [LICENSE](LICENSE). © 2026 TheRealKestryl.

## Verify your download
Releases are compiled by GitHub Actions from the tagged source — no locally built
binaries are uploaded. Each release has a signed build-provenance attestation.

```
gh attestation verify mobiThrottle-vX.Y.Z-windows.zip --repo h2mCoreAi/mobiThrottle
```
Then check the hash matches the attached `.sha256`:
```
Get-FileHash mobiThrottle-vX.Y.Z-windows.zip -Algorithm SHA256
```
Security reports: see [SECURITY.md](SECURITY.md).
