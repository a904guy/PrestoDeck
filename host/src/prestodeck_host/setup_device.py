"""Guided first-time setup for a Pimoroni Presto.

Backs the ``prestodeck-setup`` console script. This is the friendly,
one-command path for getting a brand-new Presto running PrestoDeck: it

  1. finds the Presto on USB,
  2. asks for your 2.4 GHz WiFi name and password,
  3. writes them to the board as ``secrets.py`` (never committed, never logged),
  4. copies the PrestoDeck firmware onto the board, and
  5. resets it so it boots straight into PrestoDeck.

Then you just run ``prestodeck-host`` on this computer and power-cycle the
Presto. Re-run this any time you change WiFi networks.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from prestodeck_host.deploy import (
    autodetect_port,
    deploy,
    find_device_dir,
    reset_board,
)

logger = logging.getLogger("prestodeck.setup")


def render_secrets(ssid: str, password: str) -> str:
    """Return the ``secrets.py`` body for the given credentials (safely quoted)."""
    return (
        "# WiFi credentials written by `prestodeck-setup`. Do not commit this file.\n"
        f"WIFI_SSID = {json.dumps(ssid)}\n"
        f"WIFI_PASSWORD = {json.dumps(password)}\n"
    )


def write_secrets(port: str, ssid: str, password: str, mpremote: str = "mpremote") -> None:
    """Push a generated ``secrets.py`` with the WiFi credentials to the board."""
    body = render_secrets(ssid, password)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(body)
        tmp_path = handle.name
    try:
        logger.info("writing WiFi credentials to the board (secrets.py)")
        subprocess.run(
            [mpremote, "connect", port, "fs", "cp", tmp_path, ":secrets.py"],
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _prompt_credentials() -> tuple[str, str]:
    """Interactively read the WiFi SSID and password from the terminal."""
    print("PrestoDeck setup -- let's get your Presto on WiFi.\n")
    print("Note: the Presto only joins 2.4 GHz networks (not 5 GHz).\n")
    ssid = input("WiFi network name (SSID): ").strip()
    while not ssid:
        ssid = input("Please enter a network name: ").strip()
    password = getpass.getpass("WiFi password (hidden): ")
    return ssid, password


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the setup tool."""
    parser = argparse.ArgumentParser(
        prog="prestodeck-setup",
        description="Put WiFi credentials on a Presto and install the PrestoDeck firmware.",
    )
    parser.add_argument("--port", default=None, help="Serial port (autodetected when omitted).")
    parser.add_argument("--ssid", default=None, help="WiFi SSID (prompted when omitted).")
    parser.add_argument(
        "--password", default=None, help="WiFi password (prompted, hidden, when omitted)."
    )
    parser.add_argument(
        "--device-dir", default=None, help="Path to the device firmware tree (autodetected)."
    )
    parser.add_argument("--mpremote", default="mpremote", help="Path to the mpremote executable.")
    parser.add_argument(
        "--skip-firmware",
        action="store_true",
        help="Only update WiFi credentials; do not re-copy the firmware.",
    )
    return parser


def main() -> int:
    """Entry point: collect credentials, push them, deploy firmware, and reset."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()

    port = args.port or autodetect_port(args.mpremote)
    if port is None:
        logger.error(
            "no Presto found on USB. Plug it in with a data USB cable and try again "
            "(or pass --port)."
        )
        return 1
    logger.info("using Presto on %s", port)

    device_dir = None
    if not args.skip_firmware:
        device_dir = find_device_dir(args.device_dir)
        if device_dir is None:
            logger.error(
                "could not find the device/ firmware tree; run from the repo "
                "(or host/) or pass --device-dir (or --skip-firmware)"
            )
            return 2

    ssid = args.ssid
    password = args.password
    if ssid is None or password is None:
        prompted_ssid, prompted_password = _prompt_credentials()
        ssid = ssid or prompted_ssid
        password = prompted_password if password is None else password

    try:
        write_secrets(port, ssid, password, args.mpremote)
        if device_dir is not None:
            deploy(device_dir, port, args.mpremote)
        reset_board(port, args.mpremote)
    except FileNotFoundError:
        logger.error(
            "mpremote not found. Install it with `pip install mpremote` (it ships with "
            "the host's dev extras) and try again."
        )
        return 1
    except subprocess.CalledProcessError as exc:
        logger.error("a device command failed: %s", (exc.stderr or "").strip())
        return 1

    print("\nDone! Your Presto is set up.")
    print("Next: run `prestodeck-host` on this computer, then power-cycle the Presto.")
    print("It will join WiFi, find this host automatically, and show your deck.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
