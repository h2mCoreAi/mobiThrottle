# Security

## Verifying a download
Every release zip is built by GitHub Actions from the tagged source and carries a
GitHub build-provenance attestation. See **Verify your download** in `README.md`.
If `gh attestation verify` fails, do not run the file — report it.

## Reporting a vulnerability
Please report privately via GitHub's **Security → Report a vulnerability**
(private advisory) on https://github.com/h2mCoreAi/mobiThrottle/security, not a
public issue. Include version, steps to reproduce, and impact. We aim to reply
within 7 days.

## Scope
mobiThrottle reads joystick axes locally (SDL/pygame-ce), writes `config.json`
next to the exe, and installs a keyboard hook only when a hotkey is configured.
It makes no network connections.
