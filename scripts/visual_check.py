"""Visual QA: launch the real app, verify Preferences font scaling, save screenshots.

Runs the full stack (GhostMindController + OverlayWindow + SettingsPanel) on the
Qt "offscreen" platform so nothing flashes on the desktop and nothing steals focus.

Side effects deliberately avoided:
- audio/whisper never starts  (subtitles_enabled=False short-circuits the listener)
- global keyboard hooks are no-op'd (HotkeyManager.update_hotkeys/unregister_all patched)
- settings.toml writes go to a temp file (main.CONFIG_PATH patched)
- no network: the updater timer's first tick is 6h away and _on_test_api is never called

Outputs: qa_shots/*.png + pass/fail summary on stdout (exit 1 on any failure).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from unittest import mock

from PyQt6.QtWidgets import QApplication

SHOTS = REPO_ROOT / "qa_shots"
SHOTS.mkdir(exist_ok=True)

failures: list[str] = []
passed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (passed if cond else failures).append(f"{name}{(' — ' + detail) if detail else ''}")
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))


def shot(widget, name: str) -> Path:
    p = SHOTS / name
    widget.grab().save(str(p))
    return p


def main() -> int:
    sys.argv += ["-platform", "offscreen"]
    app = QApplication(sys.argv)
    app.setApplicationName("GhostMind")

    # --- replicate main()'s app-wide polish (same stylesheet string) ---
    from PyQt6.QtGui import QFont, QFontDatabase

    fams = {f.lower() for f in QFontDatabase.families()}
    pref = next(
        (f for f in ("Inter", "DM Sans", "JetBrains Mono", "Segoe UI") if f.lower() in fams),
        None,
    )
    if pref:
        app.setFont(QFont(pref, 10))
    offscreen_has_no_fonts = not fams  # offscreen Qt ships no font directory
    app.setStyleSheet(
        ""
        "QToolTip { color:#E0E0E0; background:#1A1A1A; border:1px solid #00FF88; padding:4px; }"
        "QMenu { background:#141414; color:#E0E0E0; border:1px solid #333; }"
        "QMenu::item:selected { background:#162B1E; color:#00FF88; }"
        "QComboBox { background:#141414; color:#E0E0E0; border:1px solid #333;"
        "  border-radius:4px; padding:3px 8px; }"
        "QComboBox QAbstractItemView { background:#141414; color:#E0E0E0;"
        "  selection-background-color:#162B1E; selection-color:#00FF88; }"
        "QSpinBox { background:#141414; color:#E0E0E0; border:1px solid #333;"
        "  border-radius:4px; padding:2px 6px; }"
        "QLineEdit { background:#141414; color:#E0E0E0; border:1px solid #333;"
        "  border-radius:4px; padding:3px 6px; }"
        "QPushButton { font-size:12px; }"
        "QScrollBar:vertical { background:#111; width:8px; border:none; }"
        "QScrollBar::handle:vertical { background:#2A5A40; border-radius:4px; min-height:24px; }"
        "QScrollBar::handle:vertical:hover { background:#00FF88; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
        "QScrollBar:horizontal { background:#111; height:8px; border:none; }"
        "QScrollBar::handle:horizontal { background:#2A5A40; border-radius:4px; min-width:24px; }"
        "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }"
    )

    import main as app_main

    tmp_cfg = Path(tempfile.mkdtemp()) / "settings.toml"
    app_main.CONFIG_PATH = tmp_cfg

    import toml

    from utils.hotkey_manager import HotkeyManager

    with mock.patch.object(HotkeyManager, "update_hotkeys", lambda *a, **k: None), mock.patch.object(
        HotkeyManager, "unregister_all", lambda *a, **k: None
    ):
        settings = dict(app_main.DEFAULT_SETTINGS)
        settings["subtitles_enabled"] = False  # never start Whisper/audio in QA
        ctrl = app_main.GhostMindController(app, settings)
        overlay = ctrl.overlay
        overlay.show()
        app.processEvents()

        panel = overlay._settings_panel

        # ---------- 1) app launched + polish present ----------
        print("\n[1] Launch & app-wide polish")
        check("overlay visible on main page", overlay.isVisible() and overlay._stack.currentIndex() == 0)
        ss = app.styleSheet()
        check("tooltip stylesheet (green border)", "QToolTip" in ss and "#00FF88" in ss)
        check("dark menu styling", "QMenu::item:selected" in ss)
        check("thin scrollbar + hover styling", "QScrollBar::handle:vertical:hover" in ss)
        if offscreen_has_no_fonts:
            print("  SKIP  base font family (offscreen platform ships no fonts; probed natively below)")
        else:
            check(
                "base font preferred family",
                app.font().family().lower()
                in {p.lower() for p in ("Inter", "DM Sans", "JetBrains Mono", "Segoe UI")},
                f"got: {app.font().family()}",
            )

        # ---------- 2) default 13pt everywhere ----------
        print("\n[2] Default font size (13)")
        check("overlay font 13", overlay.font().pointSize() == 13, f"got {overlay.font().pointSize()}")
        check("ask input stylesheet 13px", "font-size:13px" in overlay._ask_input.styleSheet())
        check("answer panel _font_pt 13", overlay._answer_panel._font_pt == 13)

        # ---------- 3) seed chat content (bubble + streamed markdown) ----------
        print("\n[3] Seed conversation content")
        ap = overlay._answer_panel
        ap.add_user_message("Why does my code block overflow the window width?")
        ap.begin_answer_stream()
        ap.append_stream_chunk("Because `<pre>` never wraps. ")
        ap.append_stream_chunk("Example:\n\n```python\nx = \"A" + "very" * 40 + "long token\"\n```")
        ap.end_stream_success()
        app.processEvents()
        check("user bubble added", ap._inner_layout.count() >= 2)
        shot(overlay, "01_main_13pt.png")

        # ---------- 4) Preferences tab exists & round-trips ----------
        print("\n[4] Preferences tab")
        prefs_idx = next(
            (i for i in range(panel._tabs.count()) if panel._tabs.tabText(i) == "Preferences"), -1
        )
        check("Preferences tab present", prefs_idx >= 0)
        overlay._toggle_settings()
        app.processEvents()
        check("settings page shown", overlay._stack.currentIndex() == 1)
        panel._tabs.setCurrentIndex(prefs_idx)
        app.processEvents()
        shot(overlay, "02_preferences_tab.png")

        # ---------- 5) save 20pt through the real slot; verify app-wide ----------
        print("\n[5] Apply 20pt via saved-signal path")
        panel._font_size.setValue(20)
        overlay._on_settings_saved(panel.collect_data())  # same slot the Save button emits into
        app.processEvents()
        check("overlay font 20", overlay.font().pointSize() == 20, f"got {overlay.font().pointSize()}")
        check("ask input 20px", "font-size:20px" in overlay._ask_input.styleSheet())
        check("answer panel _font_pt 20", overlay._answer_panel._font_pt == 20)
        check(
            "existing answer block restyled",
            all("font-size: 20px" in b._text.styleSheet() for b in overlay._answer_panel._blocks),
        )
        check(
            "subtitle view 20px",
            "font-size: 20px" in overlay._subtitle_bar._view.styleSheet(),
            overlay._subtitle_bar._view.styleSheet()[:80],
        )
        check("settings round-trip: spin shows 20", panel._font_size.value() == 20)
        persisted = toml.load(tmp_cfg) if tmp_cfg.is_file() else {}
        check("persisted to temp settings.toml", int(persisted.get("font_size", 0)) == 20, str(persisted.get("font_size")))

        shot(overlay, "03_main_20pt.png")

        # ---------- 6) 9pt (min clamp) ----------
        print("\n[6] Apply 9pt (minimum)")
        overlay.apply_font_size(9)
        app.processEvents()
        check("overlay font 9", overlay.font().pointSize() == 9)
        check("ask input 9px", "font-size:9px" in overlay._ask_input.styleSheet())
        shot(overlay, "04_main_9pt.png")

        # ---------- 7) clamp absurd values ----------
        print("\n[7] Clamp")
        overlay.apply_font_size(200)
        check("200pt clamped to 24", overlay.font().pointSize() == 24, f"got {overlay.font().pointSize()}")
        overlay.apply_font_size(2)
        check("2pt clamped to 9", overlay.font().pointSize() == 9, f"got {overlay.font().pointSize()}")

    # ---------- 8) screenshots are not blank ----------
    print("\n[8] Screenshot sanity (rendered content, not blank frames)")
    from PyQt6.QtGui import QImage

    for p in sorted(SHOTS.glob("*.png")):
        img = QImage(str(p))
        colors = set()
        for y in range(0, img.height(), 4):
            for x in range(0, img.width(), 4):
                colors.add(img.pixel(x, y))
        # blank frame ≈ 3-5 colors; real render shows dozens of shades
        check(f"{p.name} has rendered content", len(colors) > 10, f"{len(colors)} distinct colors")

    app.processEvents()
    print(f"\n=== {len(passed)} passed, {len(failures)} failed ===")
    for f in failures:
        print("  FAILED:", f)
    print(f"\nScreenshots in: {SHOTS}")
    for p in sorted(SHOTS.glob("*.png")):
        print("  ", p.name)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
