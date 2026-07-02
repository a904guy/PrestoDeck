"""Deploy the device firmware tree to a connected Pimoroni Presto.

Backs the ``prestodeck-deploy`` console script. Pushes the contents of a
``device/`` tree onto a Presto over the USB serial REPL using ``mpremote``.
The Presto enumerates as USB VID:PID ``2e8a:0005``; the port is autodetected
from ``mpremote connect list`` when not given.

Usage::

    prestodeck-deploy [PORT] [--device-dir DIR] [--mpremote PATH]
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("prestodeck.deploy")

# USB VID:PID the Pimoroni Presto enumerates as.
PRESTO_VID_PID = "2e8a:0005"

# Files/directories under device/ we never push to the board: caches, OS cruft,
# and host-only dev files (tests, docs, credential templates).
_SKIP_NAMES = {"__pycache__", ".DS_Store", "tests", "conftest.py", "README.md"}


def _should_skip(entry: Path) -> bool:
    """Return whether a top-level ``device/`` entry is dev-only (not firmware)."""
    return entry.name in _SKIP_NAMES or entry.name.endswith(".example")


def find_device_dir(explicit: str | None = None) -> Path | None:
    """Locate the ``device/`` firmware tree.

    Honours ``explicit`` if given, else searches the current directory and its
    parents for a ``device/`` directory (so the tools work from the repo root or
    from ``host/``). Returns ``None`` if nothing is found.
    """
    if explicit:
        path = Path(explicit)
        return path if path.is_dir() else None
    here = Path.cwd()
    for base in (here, *here.parents):
        candidate = base / "device"
        if (candidate / "main.py").is_file():
            return candidate
    return None


def reset_board(port: str, mpremote: str = "mpremote") -> None:
    """Soft-reset the Presto so it re-runs ``boot.py`` / ``main.py``."""
    logger.info("resetting the board")
    _run([mpremote, "connect", port, "reset"])


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the deploy tool."""
    parser = argparse.ArgumentParser(description="Deploy device/ to a Presto via mpremote.")
    parser.add_argument(
        "port",
        nargs="?",
        default=None,
        help="Serial port of the Presto (autodetected when omitted).",
    )
    parser.add_argument(
        "--port",
        dest="port_flag",
        default=None,
        help="Serial port of the Presto (overrides the positional and autodetect).",
    )
    parser.add_argument(
        "--device-dir",
        default=None,
        help="Path to the device source tree to push (default: autodetected).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the board after deploying so it runs the new firmware.",
    )
    parser.add_argument(
        "--mpremote",
        default="mpremote",
        help="Path to the mpremote executable.",
    )
    return parser


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing text output, raising on non-zero exit."""
    logger.debug("exec: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def autodetect_port(mpremote: str = "mpremote") -> str | None:
    """Return the serial port of the first connected Presto, or ``None``.

    Parses ``mpremote connect list`` rows, matching the VID:PID column against
    :data:`PRESTO_VID_PID`.
    """
    try:
        result = _run([mpremote, "connect", "list"])
    except FileNotFoundError:
        logger.error("mpremote executable %r not found on PATH", mpremote)
        return None
    except subprocess.CalledProcessError as exc:
        logger.error("`mpremote connect list` failed: %s", exc.stderr.strip())
        return None

    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[2].lower() == PRESTO_VID_PID:
            logger.info("autodetected Presto on %s", fields[0])
            return fields[0]
    logger.error("no Presto (VID:PID %s) found among connected devices", PRESTO_VID_PID)
    return None


def _push_entries(mpremote: str, port: str, device_dir: Path) -> None:
    """Copy each top-level entry of ``device_dir`` onto the board recursively."""
    for entry in sorted(device_dir.iterdir()):
        if _should_skip(entry):
            continue
        src = f"{entry}/" if entry.is_dir() else str(entry)
        logger.info("pushing %s", entry.name)
        _run([mpremote, "connect", port, "fs", "cp", "-r", src, ":"])


def deploy(device_dir: Path, port: str, mpremote: str = "mpremote") -> None:
    """Push the full ``device_dir`` tree to the Presto at ``port``."""
    logger.info("deploying %s -> %s", device_dir, port)
    _push_entries(mpremote, port, device_dir)
    logger.info("deploy complete; reset the board to run main.py")


def main() -> int:
    """Entry point: resolve the port and push the device tree."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()

    device_dir = find_device_dir(args.device_dir)
    if device_dir is None:
        logger.error(
            "could not find the device/ firmware tree; run from the repo "
            "(or host/) or pass --device-dir"
        )
        return 2

    port = args.port_flag or args.port or autodetect_port(args.mpremote)
    if port is None:
        logger.error("no serial port available; pass one explicitly with --port")
        return 1

    try:
        deploy(device_dir, port, args.mpremote)
        if args.reset:
            reset_board(port, args.mpremote)
    except FileNotFoundError:
        logger.error("mpremote executable %r not found on PATH", args.mpremote)
        return 1
    except subprocess.CalledProcessError as exc:
        logger.error("mpremote command failed: %s", (exc.stderr or "").strip())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
