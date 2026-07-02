"""Page model for PrestoDeck.

A page is a named collection of buttons (a deck screen). The device renders the
active page and routes touch points to its buttons. This module also provides
``make_test_page`` -- the hardcoded 2x2, four-button test deck used as the local
fallback when the host has not yet pushed a ``config``.

Layout math (``grid_rects``) is pure and host-testable.
"""

from . import ui
from .button import Button
from . import log


def grid_rects(cols, rows, screen_w, screen_h, margin, gap):
    """Compute button rectangles for a ``cols`` x ``rows`` grid. Pure.

    :param cols: number of columns.
    :param rows: number of rows.
    :param screen_w: panel width.
    :param screen_h: panel height.
    :param margin: outer margin in pixels.
    :param gap: inter-button gap in pixels.
    :returns: list of ``(x, y, w, h)`` tuples in row-major order.
    """
    usable_w = screen_w - 2 * margin - gap * (cols - 1)
    usable_h = screen_h - 2 * margin - gap * (rows - 1)
    bw = usable_w // cols
    bh = usable_h // rows
    rects = []
    for r in range(rows):
        for c in range(cols):
            x = margin + c * (bw + gap)
            y = margin + r * (bh + gap)
            rects.append((x, y, bw, bh))
    return rects


class Page:
    """A renderable screen of buttons identified by ``page_id``."""

    def __init__(self, page_id, title="", buttons=None, theme=ui.Theme):
        """Define a page's identity, title, child buttons, and theme.

        :param page_id: id unique within the session.
        :param title: optional page title.
        :param buttons: list of ``Button`` (defaults to empty).
        :param theme: colour theme to draw with (defaults to ``ui.Theme``).
        """
        self.page_id = page_id
        self.title = title
        self.buttons = buttons if buttons is not None else []
        self.theme = theme

    def button_at(self, px, py):
        """Return the button under a touch point, or ``None``. Pure.

        :param px: touch point x in pixels.
        :param py: touch point y in pixels.
        :returns: a ``Button`` or ``None``.
        """
        for button in self.buttons:
            if button.contains(px, py):
                return button
        return None

    def draw(self, surface, icons=None):
        """Clear the surface and draw every child button.

        :param surface: the ``RenderSurface`` to draw onto.
        :param icons: an ``IconCache`` (or ``None``) used to resolve button icons.
        """
        log.debug("Page.draw {0}".format(self.page_id))
        surface.clear(self.theme.BACKGROUND)
        for button in self.buttons:
            button.draw(surface, self.theme, icons)

    @classmethod
    def from_config(cls, payload, screen_w=ui.SCREEN_W, screen_h=ui.SCREEN_H):
        """Build the default page from a config payload (back-compat helper)."""
        pages, default_id = pages_from_config(payload, screen_w, screen_h)
        if default_id in pages:
            return pages[default_id]
        for page in pages.values():
            return page
        return cls("default", "", [], _theme_from_payload(payload.get("theme")))


def _theme_from_payload(theme_payload):
    """Derive a ``ui.Theme`` from the config ``theme`` block."""
    theme_payload = theme_payload or {}
    return ui.Theme.derive(
        background=theme_payload.get("background"),
        outline=theme_payload.get("default_outline_color"),
        label=theme_payload.get("default_label_color"),
    )


def _build_page(desc_page, theme, screen_w, screen_h):
    """Build one ``Page`` from a page descriptor, placing buttons by row/col."""
    page_id = desc_page.get("id", "default")
    descs = desc_page.get("buttons", [])
    grid = desc_page.get("grid") or [2, 2]
    rows = grid[0] if len(grid) > 0 else 2
    cols = grid[1] if len(grid) > 1 else 2
    rects = grid_rects(cols, rows, screen_w, screen_h, 24, 20)

    buttons = []
    for i, desc in enumerate(descs):
        row = desc.get("row", i // cols)
        col = desc.get("col", i % cols)
        idx = row * cols + col
        if idx < 0 or idx >= len(rects):
            idx = i
        if idx >= len(rects):
            break
        x, y, w, h = rects[idx]
        bid = desc.get("id", "b{0}".format(i))
        color = desc.get("color")
        if color is not None:
            color = tuple(color)
        buttons.append(
            Button(bid, x, y, w, h, desc.get("label", str(bid)), color,
                   desc.get("icon"), desc.get("navigate"), desc.get("repeat_ms"))
        )
    return Page(page_id, desc_page.get("title", ""), buttons, theme)


def pages_from_config(payload, screen_w=ui.SCREEN_W, screen_h=ui.SCREEN_H):
    """Build every page from a ``config`` payload.

    :param payload: the ``payload`` dict of a ``config`` message.
    :returns: tuple ``(pages_by_id, default_page_id)``.
    """
    theme = _theme_from_payload(payload.get("theme"))
    pages = {}
    for desc_page in payload.get("pages") or []:
        page = _build_page(desc_page, theme, screen_w, screen_h)
        pages[page.page_id] = page
    return pages, payload.get("default_page")


class StatusScreen:
    """A non-interactive full-screen status display (e.g. the connecting screen).

    Implements the same surface the render loop and touch poll expect (``page_id``,
    ``buttons``, ``button_at``, ``draw``) so it can be set as the active page, but
    it carries no buttons and renders a stack of centered text lines instead.
    """

    def __init__(self, lines, theme=ui.Theme):
        """Configure the status screen.

        :param lines: list of ``(text, scale)`` tuples drawn top to bottom.
        :param theme: theme providing background and text colours.
        """
        self.page_id = "__status__"
        self.buttons = []
        self.lines = lines
        self.theme = theme

    def button_at(self, px, py):
        """Status screens have no buttons. Always returns ``None``."""
        return None

    def draw(self, surface, icons=None):
        """Clear the surface and draw the status lines centered vertically."""
        surface.clear(self.theme.BACKGROUND)
        spacing = 46
        count = len(self.lines)
        top = ui.SCREEN_H // 2 - (count - 1) * spacing // 2
        for i, line in enumerate(self.lines):
            text, scale = line
            surface.text_centered(text, ui.SCREEN_W // 2, top + i * spacing, self.theme.TEXT, scale)


def make_connecting_screen(ip, status="Connecting...", theme=ui.Theme):
    """Build the connecting screen showing the status and the device IP.

    The IP is shown so an operator can hard-code it if discovery is unavailable.

    :param ip: the device's IP address string (may be empty).
    :param status: the status line to show (e.g. "Connecting to host").
    :param theme: theme to render with.
    :returns: a :class:`StatusScreen`.
    """
    return StatusScreen(
        [
            ("PrestoDeck", 4),
            (status, 3),
            ("IP " + (ip if ip else "no network"), 2),
        ],
        theme,
    )


def make_test_page(screen_w=ui.SCREEN_W, screen_h=ui.SCREEN_H):
    """Build the hardcoded 4-button (2x2) local test page.

    Used as the local fallback when no host ``config`` arrives in time.

    :param screen_w: panel width.
    :param screen_h: panel height.
    :returns: a ``Page`` with four labeled buttons.
    """
    rects = grid_rects(2, 2, screen_w, screen_h, 24, 20)
    labels = ["One", "Two", "Three", "Four"]
    buttons = [
        Button("btn{0}".format(i + 1), rects[i][0], rects[i][1], rects[i][2], rects[i][3], labels[i])
        for i in range(4)
    ]
    return Page("test", "Test Deck", buttons)
