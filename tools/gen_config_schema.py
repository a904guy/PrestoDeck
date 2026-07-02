"""Generate docs/config-schema.md from the Pydantic config models.

Run from the repo root with the host package importable::

    python tools/gen_config_schema.py > docs/config-schema.md
"""

from __future__ import annotations

import typing

from prestodeck_host.config import (
    ButtonConfig,
    DeckConfig,
    HostConfig,
    LedConfig,
    ObsConfig,
    PageConfig,
    ThemeConfig,
)

_MODELS = [DeckConfig, HostConfig, ObsConfig, ThemeConfig, PageConfig, ButtonConfig, LedConfig]


def _type_name(annotation: object) -> str:
    if isinstance(annotation, type):
        return annotation.__name__
    text = str(annotation)
    if "discriminator='type'" in text:
        return "Action (one of shell/keystroke/text/http/media/macro/navigate/notify/obs/python/toggle)"
    text = text.replace("typing.", "").replace("prestodeck_host.config.", "")
    text = text.replace("prestodeck_host.actions.", "")
    return text.replace("NoneType", "None")


def _render(model: type) -> str:
    lines = [f"### `{model.__name__}`", ""]
    doc = (model.__doc__ or "").strip().splitlines()
    if doc:
        lines += [doc[0], ""]
    lines += ["| field | type | required | default |", "| --- | --- | --- | --- |"]
    for name, field in model.model_fields.items():
        required = "yes" if field.is_required() else "no"
        default = "" if field.is_required() else repr(_safe_default(field))
        ann = _type_name(field.annotation)
        lines.append(f"| `{name}` | `{ann}` | {required} | {default} |")
    lines.append("")
    return "\n".join(lines)


def _safe_default(field: typing.Any) -> object:
    if field.default_factory is not None:  # type: ignore[truthy-function]
        try:
            return field.default_factory()  # type: ignore[call-arg]
        except Exception:
            return "<factory>"
    return field.default


def main() -> None:
    out = [
        "# PrestoDeck Config Schema",
        "",
        "Generated from the Pydantic v2 models in `prestodeck_host.config` by",
        "`tools/gen_config_schema.py`. The deck is a single YAML file validated",
        "against these models and resolved to JSON for the device. Pages and",
        "buttons are addressed by string `id`.",
        "",
        "Cross-field rules enforced by the loader: grid dimensions consistent with",
        "button positions, no overlapping buttons, unique page ids, every `navigate`",
        "action targets an existing page, and every referenced icon exists on disk.",
        "",
        "`action` is one of the discriminated action types in",
        "[action-authoring.md](action-authoring.md).",
        "",
    ]
    for model in _MODELS:
        out.append(_render(model))
    print("\n".join(out))


if __name__ == "__main__":
    main()
