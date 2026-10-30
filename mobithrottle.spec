# -*- mode: python ; coding: utf-8 -*-
#
# mobiThrottle onedir build: dist/mobiThrottle/mobiThrottle.exe + _internal/.
# Mirrors mobiOverlay's onedir approach (mobioverlay.spec): onefile unpacks to
# a fresh temp dir every launch and antivirus rescans it; onedir is unpacked
# once when the user extracts the release zip. Keep the folder together.
#
# config.json persists NEXT TO the exe (see mobithrottle/paths.py app_root()).
#
#   pyinstaller mobithrottle.spec --noconfirm
#
# Author: TheRealKestryl

from PyInstaller.utils.hooks import collect_all

pygame_datas, pygame_binaries, pygame_hiddenimports = collect_all('pygame')

a = Analysis(
    ['mobithrottle_entry.py'],
    pathex=[],
    binaries=pygame_binaries,
    datas=[
        ('mobithrottle/assets', 'mobithrottle/assets'),
    ] + pygame_datas,
    hiddenimports=pygame_hiddenimports + ['keyboard'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep it light: nothing here uses these Qt add-ons.
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.Qt3DCore', 'PySide6.QtMultimedia',
              'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtPdf'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mobiThrottle',
    icon='mobithrottle/assets/mobithrottle.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='mobiThrottle',
)
