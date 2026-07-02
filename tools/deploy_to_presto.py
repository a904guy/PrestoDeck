"""Deploy the device/ tree to a connected Pimoroni Presto.

Thin wrapper around :mod:`prestodeck_host.deploy`, which also backs the
``prestodeck-deploy`` console script installed with the host package. Use this
script to run the deploy directly from a checkout::

    python tools/deploy_to_presto.py [PORT] [--device-dir DIR] [--mpremote PATH]

Requires the host package to be importable (``pip install -e host``).
"""

from __future__ import annotations

import sys

from prestodeck_host.deploy import main

if __name__ == "__main__":
    sys.exit(main())
