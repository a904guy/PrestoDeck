"""Icon store tests: manifest hashing and chunked streaming."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from prestodeck_host import icons
from prestodeck_host.icons import IconStore


def _write_icon(icons_dir: Path, name: str, data: bytes) -> None:
    icons_dir.mkdir(exist_ok=True)
    (icons_dir / name).write_bytes(data)


def test_manifest_hashes_and_sizes(tmp_path: Path) -> None:
    """The manifest lists each png with its sha256 and byte size."""
    icons_dir = tmp_path / "icons"
    _write_icon(icons_dir, "a.png", b"hello")
    _write_icon(icons_dir, "b.png", b"world!!")
    _write_icon(icons_dir, "ignore.txt", b"nope")  # non-png ignored
    manifest = IconStore(icons_dir).manifest()
    assert [m["name"] for m in manifest] == ["a.png", "b.png"]
    assert manifest[0]["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert manifest[0]["size"] == 5


def test_chunks_reassemble_to_original(tmp_path: Path) -> None:
    """Chunks decode and concatenate back to the original bytes."""
    icons_dir = tmp_path / "icons"
    data = bytes(range(256)) * 40  # > one CHUNK_BYTES so multiple chunks
    _write_icon(icons_dir, "big.png", data)
    chunks = IconStore(icons_dir).chunks("big.png")
    assert chunks is not None
    assert len(chunks) > 1
    assert all(c["total"] == len(chunks) for c in chunks)
    ordered = sorted(chunks, key=lambda c: c["seq"])
    rebuilt = b"".join(base64.b64decode(c["data_b64"]) for c in ordered)
    assert rebuilt == data


def test_missing_and_unsafe_names(tmp_path: Path) -> None:
    """Absent icons and path-traversal names return None."""
    store = IconStore(tmp_path / "icons")
    assert store.read("does-not-exist.png") is None
    assert store.read("../secrets.py") is None
    assert store.chunks("nope.png") is None


def test_single_chunk_for_small_icon(tmp_path: Path) -> None:
    """A small icon produces exactly one chunk."""
    icons_dir = tmp_path / "icons"
    _write_icon(icons_dir, "s.png", b"x" * (icons.CHUNK_BYTES - 1))
    chunks = IconStore(icons_dir).chunks("s.png")
    assert chunks is not None and len(chunks) == 1
    assert chunks[0]["seq"] == 0 and chunks[0]["total"] == 1
