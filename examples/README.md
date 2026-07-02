# Example decks

Ready-to-run deck configs showing the range of what a page can be, from a single
full-screen button up to a packed 4x4 grid. Point the host at any of them:

```
prestodeck-host --config examples/single-button.yaml
```

Or copy one to `~/.config/prestodeck/deck.yaml` (or `host/config/deck.yaml`) and
edit from there. Every example is validated in CI against the real schema.

| File | Grid | What it is |
| --- | --- | --- |
| [single-button.yaml](single-button.yaml) | 1x1 | One full-screen push-to-mute toggle for video calls. |
| [streaming-3x3.yaml](streaming-3x3.yaml) | 3x3 | A full OBS control surface: scenes, record/stream, replay, mute (with live state feedback). |
| [launchpad-4x4.yaml](launchpad-4x4.yaml) | 4x4 | A dense desktop pad: app shortcuts, media transport, volume, clipboard. |
| [mixed-sizes.yaml](mixed-sizes.yaml) | 1x1 -> 4x4 | One deck whose pages each use a different grid; swipe between them. |

Previews of each are in the main [README](../README.md#example-decks).

Grids are `[rows, cols]` and every cell is optional, so a page can be any size
and shape you like. See [docs/deck-config.md](../docs/deck-config.md) for the
full configuration reference and [docs/action-authoring.md](../docs/action-authoring.md)
for the action catalog.

The `streaming-3x3.yaml` deck needs OBS with obs-websocket enabled and scenes /
inputs named to match (edit `sceneName` / `inputName` for your setup). The rest
run with no external setup.
