# -*- mode: python ; coding: utf-8 -*-
"""
GhostMind — PyInstaller spec file (ONEDIR build, Windows).

Build with:
    pyinstaller ghostmind.spec

Or equivalently:
    python -m PyInstaller ghostmind.spec

Output: dist/ghostmind/  (one-dir folder with ghostmind.exe + all dependencies)

Design notes (release plan R-01):
- ONEDIR (not one-file): faster-whisper / sounddevice / pywin32 binaries break in one-file mode.
- hiddenimports: covers guarded imports (faster_whisper, sounddevice, keyboard) and C extensions (win32gui, win32api).
- datas: assets/ (icon.ico) + LICENSE.
- excludes: tests/, tkinter, matplotlib (not needed at runtime).
- console=False: GUI app, no console window.
"""

from PyInstaller.utils.hooks import collect_all

block_cipher = None


# ---------------------------------------------------------------------------
# Hidden imports — modules PyInstaller cannot detect automatically.
# These are guarded imports (try/except) in the GhostMind codebase, or C
# extensions (.pyd files) that static analysis misses.
#
# The list is generated from analysis of the actual imports in the codebase.
# Packages that use collect_all include their own submodules, binaries, and
# data files automatically.
# ---------------------------------------------------------------------------

# Packages where we use collect_all (includes submodules, binaries, datas).
_hidden_keyboard, _data_keyboard, _hidden_keyboard_deps = collect_all('keyboard')
_hidden_faster_whisper, _data_faster_whisper, _hidden_faster_whisper_deps = collect_all('faster_whisper')
_hidden_ctranslate2, _data_ctranslate2, _hidden_ctranslate2_deps = collect_all('ctranslate2')
_hidden_pytesseract, _data_pytesseract, _hidden_pytesseract_deps = collect_all('pytesseract')
_hidden_cv2, _data_cv2, _hidden_cv2_deps = collect_all('cv2')
_hidden_numpy, _data_numpy, _hidden_numpy_deps = collect_all('numpy')

# Combine all hidden imports.
_hiddenimports = (
    _hidden_keyboard_deps
    + _hidden_faster_whisper_deps
    + _hidden_ctranslate2_deps
    + _hidden_pytesseract_deps
    + _hidden_cv2_deps
    + _hidden_numpy_deps
    # Modules not covered by collect_all (single-file modules or C extensions).
    + [
        'win32gui',     # C extension (.pyd) — used in screen_reader + stealth.
        'win32con',     # Python file — used in stealth for GWL_EXSTYLE etc.
        'win32api',     # C extension (.pyd) — needed by win32gui internally.
        'sounddevice',  # Python file wrapping PortAudio (guarded import).
        '_sounddevice',  # Python file — PortAudio ctypes wrapper.
        'keyring',      # API key storage (Windows Credential Manager).
        'toml',         # Config file parsing.
        'dotenv',       # .env file loading (python-dotenv).
        'httpx',        # HTTP client for Groq API.
        'groq',         # Groq SDK client.
    ]
)

# ---------------------------------------------------------------------------
# Data files — assets the app needs at runtime.
# ---------------------------------------------------------------------------

_datas = [
    # Application icon (used by overlay window + tray icon).
    ('assets/icon.ico', 'assets'),
    # License file (included in installer per release plan R-01).
    ('LICENSE', '.'),
]

# ---------------------------------------------------------------------------
# Binaries — C extensions and DLLs that need to be bundled.
# collect_all already collected most; we add win32 modules manually.
# ---------------------------------------------------------------------------

_binaries = _data_keyboard + _data_faster_whisper + _data_ctranslate2 + _data_pytesseract + _data_cv2 + _data_numpy

# Add win32 binaries (pywin32 C extensions).
import os
import sys

_venv_site_packages = os.path.join(sys.prefix, 'Lib', 'site-packages')

_win32_binaries = [
    (os.path.join(_venv_site_packages, 'win32', 'win32gui.pyd'), 'win32'),
    (os.path.join(_venv_site_packages, 'win32', 'win32api.pyd'), 'win32'),
    (os.path.join(_venv_site_packages, 'win32', 'win32gui.lib'), 'win32'),
    (os.path.join(_venv_site_packages, 'win32', 'win32api.lib'), 'win32'),
]

# Only add if the files exist (they should in the venv).
for src, dest in _win32_binaries:
    if os.path.exists(src):
        _binaries.append((src, dest))

# Add sounddevice and _sounddevice Python files as binaries (they are not
# collected by collect_all since they're single files, not packages).
_sounddevice_path = os.path.join(_venv_site_packages, 'sounddevice.py')
_sounddevice_py_path = os.path.join(_venv_site_packages, '_sounddevice.py')

if os.path.exists(_sounddevice_path):
    _binaries.append((_sounddevice_path, '.'))
if os.path.exists(_sounddevice_py_path):
    _binaries.append((_sounddevice_py_path, '.'))


# ---------------------------------------------------------------------------
# Analysis — the main analysis step.
# ---------------------------------------------------------------------------

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tests',
        'tkinter',
        'matplotlib',
        # Exclude numpy test modules (not needed at runtime).
        'numpy._pyinstaller.tests',
        'numpy.f2py.tests',
        'numpy.lib.tests',
        'numpy.linalg.tests',
        'numpy.ma.tests',
        'numpy.matrixlib.tests',
        'numpy.polynomial.tests',
        'numpy.random.tests',
        'numpy.testing.tests',
        'numpy.tests',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)


# ---------------------------------------------------------------------------
# PYZ — create a ZIP archive of Python modules.
# ---------------------------------------------------------------------------

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)


# ---------------------------------------------------------------------------
# EXE — create the executable.
# ---------------------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ghostmind',
    debug=False,
    bootloaderignore=True,
    strip=False,
    upx=True,
    upx_exclude=[
        # Exclude large DLLs that UPX may corrupt or that don't benefit.
        'ctranslate2.dll',
        'cudnn64_9.dll',
        'libiomp5md.dll',
        'opencv_videoio_ffmpeg*.dll',
    ],
    runtime_tmpdir=None,
    console=False,  # GUI app — no console window.
    disable_window_compat_redirection=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)


# ---------------------------------------------------------------------------
# COLLECT — collect everything into the output folder.
# ---------------------------------------------------------------------------

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        'ctranslate2.dll',
        'cudnn64_9.dll',
        'libiomp5md.dll',
        'opencv_videoio_ffmpeg*.dll',
    ],
    name='ghostmind',
)
