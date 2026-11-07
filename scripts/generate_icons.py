"""Regenerate the GhostMind app icons from assets/icon_src.svg (dev-time tool).

Render pipeline (C9):
1. The SVG is rasterized at 512px by a headless Chromium browser (Edge ships
   with Windows), which renders the design faithfully — gradients, halo and
   rounded corners included. A cairosvg fallback would drop the soft effects,
   so a browser is strongly preferred.
2. Pillow downscales the 512px master (LANCZOS) into every icon size and
   assembles assets/icon.ico (16..256, 256 stored PNG-compressed) plus
   assets/icon_256.png for the system tray.

This script is a developer tool — it is not part of the shipped app. Usage:
    python scripts/generate_icons.py            # regenerate everything
    python scripts/generate_icons.py --check    # verify outputs are current
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("generate_icons")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SVG = REPO_ROOT / "assets" / "icon_src.svg"
ICO_PATH = REPO_ROOT / "assets" / "icon.ico"
PNG_PATH = REPO_ROOT / "assets" / "icon_256.png"

MASTER_SIZE = 512
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# Installer wizard side art (C10): classic 164x314 plus a 2x image for
# Inno Setup 6.3+ DPI scaling (WizardResizeImageFile).
WIZARD_W, WIZARD_H = 164, 314
WIZARD_DIR = REPO_ROOT / "assets" / "installer"

_BROWSER_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]


def find_browser() -> Optional[Path]:
    """Headless-capable Chromium browser, Edge first (bundled with Windows)."""
    for candidate in _BROWSER_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def render_svg_text(svg_text: str, size: int, browser: Path) -> Image.Image:
    """Rasterize an SVG string at `size`×`size` with a transparent background."""
    html = (
        "<!doctype html><html><head><style>"
        "*{margin:0;padding:0}html,body{width:100%;height:100%;overflow:hidden;"
        "background:transparent}</style></head><body>"
        + svg_text
        + "</body></html>"
    )
    with tempfile.TemporaryDirectory(prefix="ghostmind-icons-") as tmp:
        tmp_dir = Path(tmp)
        html_path = tmp_dir / "icon.html"
        html_path.write_text(html, encoding="utf-8")
        shot = tmp_dir / "shot.png"
        cmd = [
            str(browser),
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--default-background-color=00000000",
            f"--window-size={size},{size}",
            f"--screenshot={shot}",
            html_path.as_uri(),
        ]
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=60,
            cwd=str(tmp_dir),
            # A fresh profile avoids clashing with a running browser instance.
            env=None,
        )
        img = Image.open(shot).convert("RGBA")
    if img.size != (size, size):
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def render_svg(svg_path: Path, size: int, browser: Path) -> Image.Image:
    """Rasterize the SVG file at `size`×`size` with a transparent background."""
    return render_svg_text(svg_path.read_text(encoding="utf-8"), size, browser)


def _ghost_only_svg(svg_text: str) -> str:
    """Drop the black base plate so only the ghost silhouette remains.

    Used for the wizard side art: the ghost floats directly on the banner
    gradient instead of sitting inside its own app-icon tile.
    """
    lines = []
    for line in svg_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("<rect") and ('fill="#000000"' in stripped or "stroke=" in stripped):
            continue
        lines.append(line)
    return "\n".join(lines)


def _alpha_bbox(image: Image.Image) -> Image.Image:
    """Crop transparent margins so the artwork fills the canvas edge-to-edge.

    The source SVG already fills its viewBox, but the crop keeps the ICO
    robust if a future design adds breathing room.
    """
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        return image
    return image.crop(bbox)


def build_outputs(master: Image.Image) -> None:
    """Write assets/icon.ico (multi-size) and assets/icon_256.png."""
    master = _alpha_bbox(master)
    side = min(master.size)
    master = master.crop(
        (
            (master.width - side) // 2,
            (master.height - side) // 2,
            (master.width + side) // 2,
            (master.height + side) // 2,
        )
    )

    # Pillow's ICO plugin derives every layer from the 512 master; the 256
    # layer is stored PNG-compressed automatically.
    master.save(str(ICO_PATH), format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    master.resize((256, 256), Image.Resampling.LANCZOS).save(PNG_PATH, format="PNG")


def verify_outputs() -> List[str]:
    """Reopen the ICO and report the layer sizes actually stored."""
    ico = Image.open(ICO_PATH)
    sizes = sorted({s for s in ico.info.get("sizes", [])})
    return [f"{s[0]}" for s in sizes]


def _wordmark_font(px: int) -> ImageFont.FreeTypeFont:
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", px)
        except OSError:
            continue
    return ImageFont.load_default()


def build_wizard_art(svg_text: str, browser: Path) -> None:
    """Compose the branded installer wizard side images (C10).

    Layout mirrors the reference installers: dark vertical gradient, the
    ghost silhouette floating in the upper half, the wordmark and a thin
    emerald accent below. Drawn at 2x and downscaled so both the classic
    164x314 image and the 6.3+ DPI-scaled variant stay crisp.
    """
    scale = 2
    w, h = WIZARD_W * scale, WIZARD_H * scale

    gradient = Image.linear_gradient("L").resize((w, h))
    top = Image.new("RGB", (w, h), (0x16, 0x1B, 0x22))
    bottom = Image.new("RGB", (w, h), (0x05, 0x07, 0x0A))
    canvas = Image.composite(top, bottom, gradient)

    ghost = render_svg_text(_ghost_only_svg(svg_text), MASTER_SIZE, browser)
    ghost = _alpha_bbox(ghost)
    side = min(ghost.size)
    ghost = ghost.crop((
        (ghost.width - side) // 2,
        (ghost.height - side) // 2,
        (ghost.width + side) // 2,
        (ghost.height + side) // 2,
    ))
    ghost_w = int(w * 0.66)
    ghost = ghost.resize((ghost_w, ghost_w), Image.Resampling.LANCZOS)
    canvas.paste(ghost, ((w - ghost_w) // 2, int(h * 0.10)), ghost)

    draw = ImageDraw.Draw(canvas)
    title_font = _wordmark_font(int(w * 0.115))
    subtitle_font = _wordmark_font(int(w * 0.052))

    title = "GhostMind"
    tw = draw.textlength(title, font=title_font)
    title_y = int(h * 0.72)
    draw.text(((w - tw) / 2, title_y), title, font=title_font, fill=(255, 255, 255))

    subtitle = "STEALTH AI ASSISTANT"
    sw = draw.textlength(subtitle, font=subtitle_font)
    sub_y = title_y + int(w * 0.155)
    draw.text(((w - sw) / 2, sub_y), subtitle, font=subtitle_font, fill=(137, 148, 163))

    bar_w, bar_h = int(w * 0.34), max(2, int(w * 0.012))
    draw.rounded_rectangle(
        ((w - bar_w) / 2, sub_y + int(w * 0.11), (w + bar_w) / 2, sub_y + int(w * 0.11) + bar_h),
        radius=bar_h,
        fill=(0, 255, 136),
    )

    WIZARD_DIR.mkdir(parents=True, exist_ok=True)
    canvas.save(WIZARD_DIR / "wizard-side-2x.bmp", format="BMP")
    canvas.resize((WIZARD_W, WIZARD_H), Image.Resampling.LANCZOS).save(
        WIZARD_DIR / "wizard-side.bmp", format="BMP"
    )
    logger.info(
        "Wrote wizard-side.bmp (%dx%d) and wizard-side-2x.bmp (%dx%d)",
        WIZARD_W,
        WIZARD_H,
        w,
        h,
    )
    # Keep a PNG preview for quick human checks (gitignored dev area).
    preview_dir = REPO_ROOT / "dev_environment" / "qa"
    preview_dir.mkdir(parents=True, exist_ok=True)
    canvas.save(preview_dir / "wizard-side-preview.png", format="PNG")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg", type=Path, default=DEFAULT_SVG)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.svg.is_file():
        logger.error("SVG not found: %s", args.svg)
        return 1
    browser = find_browser()
    if browser is None:
        logger.error(
            "No Chromium browser found for rendering. Install Edge/Chrome or "
            "export a 512px PNG from the SVG manually and re-run."
        )
        return 1

    logger.info("Rendering %s at %dpx via %s", args.svg.name, MASTER_SIZE, browser.name)
    master = render_svg(args.svg, MASTER_SIZE, browser)

    build_outputs(master)
    build_wizard_art(args.svg.read_text(encoding="utf-8"), browser)

    layers = verify_outputs()
    logger.info("Wrote %s (layers: %s) and %s", ICO_PATH.name, ", ".join(layers), PNG_PATH.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
