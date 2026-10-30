# Building mobiThrottle

mobiThrottle ships as a PyInstaller **onedir** folder (`mobiThrottle\mobiThrottle.exe` + `_internal\`),
the same packaging approach as mobiOverlay. Windows only for the packaged app; source runs anywhere
PySide6 + pygame-ce run (hotkeys and Win32 click-through are Windows-only and safely no-op elsewhere).

## Local build (Windows, PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-build.txt
python tests\test_throttle.py          # must print ALL PASSED
pyinstaller mobithrottle.spec --noconfirm
# -> dist\mobiThrottle\mobiThrottle.exe
```

Run the result from `dist\mobiThrottle\`. Its `config.json` is created next to the exe.

## Icon

`mobithrottle/assets/mobithrottle.png` / `.ico` are committed. To regenerate the PNG:
`python -m mobithrottle.icon` (Qt draws it). The multi-size `.ico` was made from the PNG with Pillow:
`python -c "from PIL import Image; Image.open('mobithrottle/assets/mobithrottle.png').save('mobithrottle/assets/mobithrottle.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"`
(Pillow is only needed for that one-off step; it is not a runtime or build dependency.)

## Release (CI)

Push a tag `vX.Y.Z` → `.github/workflows/release.yml` runs on `windows-latest`: installs
`requirements-build.txt`, runs the tests, builds the spec, and publishes
`mobiThrottle-vX.Y.Z-windows.zip` + `.sha256` to a GitHub Release, with a signed
build-provenance attestation (`actions/attest-build-provenance`) for the exe and the zip.
Bump `__version__` in `mobithrottle/__init__.py` first. Python 3.13 is pinned in CI.

`.github/workflows/ci.yml` runs the tests + a PyInstaller smoke build on every push/PR to
`main`. Release binaries are only ever produced by CI — never upload a locally built zip.

## Supply-chain hardening

- Every GitHub Action is pinned to a full commit SHA (version in a trailing comment).
  Dependabot (`.github/dependabot.yml`) proposes weekly bumps for actions and pip.
- CI and release install from `requirements-build.lock` with `--require-hashes --no-deps`:
  exact versions + SHA256 for every wheel, resolved for Windows / Python 3.13.
  `requirements*.txt` stay the human-edited inputs. After changing them, regenerate:

  ```
  pip install uv
  uv pip compile requirements.txt --python-platform windows --python-version 3.13 --generate-hashes -o requirements.lock
  uv pip compile requirements-build.txt --python-platform windows --python-version 3.13 --generate-hashes -o requirements-build.lock
  ```
  (then restore the two header comment lines). Local dev may still use the `.txt` files.
- Workflows default to `permissions: contents: read`; only the release job gets
  `contents/id-token/attestations: write`. CI runs cancel superseded runs per ref; releases never cancel.
