"""Navigate action: ask the device to switch pages.

Page switching is device-local: the device changes pages itself on tap (or on a
left/right swipe) and tells the host via ``page_changed``. This action lets the
host *drive* a page change -- or a button explicitly bound to ``navigate`` -- by
sending a ``set_page`` frame the device acts on.
"""

from __future__ import annotations

from typing import Literal

from prestodeck_host import protocol
from prestodeck_host.actions.base import Action, ActionContext, ActionResult


class NavigateAction(Action):
    """Switch the device to another page by id."""

    type: Literal["navigate"]
    page: str

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Send a ``set_page`` frame targeting :attr:`page`."""
        await ctx.send_frame(protocol.make_set_page(page=self.page))
        return ActionResult(ok=True, detail=f"navigate -> {self.page}")
