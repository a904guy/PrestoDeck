"""Button model, hit-testing, and rendering for PrestoDeck pages.

A button is a touchable rounded-rect region carrying a centered label. It tracks
a transient ``pressed`` state used both for the pressed visual and for
press/hold timing. Geometry and hit-testing are pure (host-testable); drawing
delegates to a ``RenderSurface``.
"""

from . import ui
from . import log


class Button:
    """A single interactive button within a page."""

    def __init__(
        self, button_id, x, y, w, h, label="", color=None, icon=None, navigate=None, repeat_ms=None
    ):
        """Define a button's identity, geometry, label, accent colour, and icon.

        :param button_id: id unique within the owning page.
        :param x: left coordinate in pixels.
        :param y: top coordinate in pixels.
        :param w: width in pixels.
        :param h: height in pixels.
        :param label: centered text label.
        :param color: per-button ``(r, g, b)`` accent colour, or ``None`` for the
            theme default. Drives the outline, the pressed-state fill, and the
            colour flashed across the back LEDs while the button is held.
        :param icon: manifest icon name (e.g. ``play.png``), or ``None``. Drawn
            from the device icon cache when present.
        :param navigate: target page id for a device-local navigate button, or
            ``None``. When set, pressing the button switches pages locally.
        :param repeat_ms: when set, holding the button re-fires its action every
            ``repeat_ms`` milliseconds (e.g. volume up/down). ``None`` disables
            auto-repeat so the button fires once per tap.
        """
        self.button_id = button_id
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.label = label
        self.color = color
        self.icon = icon
        self.navigate = navigate
        self.repeat_ms = repeat_ms
        self.pressed = False

    def contains(self, px, py):
        """Return whether a point lies within the button's bounds. Pure.

        :param px: touch point x in pixels.
        :param py: touch point y in pixels.
        :returns: ``True`` if ``(px, py)`` is inside this button.
        """
        return (self.x <= px < self.x + self.w) and (self.y <= py < self.y + self.h)

    def center(self):
        """Return the ``(cx, cy)`` center of the button. Pure."""
        return (self.x + self.w // 2, self.y + self.h // 2)

    def draw(self, surface, theme=ui.Theme, icons=None):
        """Render the button onto a ``RenderSurface``.

        Draws the body (pressed vs idle fill), a 2px outline, then either the
        cached icon (centered, with the label beneath) or just the centered
        label when no icon is cached.

        :param surface: the ``RenderSurface`` to draw onto.
        :param theme: theme providing colours and corner radius.
        :param icons: an ``IconCache`` (or ``None``) used to resolve icon files.
        """
        log.debug("Button.draw {0}".format(self.button_id))
        # The per-button colour drives the outline and the pressed-state fill;
        # idle fill stays the theme default so the accent reads as a border.
        outline = self.color if self.color is not None else theme.BUTTON_OUTLINE
        if self.pressed:
            fill = self.color if self.color is not None else theme.BUTTON_FILL_DOWN
        else:
            fill = theme.BUTTON_FILL
        # Outline drawn as a slightly larger rect behind the fill.
        surface.rounded_rect(
            self.x - 2, self.y - 2, self.w + 4, self.h + 4,
            theme.BUTTON_RADIUS + 2, outline,
        )
        surface.rounded_rect(self.x, self.y, self.w, self.h, theme.BUTTON_RADIUS, fill)
        cx, cy = self.center()
        drew_icon = False
        if self.icon and icons is not None and icons.present(self.icon):
            drew_icon = surface.draw_png(icons.path_for(self.icon), cx, cy - 14)
        if drew_icon:
            if self.label:
                surface.text_centered(self.label, cx, self.y + self.h - 26, theme.TEXT, scale=2)
        else:
            surface.text_centered(self.label, cx, cy, theme.TEXT)
