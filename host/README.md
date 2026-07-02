# prestodeck-host

The host daemon for [PrestoDeck](https://github.com/a904guy/prestodeck) - a
self-hosted, network-coupled Stream Deck replacement built on a Pimoroni Presto.

`prestodeck-host` runs on your desktop and:

- serves a WebSocket endpoint the device connects to (port 7878),
- advertises itself over mDNS (`_prestodeck._tcp.local.`) for zero-config discovery,
- loads a human-editable `deck.yaml` (validated by Pydantic v2) and pushes the
  resolved layout + icons to the device,
- executes the configured action when a button is pressed (`shell`, `keystroke`,
  `text`, `http`, `media`, `macro`, `navigate`, `notify`, `toggle`, `obs`, plus
  Python entry-point plugins),
- hot-reloads on config changes, and
- serves a browser editor for the deck (port 8080 by default).

## Install

```bash
pip install -e ".[dev]"
```

## Run

```bash
prestodeck-host          # runs from any directory
```

On first run with no deck found, the host seeds an editable starter deck at
`~/.config/prestodeck/deck.yaml` and uses it (the path is printed at startup).
The deck file is resolved in this order: `--config PATH`, `$PRESTODECK_CONFIG`,
`./config/deck.yaml` or `./deck.yaml`, then `~/.config/prestodeck/deck.yaml`.
`--port`, `--web-port`, and `--bind` override the config. Edit the deck file (or
open `http://localhost:8080/ui`) and changes are pushed to the device live.

## Set up / deploy the device

```bash
prestodeck-setup         # guided: WiFi creds + firmware onto a USB-connected Presto
prestodeck-deploy --reset  # re-push the device/ tree and reset (for firmware changes)
```

See the [project README](https://github.com/a904guy/prestodeck) and `docs/`
for the protocol, config schema, and action-authoring guides.

## License

MIT.
