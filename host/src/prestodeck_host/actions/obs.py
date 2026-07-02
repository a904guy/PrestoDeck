"""OBS action: drive OBS Studio over its built-in obs-websocket v5 server.

A single generic action covers every OBS function: set ``request`` to any
obs-websocket request type and add its parameters as sibling keys, e.g.::

    action: {type: obs, request: SetCurrentProgramScene, sceneName: "BRB"}
    action: {type: obs, request: ToggleRecord}
    action: {type: obs, request: ToggleInputMute, inputName: "Mic/Aux"}

Optionally set ``feedback`` so the button reflects live OBS state (e.g. a record
button that glows red while recording); the feedback layer reads the ``on_*`` /
``off_*`` appearance from here. See :mod:`prestodeck_host.obs_feedback`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict

from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)

# Declared fields that are NOT part of the OBS request payload.
_NON_REQUEST_FIELDS = {
    "type", "request", "feedback",
    "on_label", "off_label", "on_color", "off_color", "on_icon", "off_icon",
}


class ObsAction(Action):
    """Send one obs-websocket request; extra keys become the request data."""

    model_config = ConfigDict(extra="allow")

    type: Literal["obs"]
    request: str
    # Reflect live OBS state on this button (see obs_feedback). One of:
    # ``record``, ``stream``, ``replay``, ``mute:<inputName>``, ``scene:<name>``.
    feedback: str | None = None
    on_label: str | None = None
    off_label: str | None = None
    on_color: tuple[int, int, int] | None = None
    off_color: tuple[int, int, int] | None = None
    on_icon: str | None = None
    off_icon: str | None = None

    def request_data(self) -> dict[str, Any]:
        """Return the OBS request payload (all keys except the declared ones)."""
        return {k: v for k, v in (self.model_extra or {}).items() if k not in _NON_REQUEST_FIELDS}

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Send the request to OBS and report the outcome."""
        if ctx.obs is None or not ctx.obs.connected:
            _logger.warning("obs action %r skipped: OBS not connected", self.request)
            return ActionResult(ok=False, detail="OBS not connected")
        try:
            await ctx.obs.request(self.request, self.request_data())
        except Exception as exc:
            _logger.warning("obs request %s failed: %s", self.request, exc)
            return ActionResult(ok=False, detail=f"obs {self.request} failed: {exc}")
        _logger.info("obs %s ok", self.request)
        return ActionResult(ok=True, detail=f"obs {self.request}")
