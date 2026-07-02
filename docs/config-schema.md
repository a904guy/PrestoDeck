# PrestoDeck Config Schema

Generated from the Pydantic v2 models in `prestodeck_host.config` by
`tools/gen_config_schema.py`. The deck is a single YAML file validated
against these models and resolved to JSON for the device. Pages and
buttons are addressed by string `id`.

Cross-field rules enforced by the loader: grid dimensions consistent with
button positions, no overlapping buttons, unique page ids, every `navigate`
action targets an existing page, and every referenced icon exists on disk.

`action` is one of the discriminated action types in
[action-authoring.md](action-authoring.md).

### `DeckConfig`

Top-level deck configuration document.

| field | type | required | default |
| --- | --- | --- | --- |
| `version` | `int` | yes |  |
| `host` | `HostConfig` | no | HostConfig(bind='0.0.0.0', port=7878, service_name='PrestoDeck', log_level='INFO', web_port=8080, obs=ObsConfig(enabled=False, url='ws://localhost:4455', password=None)) |
| `default_page` | `str` | yes |  |
| `theme` | `ThemeConfig` | no | ThemeConfig(background=[10, 10, 14], default_label_color=[240, 240, 240], default_outline_color=[60, 200, 200], font='lib/fonts/IBMPlexSans-Medium.af', corner_radius=12) |
| `pages` | `list[PageConfig]` | no | [] |

### `HostConfig`

Host-level networking and service settings.

| field | type | required | default |
| --- | --- | --- | --- |
| `bind` | `str` | no | '0.0.0.0' |
| `port` | `int` | no | 7878 |
| `service_name` | `str` | no | 'PrestoDeck' |
| `log_level` | `str` | no | 'INFO' |
| `web_port` | `int` | no | 8080 |
| `obs` | `ObsConfig` | no | ObsConfig(enabled=False, url='ws://localhost:4455', password=None) |

### `ObsConfig`

Connection settings for OBS Studio's obs-websocket server.

| field | type | required | default |
| --- | --- | --- | --- |
| `enabled` | `bool` | no | False |
| `url` | `str` | no | 'ws://localhost:4455' |
| `password` | `str | None` | no | None |

### `ThemeConfig`

Visual theme applied to rendered pages.

| field | type | required | default |
| --- | --- | --- | --- |
| `background` | `list[int]` | no | [10, 10, 14] |
| `default_label_color` | `list[int]` | no | [240, 240, 240] |
| `default_outline_color` | `list[int]` | no | [60, 200, 200] |
| `font` | `str` | no | 'lib/fonts/IBMPlexSans-Medium.af' |
| `corner_radius` | `int` | no | 12 |

### `PageConfig`

A page of buttons, addressed by string ``id``.

| field | type | required | default |
| --- | --- | --- | --- |
| `id` | `str` | yes |  |
| `grid` | `list[int]` | no | [4, 4] |
| `buttons` | `list[ButtonConfig]` | no | [] |

### `ButtonConfig`

A single button on a page grid.

| field | type | required | default |
| --- | --- | --- | --- |
| `id` | `str` | yes |  |
| `row` | `int` | yes |  |
| `col` | `int` | yes |  |
| `label` | `str` | no | '' |
| `icon` | `str | None` | no | None |
| `color` | `list[int] | None` | no | None |
| `led` | `LedConfig | None` | no | None |
| `action` | `Action (one of shell/keystroke/text/http/media/macro/navigate/notify/obs/python/toggle)` | no | None |
| `repeat_ms` | `int | None` | no | None |

### `LedConfig`

Per-button LED binding (the config layer).

| field | type | required | default |
| --- | --- | --- | --- |
| `index` | `int` | yes |  |
| `rgb` | `list[int]` | yes |  |

