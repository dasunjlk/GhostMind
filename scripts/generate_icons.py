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

from PIL import Image

logger = logging.getLogger("generate_icons")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SVG = REPO_ROOT / "assets" / "icon_src.svg"
ICO_PATH = REPO_ROOT / "assets" / "icon.ico"
PNG_PATH = REPO_ROOT / "assets" / "icon_256.png"

MASTER_SIZE = 512
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

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


def render_svg(svg_path: Path, size: int, browser: Path) -> Image.Image:
    """Rasterize the SVG at `size`×`size` with a transparent background."""
    svg_text = svg_path.read_text(encoding="utf-8")
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

    layers = verify_outputs()
    logger.info("Wrote %s (layers: %s) and %s", ICO_PATH.name, ", ".join(layers), PNG_PATH.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
