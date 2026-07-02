"""On-device icon cache with sha256 sidecar integrity.

Button icons are streamed from the host and cached under ``/icons`` on the
device filesystem, keyed by their manifest name (e.g. ``play.png``). Each cached
image ``<name>`` is paired with a ``<name>.sha256`` sidecar recording the host's
content hash, so the device can skip re-fetching unchanged icons (and re-fetch
when the host's hash changes).
"""

import os

from . import log

# Filesystem root for cached icons on the device.
CACHE_DIR = "/icons"


class IconCache:
    """Filesystem-backed icon cache keyed by manifest name, validated by sha256."""

    def __init__(self, cache_dir=CACHE_DIR):
        """Configure the cache root and ensure it exists.

        :param cache_dir: filesystem path used to store cached icons.
        """
        self.cache_dir = cache_dir
        self._ensure_dir()

    def _ensure_dir(self):
        """Create the cache directory if it does not already exist."""
        try:
            os.stat(self.cache_dir)
        except OSError:
            try:
                os.mkdir(self.cache_dir)
            except OSError as exc:
                log.warn("mkdir {0} failed: {1}".format(self.cache_dir, exc))

    def path_for(self, name):
        """Return the on-disk path for icon ``name``. Pure; no I/O."""
        return self.cache_dir + "/" + name

    def _sidecar(self, name):
        """Return the sidecar path holding the cached icon's sha256."""
        return self.path_for(name) + ".sha256"

    def _exists(self, path):
        """Return whether ``path`` exists on the filesystem."""
        try:
            os.stat(path)
            return True
        except OSError:
            return False

    def present(self, name):
        """Return whether the icon file for ``name`` is on disk (any hash)."""
        return self._exists(self.path_for(name))

    def has(self, name, sha256):
        """Return whether ``name`` is cached AND its sidecar matches ``sha256``.

        :param name: manifest icon name.
        :param sha256: expected hex content hash from the host manifest.
        :returns: ``True`` only on a hash-verified cache hit.
        """
        if not self._exists(self.path_for(name)):
            return False
        try:
            with open(self._sidecar(name)) as fh:
                return fh.read().strip() == sha256
        except OSError:
            return False

    def store(self, name, data, sha256):
        """Write icon bytes then their sidecar, temp-and-rename for the image.

        :param name: manifest icon name.
        :param data: raw image bytes (already base64-decoded and verified).
        :param sha256: hex content hash to record in the sidecar.
        :returns: ``True`` on success.
        """
        try:
            tmp = self.path_for(name) + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.rename(tmp, self.path_for(name))
            with open(self._sidecar(name), "w") as fh:
                fh.write(sha256)
            return True
        except OSError as exc:
            log.error("icon store {0} failed: {1}".format(name, exc))
            return False
