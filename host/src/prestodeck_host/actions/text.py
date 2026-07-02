"""Text-typing action: type a literal string via pynput."""

from __future__ import annotations

from typing import Literal

from prestodeck_host.actions import _input
from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)


class TextAction(Action):
    """Type a literal string at the host's cursor."""

    type: Literal["text"]
    text: str
    delay_ms: int | None = None

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Type ``text``. pynput faults are logged, not raised."""
        try:
            _input.type_text(self.text)
        except Exception as exc:
            _logger.warning("text type failed: %s", exc)
            return ActionResult(ok=False, detail=str(exc))
        return ActionResult(ok=True, detail=f"typed {len(self.text)} chars")
