"""FastAPI application for the web UI config editor.

Exposes the editor SPA at ``/ui`` and a small JSON/text API:

* ``GET  /api/deck``  -> current deck.yaml text
* ``PUT  /api/deck``  -> validate submitted YAML; write deck.yaml only if valid
  (the running config watcher then hot-reloads and pushes to devices). Invalid
  YAML returns 400 with a diagnostic and the on-disk file is left untouched.
* ``GET  /api/icons`` -> list of icon names
* ``POST /api/icons`` -> upload a .png icon

The server runs on its own port (``host.web_port``) so it never disturbs the
verified WebSocket transport on ``host.port``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from prestodeck_host import __version__
from prestodeck_host.config import DeckConfigError, load_deck, resolve_for_device
from prestodeck_host.icons import IconStore
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)

_STATIC = Path(__file__).parent / "static"


def create_app(deck_path: Path, icons_dir: Path, ws_port: int = 7878) -> FastAPI:
    """Build the web UI app bound to ``deck_path`` and ``icons_dir``.

    :param ws_port: the device WebSocket port, exposed to the browser so the
        live preview can connect to the host as a virtual device.
    """
    app = FastAPI(title="PrestoDeck", version=__version__)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/info")
    async def info() -> dict[str, Any]:
        """Runtime facts the browser needs (the device WebSocket port)."""
        return {"ws_port": ws_port, "version": __version__}

    @app.get("/ui", response_class=HTMLResponse)
    async def ui() -> str:
        return (_STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/deck", response_class=PlainTextResponse)
    async def get_deck() -> str:
        return deck_path.read_text(encoding="utf-8") if deck_path.is_file() else ""

    @app.put("/api/deck")
    async def put_deck(body: dict[str, str]) -> dict[str, object]:
        text = body.get("yaml", "")
        # Validate against a temp file (icon existence included). The live file is
        # only replaced once validation passes, so a bad edit cannot corrupt it.
        tmp = deck_path.parent / ".deck.validate.tmp"
        tmp.write_text(text, encoding="utf-8")
        try:
            config = load_deck(tmp, icons_dir)
        except DeckConfigError as exc:
            tmp.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        tmp.replace(deck_path)
        _logger.info("deck saved via web UI: %d page(s)", len(config.pages))
        return {"ok": True, "pages": len(config.pages)}

    @app.post("/api/deck/preview")
    async def preview(body: dict[str, str]) -> dict[str, Any]:
        """Validate submitted YAML without saving; return the resolved pages."""
        text = body.get("yaml", "")
        tmp = deck_path.parent / ".deck.preview.tmp"
        tmp.write_text(text, encoding="utf-8")
        try:
            config = load_deck(tmp, icons_dir)
        except DeckConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            tmp.unlink(missing_ok=True)
        return resolve_for_device(config, IconStore(icons_dir).manifest())

    @app.get("/api/icons")
    async def list_icons() -> list[str]:
        if not icons_dir.is_dir():
            return []
        return [p.name for p in sorted(icons_dir.iterdir()) if p.suffix.lower() == ".png"]

    @app.get("/api/icons/{name}")
    async def get_icon(name: str) -> FileResponse:
        """Serve one icon PNG so the preview can render real icons."""
        safe = Path(name).name
        path = icons_dir / safe
        if safe != name or not safe.lower().endswith(".png") or not path.is_file():
            raise HTTPException(status_code=404, detail="icon not found")
        return FileResponse(path, media_type="image/png")

    @app.post("/api/icons")
    async def upload_icon(file: UploadFile) -> dict[str, object]:
        name = Path(file.filename or "").name
        if not name.lower().endswith(".png"):
            raise HTTPException(status_code=400, detail="only .png icons are supported")
        icons_dir.mkdir(parents=True, exist_ok=True)
        (icons_dir / name).write_bytes(await file.read())
        _logger.info("icon uploaded via web UI: %s", name)
        return {"ok": True, "name": name}

    return app
