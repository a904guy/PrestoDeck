"""Generate PrestoDeck's built-in button icon set as device-ready PNGs.

The device draws each icon as a centered PNG over the button face (see
``device/lib/prestodeck/button.py``). These glyphs are drawn white on a
transparent canvas so a single icon works on a button of any accent colour --
only the symbol shows, sitting on the button's own fill/outline.

Run it to (re)generate the icons shipped with the host::

    python tools/make_icons.py --out host/config/icons

Icons are pure geometry (no external assets), so this is fully offline and the
set stays visually consistent. Add a new entry to ``ICONS`` to grow the set.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

# Canvas size (matches the existing 96x96 icons) and glyph colour.
SIZE = 96
FG = (236, 239, 245, 255)   # near-white, matches Theme.TEXT
STROKE = 8                  # default line weight


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _line(d: ImageDraw.ImageDraw, pts, width=STROKE) -> None:
    d.line(pts, fill=FG, width=width, joint="curve")
    r = width / 2
    for x, y in pts:  # round the caps
        d.ellipse((x - r, y - r, x + r, y + r), fill=FG)


# -- individual glyphs (each draws into a fresh canvas) ---------------------

def record(d):
    d.ellipse((28, 28, 68, 68), fill=FG)


def play(d):
    d.polygon([(34, 26), (34, 70), (72, 48)], fill=FG)


def pause(d):
    d.rounded_rectangle((32, 28, 44, 68), radius=4, fill=FG)
    d.rounded_rectangle((52, 28, 64, 68), radius=4, fill=FG)


def stop(d):
    d.rounded_rectangle((30, 30, 66, 66), radius=6, fill=FG)


def _skip(d, forward=True):
    if forward:
        d.polygon([(28, 28), (28, 68), (54, 48)], fill=FG)
        d.polygon([(50, 28), (50, 68), (76, 48)], fill=FG)
        d.rounded_rectangle((72, 28, 80, 68), radius=3, fill=FG)
    else:
        d.polygon([(68, 28), (68, 68), (42, 48)], fill=FG)
        d.polygon([(46, 28), (46, 68), (20, 48)], fill=FG)
        d.rounded_rectangle((16, 28, 24, 68), radius=3, fill=FG)


def skip_next(d):
    _skip(d, True)


def skip_previous(d):
    _skip(d, False)


def _speaker(d):
    d.rectangle((22, 40, 34, 56), fill=FG)
    d.polygon([(34, 40), (50, 26), (50, 70), (34, 56)], fill=FG)


def _waves(d):
    d.arc((44, 30, 66, 66), start=-55, end=55, fill=FG, width=STROKE - 2)
    d.arc((44, 22, 78, 74), start=-52, end=52, fill=FG, width=STROKE - 2)


def volume_up(d):
    _speaker(d)
    _waves(d)
    _line(d, [(64, 22), (76, 22)], 6)   # plus
    _line(d, [(70, 16), (70, 28)], 6)


def volume_down(d):
    _speaker(d)
    _waves(d)
    _line(d, [(64, 22), (76, 22)], 6)   # minus


def volume_mute(d):
    _speaker(d)
    _line(d, [(58, 36), (78, 60)], 7)   # X
    _line(d, [(78, 36), (58, 60)], 7)


def speaker(d):
    _speaker(d)
    _waves(d)


def check(d):
    _line(d, [(26, 50), (42, 66), (72, 30)], 10)


def mic(d):
    d.rounded_rectangle((38, 18, 58, 54), radius=10, fill=FG)
    d.arc((30, 30, 66, 64), start=20, end=160, fill=FG, width=STROKE - 2)
    _line(d, [(48, 64), (48, 76)], 6)   # stand
    _line(d, [(36, 76), (60, 76)], 6)   # base


def mic_muted(d):
    mic(d)
    _line(d, [(24, 22), (72, 74)], 8)   # slash


def monitor(d):
    d.rounded_rectangle((22, 24, 74, 60), radius=6, outline=FG, width=STROKE - 2)
    _line(d, [(48, 60), (48, 70)], 6)
    _line(d, [(36, 72), (60, 72)], 6)


def broadcast(d):
    d.ellipse((42, 42, 54, 54), fill=FG)
    for r, w in ((16, 5), (26, 5)):
        d.arc((48 - r, 48 - r, 48 + r, 48 + r), start=210, end=330, fill=FG, width=w)
        d.arc((48 - r, 48 - r, 48 + r, 48 + r), start=30, end=150, fill=FG, width=w)


def coffee(d):
    d.rounded_rectangle((26, 42, 60, 72), radius=8, fill=FG)
    d.arc((56, 44, 76, 64), start=-90, end=90, fill=FG, width=STROKE - 2)
    for x in (34, 44, 54):   # steam
        d.arc((x - 4, 22, x + 4, 38), start=120, end=300, fill=FG, width=5)


def terminal(d):
    d.rounded_rectangle((20, 24, 76, 72), radius=8, outline=FG, width=STROKE - 3)
    _line(d, [(32, 40), (44, 48), (32, 56)], 6)   # >
    _line(d, [(50, 58), (62, 58)], 6)             # _


def bell(d):
    d.pieslice((30, 24, 66, 60), start=180, end=360, fill=FG)
    d.rectangle((30, 42, 66, 60), fill=FG)
    _line(d, [(26, 60), (70, 60)], 6)
    d.ellipse((44, 62, 52, 70), fill=FG)
    d.ellipse((44, 18, 52, 26), fill=FG)


def globe(d):
    d.ellipse((24, 24, 72, 72), outline=FG, width=STROKE - 3)
    d.ellipse((40, 24, 56, 72), outline=FG, width=STROKE - 4)
    _line(d, [(26, 40), (70, 40)], 4)
    _line(d, [(24, 48), (72, 48)], 4)
    _line(d, [(26, 56), (70, 56)], 4)


def arrows_swap(d):
    _line(d, [(28, 38), (68, 38)], 7)
    d.polygon([(68, 30), (68, 46), (80, 38)], fill=FG)
    _line(d, [(68, 58), (28, 58)], 7)
    d.polygon([(28, 50), (28, 66), (16, 58)], fill=FG)


ICONS = {
    "record": record,
    "play": play,
    "pause": pause,
    "stop": stop,
    "next": skip_next,
    "previous": skip_previous,
    "volume_up": volume_up,
    "volume_down": volume_down,
    "volume_mute": volume_mute,
    "speaker": speaker,
    "check": check,
    "mic": mic,
    "mic_muted": mic_muted,
    "monitor": monitor,
    "broadcast": broadcast,
    "coffee": coffee,
    "terminal": terminal,
    "bell": bell,
    "globe": globe,
    "swap": arrows_swap,
}


def build(out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, fn in ICONS.items():
        img, d = _canvas()
        fn(d)
        path = out_dir / f"{name}.png"
        img.save(path)
        written.append(path.name)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate PrestoDeck button icons.")
    ap.add_argument("--out", default="host/config/icons", help="output icon directory")
    ap.add_argument("--also", action="append", default=[], help="extra dirs to mirror into")
    args = ap.parse_args()
    names = build(Path(args.out))
    for extra in args.also:
        build(Path(extra))
    print(f"wrote {len(names)} icons to {args.out}: {', '.join(names)}")


if __name__ == "__main__":
    main()
