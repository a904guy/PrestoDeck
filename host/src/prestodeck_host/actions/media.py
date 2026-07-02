"""Media-control action: tap a media key via pynput."""

from __future__ import annotations

from typing import Literal

from prestodeck_host.actions import _input
from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)


class MediaAction(Action):
    """Send a media key: play_pause, next, prev, vol_up, vol_down, or mute."""

    type: Literal["media"]
    key: str

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Tap the configured media key. pynput faults are logged, not raised."""
        try:
            _input.tap_media(self.key)
        except Exception as exc:
            _logger.warning("media %r failed: %s", self.key, exc)
            return ActionResult(ok=False, detail=str(exc))
        return ActionResult(ok=True, detail=self.key)
