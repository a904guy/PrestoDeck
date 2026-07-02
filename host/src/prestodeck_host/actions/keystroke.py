"""Keystroke action: synthesize a key combination via pynput."""

from __future__ import annotations

from typing import Literal

from prestodeck_host.actions import _input
from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)


class KeystrokeAction(Action):
    """Send a key combination (e.g. ``"ctrl+shift+t"``) to the host."""

    type: Literal["keystroke"]
    combo: str

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Tap the configured combo. pynput faults are logged, not raised."""
        try:
            _input.tap_combo(self.combo)
        except Exception as exc:
            _logger.warning("keystroke %r failed: %s", self.combo, exc)
            return ActionResult(ok=False, detail=str(exc))
        return ActionResult(ok=True, detail=self.combo)
