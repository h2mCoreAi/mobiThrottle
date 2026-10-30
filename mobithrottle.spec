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

# Size budget (2026-10-30): the first build was ~155 MB, almost all unused
# Qt. We use only QtCore/QtGui/QtWidgets + the Windows platform plugin.
# pygame: PyInstaller's built-in hook already collects its DLLs; the old
# collect_all('pygame') also dragged in docs/examples/tests (~10 MB).

QT_EXCLUDE_MODULES = [
    'QtNetwork', 'QtQml', 'QtQuick', 'QtQuickWidgets', 'QtQuickControls2', 'QtWebEngineCore',
    'QtWebEngineWidgets', 'QtWebEngineQuick', 'QtWebChannel', 'QtWebSockets', 'QtMultimedia',
    'QtMultimediaWidgets', 'QtSpatialAudio', 'QtOpenGL', 'QtOpenGLWidgets', 'QtPdf', 'QtPdfWidgets',
    'QtSvg', 'QtSvgWidgets', 'QtCharts', 'QtDataVisualization', 'QtGraphs', 'Qt3DCore', 'Qt3DRender',
    'QtSql', 'QtTest', 'QtXml', 'QtDBus', 'QtBluetooth', 'QtNfc', 'QtPositioning', 'QtLocation',
    'QtSensors', 'QtSerialPort', 'QtSerialBus', 'QtRemoteObjects', 'QtScxml', 'QtStateMachine',
    'QtTextToSpeech', 'QtHelp', 'QtDesigner', 'QtUiTools', 'QtConcurrent', 'QtPrintSupport',
    'QtHttpServer', 'QtNetworkAuth', 'QtAxContainer',
]

a = Analysis(
    ['mobithrottle_entry.py'],
    pathex=[],
    binaries=[],
    datas=[('mobithrottle/assets', 'mobithrottle/assets')],
    hiddenimports=['keyboard'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'unittest', 'pydoc', 'doctest', 'xmlrpc', 'pdb',
              'lib2to3', 'sqlite3', 'numpy', 'PIL',
              'pygame.examples', 'pygame.tests', 'pygame.docs', 'pygame._sdl2.video',
              'pygame.camera', 'pygame.midi', 'pygame.sndarray', 'pygame.surfarray']
             + [f'PySide6.{m}' for m in QT_EXCLUDE_MODULES],
    noarchive=False,
    optimize=0,
)

# Drop leftover heavy binaries/data the PySide6 hook still pulls in.
_DROP_SUBSTR = (
    'opengl32sw',            # ~20 MB software OpenGL; we never use GL
    'd3dcompiler',           # GL/ANGLE helper
    'qt6network', 'qt6qml', 'qt6quick', 'qt6pdf', 'qt6svg', 'qt6opengl', 'qt6virtualkeyboard',
    'qt6webengine', 'qt6multimedia',   # NOT qt6dbus: QtGui links it on Linux
    '/translations/', '\\translations\\',
    'plugins/tls', 'plugins\\tls', 'plugins/networkinformation', 'plugins\\networkinformation',
    'plugins/generic', 'plugins\\generic', 'plugins/iconengines', 'plugins\\iconengines',
    'plugins/platforminputcontexts', 'plugins\\platforminputcontexts',
    'qdirect2d',
    'qgif', 'qjpeg', 'qsvg', 'qtga', 'qtiff', 'qwbmp', 'qwebp', 'qicns', 'qpdf',  # keep qico
    'pygame/docs', 'pygame\\docs', 'pygame/examples', 'pygame\\examples',
    'pygame/tests', 'pygame\\tests', 'freesansbold',
)


import sys
if sys.platform == 'win32':
    # Windows release: only qwindows platform plugin (offscreen kept elsewhere for CI smoke).
    _DROP_SUBSTR += ('qminimal', 'qoffscreen')


def _keep(entry):
    name = (entry[0] + '|' + entry[1]).lower()
    return not any(s in name for s in _DROP_SUBSTR)


a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

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
    upx=False,  # UPX on Qt DLLs: AV false positives + broken plugins; strip is a no-op on Windows
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
    upx=False,  # UPX on Qt DLLs: AV false positives + broken plugins; strip is a no-op on Windows
    upx_exclude=[],
    name='mobiThrottle',
)
