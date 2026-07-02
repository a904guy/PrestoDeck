"""Notify action: show a transient toast on the device."""

from __future__ import annotations

from typing import Literal

from prestodeck_host import protocol
from prestodeck_host.actions.base import Action, ActionContext, ActionResult


class NotifyAction(Action):
    """Send a transient toast to the originating device."""

    type: Literal["notify"]
    text: str
    duration_ms: int = 2000
    color: tuple[int, int, int] | None = None

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Send a ``notify`` frame with the text, duration, and optional colour."""
        await ctx.send_frame(
            protocol.make_notify(
                text=self.text,
                duration_ms=self.duration_ms,
                color=self.color,
            )
        )
        return ActionResult(ok=True, detail=f"notify: {self.text}")
