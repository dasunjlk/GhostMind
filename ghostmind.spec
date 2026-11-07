# -*- mode: python ; coding: utf-8 -*-
"""
GhostMind — PyInstaller spec file (ONEDIR build, Windows).

Build with:
    pyinstaller ghostmind.spec

Or equivalently:
    python -m PyInstaller ghostmind.spec

Output: dist/ghostmind/  (one-dir folder with ghostmind.exe + all dependencies)

Design notes (release plan R-01, slimmed per C12):
- ONEDIR (not one-file): pywin32 binaries break in one-file mode.
- hiddenimports: covers guarded imports (keyboard), all keyring
  backends/metadata, and C extensions (win32gui, win32api).
- AUDIO STACK IS INTENTIONALLY NOT BUNDLED (C12): faster_whisper,
  ctranslate2, and sounddevice are dormant in v1.0 (main.py never starts the
  AudioListener) and were the heaviest dependencies in the installer. They
  remain in requirements.txt so source runs keep working.
  >>> TO RE-ENABLE AUDIO: collect_all('faster_whisper'), collect_all('ctranslate2'),
  >>> collect_all('sounddevice') + their hiddenimports and the
  >>> sounddevice.py/_sounddevice.py binary copies — see git history of this
  >>> file at tag v1.1.0^ (commit 'build: drop dormant audio stack ...').
- datas: assets/ (icon.ico, icon_256.png) + LICENSE.
- excludes: tests/, tkinter, matplotlib (not needed at runtime).
- console=False: GUI app, no console window.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

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
_hidden_pytesseract, _data_pytesseract, _hidden_pytesseract_deps = collect_all('pytesseract')
_hidden_cv2, _data_cv2, _hidden_cv2_deps = collect_all('cv2')
_hidden_numpy, _data_numpy, _hidden_numpy_deps = collect_all('numpy')
_hidden_sentry, _data_sentry, _hidden_sentry_deps = collect_all('sentry_sdk')
_hidden_keyring = collect_submodules('keyring.backends')
_data_keyring = copy_metadata('keyring')

# C12: GhostMind never touches video I/O (grayscale/blur/threshold on
# in-memory arrays only), so OpenCV's ~30 MB ffmpeg video plugin is dropped.
# cv2 loads video codecs dynamically — verified: import + OCR preprocessing
# work without it.
_data_cv2 = [(src, dest) for src, dest in _data_cv2 if 'ffmpeg' not in src.lower()]

# Combine all hidden imports.
_hiddenimports = (
    _hidden_keyboard_deps
    + _hidden_pytesseract_deps
    + _hidden_cv2_deps
    + _hidden_numpy_deps
    + _hidden_sentry_deps
    + _hidden_keyring
    # Modules not covered by collect_all (single-file modules or C extensions).
    + [
        'win32gui',     # C extension (.pyd) — used in screen_reader + stealth.
        'win32con',     # Python file — used in stealth for GWL_EXSTYLE etc.
        'win32api',     # C extension (.pyd) — needed by win32gui internally.
        'keyring',      # API key storage (Windows Credential Manager).
        'toml',         # Config file parsing.
        'dotenv',       # .env file loading (python-dotenv).
        'httpx',        # HTTP client for the OpenAI-compatible SDK.
        'openai',       # Provider-agnostic OpenAI-compatible SDK.
    ]
)

# ---------------------------------------------------------------------------
# Data files — assets the app needs at runtime.
# ---------------------------------------------------------------------------

_datas = [
    # Application icon (used by overlay window + tray icon). icon_256.png is
    # the tray's preferred asset; icon.ico backs the window icon.
    ('assets/icon.ico', 'assets'),
    ('assets/icon_256.png', 'assets'),
    # License file (included in installer per release plan R-01).
    ('LICENSE', '.'),
]
_datas += _data_keyring

# ---------------------------------------------------------------------------
# Binaries — C extensions and DLLs that need to be bundled.
# collect_all already collected most; we add win32 modules manually.
# ---------------------------------------------------------------------------

_binaries = _data_keyboard + _data_pytesseract + _data_cv2 + _data_numpy + _data_sentry

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

# (C12) The sounddevice.py/_sounddevice.py binary copies that used to live
# here were removed together with the audio stack — see the docstring above.


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
        # C12: the dormant audio stack and its whole dependency chain are
        # excluded here — a plain collect_all removal is NOT enough because
        # PyInstaller's static analysis follows the guarded (try/except)
        # imports in core/audio_listener.py and pulls faster_whisper +
        # ctranslate2 + onnxruntime + av (ffmpeg libs) + tokenizers +
        # huggingface_hub (~330 MB) right back in. The hard excludes stop
        # that; core/audio_listener.py degrades gracefully at runtime.
        'faster_whisper',
        'ctranslate2',
        'sounddevice',
        '_sounddevice',
        'av',
        'onnxruntime',
        'onnxruntime_genai',
        'tokenizers',
        'huggingface_hub',
        'safetensors',
        'hf_xet',
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

# C12: strip OpenCV's ffmpeg video plugin here as well — the official
# hook-cv2 re-adds it during Analysis even after the collect_all filter
# above, and GhostMind never performs video I/O.
a.binaries = [entry for entry in a.binaries if 'ffmpeg' not in entry[0].lower()]


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
    [],
    exclude_binaries=True,  # ONEDIR: payload lives in _internal, exe stays small
    name='ghostmind',
    icon='assets\\icon.ico',  # exe icon: Explorer, taskbar, Windows search (C9)
    debug=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # Exclude large DLLs that UPX may corrupt or that don't benefit.
        'libiomp5md.dll',
        'opencv_videoio_ffmpeg*.dll',
    ],
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
        'libiomp5md.dll',
        'opencv_videoio_ffmpeg*.dll',
    ],
    name='ghostmind',
)
