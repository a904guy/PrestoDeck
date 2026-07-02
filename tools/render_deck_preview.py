"""Render promotional preview images of a deck, matching the device's look.

Reproduces the on-device layout (480x480 panel, 24px margin, 20px gap, 12px
corner radius, 2px accent outline, icon centered with the label beneath) from a
`deck.yaml` and its icons, so the README can show what a running deck looks like
without a photo. Supersampled and downscaled for crisp edges.

Usage:
    python tools/render_deck_preview.py --deck host/config/deck.yaml \
        --icons host/config/icons --out assets/promo
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw, ImageFont

SCREEN = 480
MARGIN = 24
GAP = 20
RADIUS = 12
SS = 3  # supersample factor
OUT = 960  # final edge length

# Theme constants pulled from device/lib/prestodeck/ui.py.
BACKGROUND = (10, 10, 14)
BUTTON_FILL = (38, 44, 60)
PRESSED_FILL = (70, 110, 200)
TEXT = (235, 238, 245)
DEFAULT_OUTLINE = (60, 200, 200)

_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Live-state overrides per page, so the OBS page shows a compelling "on air"
# moment (recording, muted mic) instead of every button in its idle look.
LIVE_STATES: dict[str, dict[str, dict[str, Any]]] = {
    "obs": {
        "record": {"label": "REC ON", "color": [200, 0, 0], "icon": "stop.png"},
        "scene_brb": {"label": "BRB LIVE", "color": [0, 180, 0], "icon": "check.png"},
        "mute_mic": {"label": "Mic Muted", "color": [200, 0, 0], "icon": "mic_muted.png"},
    },
}


def _font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_FONT, px)


def _grid_rects(cols: int, rows: int) -> list[tuple[int, int, int, int]]:
    usable_w = SCREEN - 2 * MARGIN - GAP * (cols - 1)
    usable_h = SCREEN - 2 * MARGIN - GAP * (rows - 1)
    bw, bh = usable_w // cols, usable_h // rows
    rects = []
    for r in range(rows):
        for c in range(cols):
            rects.append((MARGIN + c * (bw + GAP), MARGIN + r * (bh + GAP), bw, bh))
    return rects


def _centered(draw: ImageDraw.ImageDraw, text: str, cx: int, cy: int, font: ImageFont.FreeTypeFont) -> None:
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (r - l) / 2 - l, cy - (b - t) / 2 - t), text, font=font, fill=TEXT)


def render_page(
    deck: dict[str, Any],
    page: dict[str, Any],
    icons_dir: Path,
    live: bool = False,
    states: dict[str, dict[str, Any]] | None = None,
    pressed: str | None = None,
) -> Image.Image:
    theme = deck.get("theme") or {}
    bg = tuple(theme.get("background", BACKGROUND))
    default_outline = tuple(theme.get("default_outline_color", DEFAULT_OUTLINE))

    img = Image.new("RGBA", (SCREEN * SS, SCREEN * SS), (*bg, 255))
    draw = ImageDraw.Draw(img)
    grid = page.get("grid", [2, 2])
    rects = _grid_rects(grid[1], grid[0])
    if states is not None:
        overrides = states
    else:
        overrides = LIVE_STATES.get(page["id"], {}) if live else {}

    for button in page.get("buttons", []):
        state = overrides.get(button["id"], {})
        label = state.get("label", button.get("label", ""))
        icon = state.get("icon", button.get("icon"))
        color = state.get("color", button.get("color")) or default_outline
        idx = button["row"] * grid[1] + button["col"]
        if idx >= len(rects):
            continue
        x, y, w, h = (v * SS for v in rects[idx])
        r = RADIUS * SS

        # Pressed buttons fill with the accent-blue "down" body (device behaviour).
        body = PRESSED_FILL if button["id"] == pressed else BUTTON_FILL
        # 2px accent outline behind the fill, then the button body.
        draw.rounded_rectangle(
            (x - 2 * SS, y - 2 * SS, x + w + 2 * SS, y + h + 2 * SS),
            radius=r + 2 * SS, fill=tuple(color),
        )
        draw.rounded_rectangle((x, y, x + w, y + h), radius=r, fill=body)

        cx, cy = x + w // 2, y + h // 2
        drew_icon = False
        if icon and (icons_dir / icon).is_file():
            ic = Image.open(icons_dir / icon).convert("RGBA")
            ic = ic.resize((ic.width * SS, ic.height * SS), Image.LANCZOS)
            img.alpha_composite(ic, (int(cx - ic.width / 2), int(cy - 14 * SS - ic.height / 2)))
            drew_icon = True
        if drew_icon:
            if label:
                _centered(draw, label, cx, y + h - 30 * SS, _font(24 * SS))
        elif label:
            _centered(draw, label, cx, cy, _font(30 * SS))

    return img.convert("RGB").resize((OUT, OUT), Image.LANCZOS)


def render_hero(screen: Image.Image) -> Image.Image:
    """Frame a rendered screen in a Presto-like bezel on a soft gradient."""
    pad, bezel = 140, 46
    size = OUT + 2 * (pad + bezel)
    # Vertical gradient backdrop.
    bg = Image.new("RGB", (size, size))
    top, bot = (24, 26, 34), (12, 12, 18)
    px = bg.load()
    for yy in range(size):
        f = yy / size
        px_row = tuple(int(top[i] + (bot[i] - top[i]) * f) for i in range(3))
        for xx in range(size):
            px[xx, yy] = px_row
    draw = ImageDraw.Draw(bg)
    # Device body (dark rounded bezel with a subtle border).
    bx0, by0 = pad, pad
    bx1, by1 = size - pad, size - pad
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=54, fill=(18, 19, 24), outline=(44, 48, 58), width=3)
    bg.paste(screen, (pad + bezel, pad + bezel))
    return bg


def main() -> None:
    ap = argparse.ArgumentParser(description="Render deck preview images.")
    ap.add_argument("--deck", default="host/config/deck.yaml")
    ap.add_argument("--icons", default="host/config/icons")
    ap.add_argument("--out", default="assets/promo")
    args = ap.parse_args()

    deck = yaml.safe_load(Path(args.deck).read_text(encoding="utf-8"))
    icons_dir = Path(args.icons)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    screens = {}
    for page in deck.get("pages", []):
        live = page["id"] in LIVE_STATES
        img = render_page(deck, page, icons_dir, live=live)
        img.save(out / f"screen-{page['id']}.png")
        screens[page["id"]] = img
        print(f"wrote screen-{page['id']}.png")

    # Hero from the most eye-catching page (OBS if present, else the first).
    hero_id = "obs" if "obs" in screens else next(iter(screens))
    render_hero(screens[hero_id]).save(out / "hero.png")
    print("wrote hero.png")

    # Side-by-side strip of up to three pages for the README.
    strip_ids = list(screens)[:3]
    gap = 40
    thumb = 520
    strip = Image.new("RGB", (thumb * len(strip_ids) + gap * (len(strip_ids) + 1), thumb + 2 * gap), (16, 17, 22))
    for i, pid in enumerate(strip_ids):
        t = screens[pid].resize((thumb, thumb), Image.LANCZOS)
        strip.paste(t, (gap + i * (thumb + gap), gap))
    strip.save(out / "pages.png")
    print("wrote pages.png")


if __name__ == "__main__":
    main()
