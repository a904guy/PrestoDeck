"""Build the silent product demo (MP4 + GIF) for the README.

Assembles a short looping clip from faithfully rendered deck screens: an intro,
the pages cycling, a button press that lights up live feedback, a browser-editor
beat, and an outro. No audio. Pure Pillow frames muxed by ffmpeg.

    python tools/build_demo_video.py --deck host/config/deck.yaml \
        --icons host/config/icons --out assets/promo

Requires ffmpeg on PATH.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

import render_deck_preview as rdp

W, H, FPS = 1280, 720, 30
BG = (14, 15, 20)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def font(px: int, mono: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(MONO if mono else FONT, px)


def _centered(d: ImageDraw.ImageDraw, text: str, cx: int, y: int, f: ImageFont.FreeTypeFont, fill: tuple) -> None:
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    d.text((cx - (r - l) / 2 - l, y), text, font=f, fill=fill)


def stage(square: Image.Image, size: int = 560, caption: str = "") -> Image.Image:
    """Center a square screen on the 16:9 canvas with a single caption below."""
    canvas = Image.new("RGB", (W, H), BG)
    top = (H - size) // 2
    s = square.convert("RGB").resize((size, size), Image.LANCZOS)
    canvas.paste(s, ((W - size) // 2, top))
    if caption:
        _centered(ImageDraw.Draw(canvas), caption, W // 2, top + size + 16, font(26), (156, 164, 178))
    return canvas


def title_card(hero: Image.Image, tagline: str, sub: str = "") -> Image.Image:
    """Intro/outro: the wordmark over the framed device, with a tagline."""
    size = 500
    canvas = Image.new("RGB", (W, H), BG)
    top = (H - size) // 2 + 6
    canvas.paste(hero.convert("RGB").resize((size, size), Image.LANCZOS), ((W - size) // 2, top))
    d = ImageDraw.Draw(canvas)
    _centered(d, "PrestoDeck", W // 2, top - 78, font(46), (238, 242, 250))
    _centered(d, tagline, W // 2, top + size + 14, font(25), (156, 164, 178))
    if sub:
        _centered(d, sub, W // 2, top + size + 48, font(22, mono=True), (120, 200, 200))
    return canvas


def editor_mock(pages_img: Image.Image) -> Image.Image:
    """A clean mock of the browser deck editor: YAML pane + live preview pane."""
    img = Image.new("RGB", (W, H), (13, 14, 19))
    d = ImageDraw.Draw(img)
    # Header.
    d.rectangle((0, 0, W, 54), fill=(18, 20, 27))
    d.text((28, 15), "PrestoDeck", font=font(26), fill=(90, 220, 220))
    d.text((196, 18), "deck editor", font=font(20), fill=(150, 158, 172))
    d.text((W - 96, 18), "valid", font=font(20), fill=(90, 200, 120))
    # Left YAML pane.
    pane_w = int(W * 0.56)
    d.rectangle((0, 54, pane_w, H), fill=(9, 10, 14))
    d.text((24, 70), "DECK.YAML", font=font(16), fill=(110, 118, 132))
    lines = [
        ("# PrestoDeck deck - edit live, changes push to the device", "c"),
        ("version: 1", "k"),
        ("default_page: \"main\"", "k"),
        ("", ""),
        ("pages:", "k"),
        ("  - id: \"main\"", "k"),
        ("    grid: [2, 3]", "k"),
        ("    buttons:", "k"),
        ("      - id: \"record\"", "k"),
        ("        label: \"Record\"", "k"),
        ("        icon: \"record.png\"", "k"),
        ("        color: [200, 0, 0]", "k"),
        ("        action:", "k"),
        ("          type: \"obs\"", "k"),
        ("          request: \"ToggleRecord\"", "k"),
        ("          feedback: \"record\"", "k"),
        ("          on_label: \"REC ON\"", "k"),
        ("          on_icon: \"stop.png\"", "k"),
    ]
    fm = font(17, mono=True)
    y = 104
    for text, kind in lines:
        color = {"c": (95, 104, 118), "k": (196, 204, 218)}.get(kind, (196, 204, 218))
        # light key/value tint
        if kind == "k" and ":" in text and not text.strip().startswith("-"):
            key, _, val = text.partition(":")
            d.text((24, y), key + ":", font=fm, fill=(120, 190, 210))
            d.text((24 + d.textlength(key + ":", font=fm), y), val, font=fm, fill=(210, 170, 120) if '"' in val or "[" in val else (196, 204, 218))
        else:
            d.text((24, y), text, font=fm, fill=color)
        y += 26
    # Right preview pane.
    d.text((pane_w + 24, 70), "PREVIEW", font=font(16), fill=(110, 118, 132))
    prev = pages_img.convert("RGB")
    pw = W - pane_w - 48
    ph = int(prev.height * pw / prev.width)
    img.paste(prev.resize((pw, ph), Image.LANCZOS), (pane_w + 24, 104))
    # Footer button.
    d.rounded_rectangle((24, H - 44, 150, H - 14), radius=6, fill=(30, 140, 70))
    d.text((44, H - 40), "Save & push", font=font(18), fill=(240, 245, 240))
    return img


def ken_burns(base: Image.Image, n: int, z0: float, z1: float) -> list[Image.Image]:
    frames = []
    for i in range(n):
        z = z0 + (z1 - z0) * (i / max(1, n - 1))
        cw, ch = int(W / z), int(H / z)
        x, y = (W - cw) // 2, (H - ch) // 2
        frames.append(base.crop((x, y, x + cw, y + ch)).resize((W, H), Image.LANCZOS))
    return frames


def hold(img: Image.Image, n: int) -> list[Image.Image]:
    return [img] * n


def xfade(a: Image.Image, b: Image.Image, n: int) -> list[Image.Image]:
    return [Image.blend(a, b, (i + 1) / (n + 1)) for i in range(n)]


def fade_from_black(img: Image.Image, n: int) -> list[Image.Image]:
    black = Image.new("RGB", img.size, (0, 0, 0))
    return [Image.blend(black, img, (i + 1) / n) for i in range(n)]


def build(deck_path: Path, icons: Path, out: Path) -> None:
    deck = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    pages = {p["id"]: p for p in deck["pages"]}

    def screen(pid: str, **kw) -> Image.Image:
        return rdp.render_page(deck, pages[pid], icons, **kw)

    hero = Image.open(out / "hero.png")
    pages_strip = Image.open(out / "pages.png")
    main = stage(screen("main"), caption="System shortcuts - your desktop, one tap away")
    tools = stage(screen("tools"), caption="Media control - play, skip, hold-to-ramp volume")
    obs_idle = stage(screen("obs", states={}), caption="OBS Studio control")
    obs_press = stage(screen("obs", states={}, pressed="record"), caption="OBS Studio control")
    obs_live = stage(screen("obs", live=True), caption="Live feedback - buttons mirror OBS in real time")
    editor = editor_mock(pages_strip)

    intro = title_card(hero, "A touchscreen control deck for your desk")
    outro = title_card(hero, "Open source - MicroPython device + Python host",
                       "make install   make setup   make run")

    frames: list[Image.Image] = []
    frames += fade_from_black(intro, 14)
    frames += hold(intro, 34)
    frames += xfade(intro, main, 12)
    frames += hold(main, 40)
    frames += xfade(main, tools, 12)
    frames += hold(tools, 40)
    frames += xfade(tools, obs_idle, 12)
    frames += hold(obs_idle, 26)
    frames += hold(obs_press, 12)
    frames += hold(obs_live, 60)
    frames += xfade(obs_live, editor, 14)
    frames += ken_burns(editor, 80, 1.0, 1.08)
    frames += xfade(ken_burns(editor, 2, 1.08, 1.08)[0], outro, 14)
    frames += hold(outro, 40)
    frames += [Image.blend(outro, Image.new("RGB", (W, H), (0, 0, 0)), (i + 1) / 12) for i in range(12)]

    tmp = out / "_frames"
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("*.png"):
        old.unlink()
    for i, fr in enumerate(frames):
        fr.save(tmp / f"f{i:04d}.png")
    dur = len(frames) / FPS
    print(f"{len(frames)} frames (~{dur:.1f}s)")

    mp4 = out / "demo.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
        "-i", str(tmp / "f%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-vf", "scale=1280:720", str(mp4),
    ], check=True)
    print(f"wrote {mp4}")

    gif = out / "demo.gif"
    palette = tmp / "palette.png"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
        "-i", str(tmp / "f%04d.png"), "-vf", "fps=15,scale=640:-1:flags=lanczos,palettegen",
        str(palette),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
        "-i", str(tmp / "f%04d.png"), "-i", str(palette),
        "-lavfi", "fps=15,scale=640:-1:flags=lanczos[x];[x][1:v]paletteuse", str(gif),
    ], check=True)
    print(f"wrote {gif}")

    for f in tmp.glob("*.png"):
        f.unlink()
    tmp.rmdir()


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the PrestoDeck demo video.")
    ap.add_argument("--deck", default="host/config/deck.yaml")
    ap.add_argument("--icons", default="host/config/icons")
    ap.add_argument("--out", default="assets/promo")
    args = ap.parse_args()
    build(Path(args.deck), Path(args.icons), Path(args.out))


if __name__ == "__main__":
    main()
