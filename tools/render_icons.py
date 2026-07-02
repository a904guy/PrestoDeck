"""Pre-rasterize source images into device-ready icon PNGs.

The RP2350 cannot decode or rescale SVG quickly, so icons are pre-rendered on
the host and shipped to the device icon cache. This tool scans a source
directory, fits each image into a square of the button pixel size (preserving
aspect ratio, on a transparent canvas), and writes the results as PNGs into the
output directory.

Usage::

    python tools/render_icons.py --src assets/icons --out host/config/icons --size 96
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logger = logging.getLogger("prestodeck.render_icons")

# Source extensions Pillow can open and we are willing to rasterize.
_SOURCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the icon renderer."""
    parser = argparse.ArgumentParser(description="Rasterize source icons for the device cache.")
    parser.add_argument("--src", required=True, help="Directory of source images.")
    parser.add_argument(
        "--out",
        default="host/config/icons",
        help="Output directory for rasterized PNGs.",
    )
    parser.add_argument("--size", type=int, default=96, help="Output edge length in pixels.")
    return parser


def render_icon(src: Path, dest: Path, size: int) -> None:
    """Fit one image into a ``size`` x ``size`` transparent PNG at ``dest``."""
    from PIL import Image

    with Image.open(src) as img:
        icon = img.convert("RGBA")
        icon.thumbnail((size, size), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        offset = ((size - icon.width) // 2, (size - icon.height) // 2)
        canvas.paste(icon, offset, icon)
        canvas.save(dest, format="PNG")


def render_dir(src_dir: Path, out_dir: Path, size: int) -> list[Path]:
    """Rasterize every supported image in ``src_dir`` into ``out_dir``.

    :returns: the list of written PNG paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for src in sorted(src_dir.iterdir()):
        if src.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        dest = out_dir / (src.stem + ".png")
        render_icon(src, dest, size)
        logger.info("rendered %s -> %s", src.name, dest.name)
        written.append(dest)
    return written


def main() -> int:
    """Entry point: rasterize the source directory into the output directory."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()

    src_dir = Path(args.src)
    if not src_dir.is_dir():
        logger.error("source directory %s does not exist", src_dir)
        return 2

    written = render_dir(src_dir, Path(args.out), args.size)
    logger.info("wrote %d icon(s) to %s", len(written), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
