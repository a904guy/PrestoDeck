"""Deck configuration models, validation, loader, and device resolver.

The deck is described by a single YAML file validated by Pydantic v2 and
resolved to JSON for the device. Pages and buttons are addressed by string
``id``.

This module covers the deck schema and its cross-field semantic validation:
grid dimensions consistent with button positions, no overlapping buttons, every
``navigate`` action targets an existing page, and every referenced icon exists
on disk. ``action`` is a discriminated union over the action types validated by
the action engine.

On any error the loader raises :class:`DeckConfigError` carrying a structured,
human-readable diagnostic that points at the offending field (and the YAML line
for syntax errors) so the host can refuse to serve with a clear message.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from prestodeck_host.actions import AnyAction, NavigateAction


class _DeckLoader(yaml.SafeLoader):
    """YAML loader that does NOT treat on/off/yes/no as booleans (YAML 1.2-ish).

    Without this, toggle action keys ``on:`` and ``off:`` parse as the booleans
    ``True``/``False`` instead of the strings the schema expects.
    """


# Drop the implicit bool resolvers that start with o/y/n (on/off, yes/no) while
# keeping true/false and the null resolver.
for _ch in "oOyYnN":
    _resolvers = _DeckLoader.yaml_implicit_resolvers.get(_ch, [])
    _DeckLoader.yaml_implicit_resolvers[_ch] = [
        (tag, regexp) for tag, regexp in _resolvers if tag != "tag:yaml.org,2002:bool"
    ]

RGB = list[int]
"""An ``[r, g, b]`` colour triplet, each channel 0-255."""


class DeckConfigError(Exception):
    """A deck configuration that is syntactically or semantically invalid.

    The message is a multi-line, human-readable diagnostic suitable for logging
    and for surfacing to the operator.
    """


class ObsConfig(BaseModel):
    """Connection settings for OBS Studio's obs-websocket server."""

    enabled: bool = False
    url: str = "ws://localhost:4455"
    password: str | None = None


class HostConfig(BaseModel):
    """Host-level networking and service settings."""

    bind: str = "0.0.0.0"
    port: int = 7878
    service_name: str = "PrestoDeck"
    log_level: str = "INFO"
    web_port: int = 8080
    obs: ObsConfig = Field(default_factory=ObsConfig)


class ThemeConfig(BaseModel):
    """Visual theme applied to rendered pages."""

    background: RGB = Field(default_factory=lambda: [10, 10, 14])
    default_label_color: RGB = Field(default_factory=lambda: [240, 240, 240])
    default_outline_color: RGB = Field(default_factory=lambda: [60, 200, 200])
    font: str = "lib/fonts/IBMPlexSans-Medium.af"
    corner_radius: int = 12


class LedConfig(BaseModel):
    """Per-button LED binding (the config layer)."""

    index: int
    rgb: RGB


class ButtonConfig(BaseModel):
    """A single button on a page grid.

    ``action`` carries the action type discriminator plus its parameters; it is
    resolved against the action union.
    """

    id: str
    row: int
    col: int
    label: str = ""
    icon: str | None = None
    color: RGB | None = None
    led: LedConfig | None = None
    action: AnyAction | None = None
    # When set, holding the button re-fires its action every ``repeat_ms``
    # milliseconds (e.g. volume up/down). Absent means fire once per tap.
    repeat_ms: int | None = Field(default=None, gt=0)


class PageConfig(BaseModel):
    """A page of buttons, addressed by string ``id``.

    ``grid`` is ``[rows, cols]``. Cross-field checks (in-bounds positions, no
    overlaps) run in :meth:`_check_grid`.
    """

    id: str
    grid: list[int] = Field(default_factory=lambda: [4, 4])
    buttons: list[ButtonConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_grid(self) -> PageConfig:
        if len(self.grid) != 2 or self.grid[0] < 1 or self.grid[1] < 1:
            raise ValueError("grid must be [rows, cols] with both >= 1")
        rows, cols = self.grid[0], self.grid[1]
        seen: set[tuple[int, int]] = set()
        for button in self.buttons:
            if not (0 <= button.row < rows and 0 <= button.col < cols):
                raise ValueError(
                    f"button {button.id!r} at ({button.row},{button.col}) is "
                    f"outside the {rows}x{cols} grid"
                )
            cell = (button.row, button.col)
            if cell in seen:
                raise ValueError(
                    f"button {button.id!r} overlaps another button at cell {cell}"
                )
            seen.add(cell)
        return self


class DeckConfig(BaseModel):
    """Top-level deck configuration document."""

    version: int
    host: HostConfig = Field(default_factory=HostConfig)
    default_page: str
    theme: ThemeConfig = Field(default_factory=ThemeConfig)
    pages: list[PageConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> DeckConfig:
        page_ids = [page.id for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("duplicate page id(s) in pages")
        if self.default_page not in page_ids:
            raise ValueError(
                f"default_page {self.default_page!r} does not match any page id"
            )
        for page in self.pages:
            for button in page.buttons:
                action = button.action
                if isinstance(action, NavigateAction) and action.page not in page_ids:
                    raise ValueError(
                        f"button {button.id!r} navigates to unknown page "
                        f"{action.page!r}"
                    )
        return self


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["deck configuration failed validation:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  - at {loc}: {err['msg']}")
    return "\n".join(lines)


def load_deck(path: Path, icons_dir: Path | None = None) -> DeckConfig:
    """Load, validate, and return the deck configuration at ``path``.

    :param path: path to ``deck.yaml``.
    :param icons_dir: directory holding icon assets; when given, every button
        ``icon`` must exist there.
    :raises DeckConfigError: with a structured, line/field-aware diagnostic on
        any syntax, schema, or semantic error.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeckConfigError(f"cannot read deck config {path}: {exc}") from exc

    try:
        raw = yaml.load(text, Loader=_DeckLoader)  # noqa: S506 - _DeckLoader is SafeLoader-based
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise DeckConfigError(f"deck config YAML syntax error{where}: {exc}") from exc

    if not isinstance(raw, dict):
        raise DeckConfigError("deck config must be a YAML mapping at the top level")

    try:
        deck = DeckConfig.model_validate(raw)
    except ValidationError as exc:
        raise DeckConfigError(_format_validation_error(exc)) from exc

    if icons_dir is not None:
        missing = _missing_icons(deck, icons_dir)
        if missing:
            listed = "\n".join(
                f"  - button {bid!r} references missing icon {icon!r}"
                for bid, icon in missing
            )
            raise DeckConfigError(
                f"referenced icons not found in {icons_dir}:\n{listed}"
            )
    return deck


def _resolve_button(button: ButtonConfig) -> dict[str, Any]:
    """Resolve one button to its device payload (display fields + navigate hint).

    Navigate is device-local, so the target page is sent to the device; all
    other actions stay on the host.
    """
    payload: dict[str, Any] = {
        "id": button.id,
        "row": button.row,
        "col": button.col,
        "label": button.label,
        "color": button.color,
        "icon": button.icon,
    }
    if button.repeat_ms is not None:
        payload["repeat_ms"] = button.repeat_ms
    if isinstance(button.action, NavigateAction):
        payload["navigate"] = button.action.page
    return payload


def _missing_icons(deck: DeckConfig, icons_dir: Path) -> list[tuple[str, str]]:
    missing: list[tuple[str, str]] = []
    for page in deck.pages:
        for button in page.buttons:
            if button.icon and not (icons_dir / button.icon).is_file():
                missing.append((button.id, button.icon))
    return missing


def resolve_for_device(deck: DeckConfig, icons_manifest: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve a validated deck into the device ``config`` payload.

    Only display-facing fields are sent to the device; actions stay on the host.

    :param deck: a validated :class:`DeckConfig`.
    :param icons_manifest: ``[{"name", "sha256", "size"}, ...]`` from the icon store.
    :returns: the ``config`` message payload as a plain ``dict``.
    """
    return {
        "version": deck.version,
        "default_page": deck.default_page,
        "theme": {
            "background": deck.theme.background,
            "default_label_color": deck.theme.default_label_color,
            "default_outline_color": deck.theme.default_outline_color,
            "corner_radius": deck.theme.corner_radius,
        },
        "pages": [
            {
                "id": page.id,
                "grid": page.grid,
                "buttons": [_resolve_button(button) for button in page.buttons],
            }
            for page in deck.pages
        ],
        "icons_manifest": icons_manifest,
    }
