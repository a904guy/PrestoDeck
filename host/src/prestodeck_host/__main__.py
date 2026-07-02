"""Console-script entry point for the PrestoDeck host daemon.

Running ``prestodeck-host`` (or ``python -m prestodeck_host``) configures
logging, loads and validates the deck configuration, starts the WebSocket
server, the mDNS advertiser, the config watcher, and the web editor, then runs
until interrupted (Ctrl-C / SIGTERM) and shuts everything down cleanly.

The host works from any directory. The deck file is resolved in this order:

1. ``--config PATH`` on the command line,
2. ``$PRESTODECK_CONFIG``,
3. ``./config/deck.yaml`` or ``./deck.yaml`` in the current directory,
4. ``~/.config/prestodeck/deck.yaml``.

If none exist, a starter deck (bundled with the package) is copied to
``~/.config/prestodeck/deck.yaml`` -- along with its icons -- and used, so a
fresh install runs out of the box and leaves you an editable file. Icons live in
an ``icons/`` directory beside the deck file. On any configuration error the host
logs a clear diagnostic and refuses to serve.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import shutil
from pathlib import Path

from prestodeck_host import __version__
from prestodeck_host.config import DeckConfig, DeckConfigError, load_deck
from prestodeck_host.discovery import Advertiser
from prestodeck_host.icons import IconStore
from prestodeck_host.log import configure_logging, get_logger
from prestodeck_host.server import Server
from prestodeck_host.watcher import ConfigWatcher
from prestodeck_host.webui.app import create_app

_logger = get_logger(__name__)

# Starter deck + icons shipped inside the package (used as the first-run default).
_DATA_DIR = Path(__file__).parent / "data"


def _user_config_path() -> Path:
    """Return ``~/.config/prestodeck/deck.yaml`` (respecting ``$XDG_CONFIG_HOME``)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "prestodeck" / "deck.yaml"


def _seed_user_config(dest: Path) -> None:
    """Copy the bundled starter deck and its icons to ``dest`` (and ``dest``/icons)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_DATA_DIR / "deck.example.yaml", dest)
    icons_src = _DATA_DIR / "icons"
    if icons_src.is_dir():
        icons_dest = dest.parent / "icons"
        icons_dest.mkdir(parents=True, exist_ok=True)
        for icon in icons_src.glob("*.png"):
            shutil.copyfile(icon, icons_dest / icon.name)
    _logger.info("seeded a starter deck at %s (edit it or use the web editor)", dest)


def _resolve_deck_path(cli_config: str | None) -> Path:
    """Resolve the deck file path; seed a user default on a fresh install.

    See the module docstring for the resolution order.
    """
    if cli_config:
        return Path(cli_config)
    env = os.environ.get("PRESTODECK_CONFIG")
    if env:
        return Path(env)
    for candidate in (Path("config/deck.yaml"), Path("deck.yaml"), _user_config_path()):
        if candidate.is_file():
            return candidate
    user_path = _user_config_path()
    _seed_user_config(user_path)
    return user_path


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the host daemon."""
    parser = argparse.ArgumentParser(
        prog="prestodeck-host",
        description="Run the PrestoDeck host daemon (WebSocket server, mDNS, web editor).",
    )
    parser.add_argument("--config", help="path to deck.yaml (default: autodetected)")
    parser.add_argument("--icons", help="path to the icons directory (default: <config dir>/icons)")
    parser.add_argument("--port", type=int, help="WebSocket port for devices (default from config)")
    parser.add_argument("--web-port", type=int, help="web editor port (default: from config)")
    parser.add_argument("--bind", help="address to bind the servers to (default: from config)")
    parser.add_argument("--version", action="version", version=f"prestodeck-host {__version__}")
    return parser


async def run(config: DeckConfig, icon_store: IconStore, deck_path: Path, icons_dir: Path) -> None:
    """Start the server, advertiser, config watcher, and web editor; serve until cancelled.

    Cleans up the watcher, web server, advertiser, and listener on the way out
    regardless of how the serve loop terminates.
    """
    import uvicorn

    obs_client = None
    if config.host.obs.enabled:
        from prestodeck_host.obs import ObsClient

        obs_client = ObsClient(config.host.obs.url, config.host.obs.password)
        _logger.info("OBS integration enabled -> %s", config.host.obs.url)

    server = Server(config, icon_store, obs=obs_client)
    advertiser = Advertiser(config.host.service_name, config.host.port)
    watcher = ConfigWatcher(deck_path, icons_dir, server.apply_config)

    web_app = create_app(deck_path, icons_dir, ws_port=config.host.port)
    web = uvicorn.Server(
        uvicorn.Config(
            web_app, host=config.host.bind, port=config.host.web_port, log_level="warning"
        )
    )

    ws_server = await server.start()
    await advertiser.start()
    watch_task = asyncio.create_task(watcher.watch_forever())
    web_task = asyncio.create_task(web.serve())
    obs_task = asyncio.create_task(obs_client.run()) if obs_client is not None else None
    _logger.info("web editor on http://localhost:%d/ui", config.host.web_port)
    try:
        await ws_server.serve_forever()
    finally:
        watch_task.cancel()
        web_task.cancel()
        if obs_task is not None:
            obs_task.cancel()
        ws_server.close()
        with contextlib.suppress(Exception):
            await ws_server.wait_closed()
        await advertiser.stop()


def _apply_overrides(config: DeckConfig, args: argparse.Namespace) -> None:
    """Apply command-line overrides onto the loaded config's host settings."""
    if args.port is not None:
        config.host.port = args.port
    if args.web_port is not None:
        config.host.web_port = args.web_port
    if args.bind is not None:
        config.host.bind = args.bind


def main() -> None:
    """Parse arguments, load the deck config, and run the daemon."""
    args = _build_parser().parse_args()
    configure_logging()
    _logger.info("PrestoDeck host v%s starting up", __version__)

    deck_path = _resolve_deck_path(args.config)
    icons_dir = Path(args.icons) if args.icons else deck_path.parent / "icons"
    try:
        config = load_deck(deck_path, icons_dir)
    except DeckConfigError as exc:
        _logger.error("refusing to serve, deck config is invalid:\n%s", exc)
        raise SystemExit(2) from exc

    _apply_overrides(config, args)
    logging.getLogger().setLevel(config.host.log_level.upper())

    _logger.info(
        "loaded deck %s: %d page(s), default=%s, icons=%s",
        deck_path,
        len(config.pages),
        config.default_page,
        icons_dir,
    )
    icon_store = IconStore(icons_dir)
    try:
        asyncio.run(run(config, icon_store, deck_path, icons_dir))
    except KeyboardInterrupt:
        _logger.info("interrupted; shutting down")


if __name__ == "__main__":
    main()
