"""PicoGraphics-backed render surface and theme for PrestoDeck.

Wraps the Presto display + its PicoGraphics drawing surface into one
``RenderSurface`` that pages and buttons draw onto. The display is constructed
in ``boot.py``/``main.py`` from ``presto.Presto(...)``; the PicoGraphics
surface is obtained from the Presto object (firmware exposes ``presto.display``
on the constructed instance). Colours are created via ``create_pen``.

The Presto/PicoGraphics modules are device-frozen, so direct imports here are
avoided; the live objects are injected. Theme constants are plain RGB tuples so
they remain host-importable for tests.
"""

from . import log

# Target panel geometry for this build (480x480 full-res Presto).
SCREEN_W = 480
SCREEN_H = 480


class Theme:
    """Colour theme for the test deck, as RGB tuples (host-safe constants)."""

    BACKGROUND = (16, 18, 24)       # near-black slate
    BUTTON_FILL = (38, 44, 60)      # idle button body
    BUTTON_FILL_DOWN = (70, 110, 200)  # pressed button body
    BUTTON_OUTLINE = (90, 100, 130)  # button border
    TEXT = (235, 238, 245)          # label text
    BUTTON_RADIUS = 18              # rounded-corner radius

    @classmethod
    def derive(cls, background=None, outline=None, label=None):
        """Return a theme instance overriding selected colours from host config.

        Instance attributes shadow the class constants, so unspecified colours
        keep their defaults. Accepts ``(r, g, b)`` sequences (e.g. JSON lists).

        :param background: page background colour, or ``None`` to keep default.
        :param outline: button outline colour, or ``None`` to keep default.
        :param label: label text colour, or ``None`` to keep default.
        :returns: a ``Theme`` instance usable anywhere ``Theme`` is.
        """
        theme = cls()
        if background is not None:
            theme.BACKGROUND = tuple(background)
        if outline is not None:
            theme.BUTTON_OUTLINE = tuple(outline)
        if label is not None:
            theme.TEXT = tuple(label)
        return theme


class RenderSurface:
    """Drawable surface bound to the Presto PicoGraphics context.

    Holds the display object, caches pens for the theme colours, and exposes
    the primitives buttons/pages need: clear, rounded-rect, centered text, and
    present. Pens are created lazily on first ``bind_pens`` so a host import
    (no display) does not fail.
    """

    def __init__(self, display=None, width=SCREEN_W, height=SCREEN_H):
        """Bind to a PicoGraphics ``display`` and record panel geometry.

        :param display: PicoGraphics-like object (the Presto display surface).
        :param width: panel width in pixels.
        :param height: panel height in pixels.
        """
        self.display = display
        self.width = width
        self.height = height
        self._pens = {}
        self._png = None

    def pen(self, rgb):
        """Return (creating + caching) a PicoGraphics pen for an RGB tuple.

        :param rgb: an ``(r, g, b)`` tuple from the theme.
        :returns: the pen handle from ``display.create_pen``.
        """
        key = tuple(rgb)
        pen = self._pens.get(key)
        if pen is None:
            pen = self.display.create_pen(rgb[0], rgb[1], rgb[2])
            self._pens[key] = pen
        return pen

    def clear(self, rgb=Theme.BACKGROUND):
        """Clear the back buffer to a solid colour.

        :param rgb: clear colour as an ``(r, g, b)`` tuple.
        """
        self.display.set_pen(self.pen(rgb))
        self.display.clear()

    def rounded_rect(self, x, y, w, h, radius, rgb):
        """Fill a rounded rectangle in the given colour.

        :param x: left coordinate.
        :param y: top coordinate.
        :param w: width.
        :param h: height.
        :param radius: corner radius.
        :param rgb: fill colour ``(r, g, b)``.
        """
        self.display.set_pen(self.pen(rgb))
        # This PicoGraphics build has no rounded_rectangle, so compose one from a
        # cross of two rectangles plus four corner circles.
        r = radius
        if r * 2 > w:
            r = w // 2
        if r * 2 > h:
            r = h // 2
        if r <= 0:
            self.display.rectangle(x, y, w, h)
            return
        self.display.rectangle(x + r, y, w - 2 * r, h)
        self.display.rectangle(x, y + r, w, h - 2 * r)
        self.display.circle(x + r, y + r, r)
        self.display.circle(x + w - r - 1, y + r, r)
        self.display.circle(x + r, y + h - r - 1, r)
        self.display.circle(x + w - r - 1, y + h - r - 1, r)

    def dot(self, cx, cy, radius, rgb):
        """Fill a small circle (used for page indicator dots).

        :param cx: center x.
        :param cy: center y.
        :param radius: radius in pixels.
        :param rgb: fill colour ``(r, g, b)``.
        """
        self.display.set_pen(self.pen(rgb))
        self.display.circle(cx, cy, radius)

    def text_centered(self, text, cx, cy, rgb, scale=3):
        """Draw text centered on ``(cx, cy)``.

        Uses ``measure_text`` to compute the offset so the label is centered
        within its button. Falls back to a coarse width estimate if measurement
        is unavailable.

        :param text: label string.
        :param cx: center x.
        :param cy: center y.
        :param rgb: text colour ``(r, g, b)``.
        :param scale: bitmap font scale.
        """
        self.display.set_pen(self.pen(rgb))
        try:
            tw = self.display.measure_text(text, scale)
        except (AttributeError, TypeError):
            tw = len(text) * 6 * scale
        th = 8 * scale
        self.display.text(text, int(cx - tw / 2), int(cy - th / 2), self.width, scale)

    def draw_png(self, path, cx, cy):
        """Decode a cached PNG and draw it centered on ``(cx, cy)``.

        Uses ``pngdec`` (device-frozen, lazily imported and cached). Faults are
        swallowed so a bad/partial icon never breaks the render loop.

        :param path: filesystem path of the cached PNG.
        :param cx: center x in pixels.
        :param cy: center y in pixels.
        :returns: ``True`` if the icon was drawn.
        """
        try:
            from pngdec import PNG
        except ImportError:
            return False
        try:
            if self._png is None:
                self._png = PNG(self.display)
            self._png.open_file(path)
            w = self._png.get_width()
            h = self._png.get_height()
            self._png.decode(int(cx - w / 2), int(cy - h / 2))
            return True
        except Exception as exc:  # corrupt/partial icon, missing file, etc.
            log.warn("png decode failed {0}: {1}".format(path, exc))
            return False

    def present(self):
        """Push the back buffer to the physical panel.

        Delegates to the Presto update (driven by ``main.py`` via the wrapper
        passed in). Here we call PicoGraphics-level update if present; the
        Presto-level ``update`` is invoked by the render tick.
        """
        log.debug("RenderSurface.present")
        update = getattr(self.display, "update", None)
        if callable(update):
            update()
