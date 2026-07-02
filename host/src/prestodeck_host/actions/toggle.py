"""Toggle action: alternate between two sub-actions with persistent state."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import PrivateAttr, model_validator

from prestodeck_host import protocol
from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)


class ToggleAction(Action):
    """Alternate between ``on`` and ``off`` sub-actions, tracking state on the host.

    State persists across host restarts (via ``ctx.store``, namespaced by
    device) and the button's label/colour are updated on the device through a
    ``set_button_state`` frame so the toggle's current state is visible.
    """

    type: Literal["toggle"]
    id: str
    on: dict[str, Any]
    off: dict[str, Any]
    initial: bool = False
    on_label: str | None = None
    off_label: str | None = None
    on_color: tuple[int, int, int] | None = None
    off_color: tuple[int, int, int] | None = None
    on_icon: str | None = None
    off_icon: str | None = None

    _on_action: Action = PrivateAttr()
    _off_action: Action = PrivateAttr()

    @model_validator(mode="after")
    def _parse_sub_actions(self) -> ToggleAction:
        from prestodeck_host.actions import parse_action

        self._on_action = parse_action(self.on)
        self._off_action = parse_action(self.off)
        return self

    def visual_for(self, is_on: bool) -> dict[str, Any]:
        """Return the ``set_button_state`` fields for the on/off appearance.

        Only the fields configured for that state are included, so unset
        properties keep the button's base label/colour/icon.
        """
        state: dict[str, Any] = {}
        label = self.on_label if is_on else self.off_label
        color = self.on_color if is_on else self.off_color
        icon = self.on_icon if is_on else self.off_icon
        if label is not None:
            state["label"] = label
        if color is not None:
            state["color"] = list(color)
        if icon is not None:
            state["icon"] = icon
        return state

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Flip state, run the matching sub-action, and push the new visual."""
        key = f"{ctx.device_id}:{self.id}"
        current = bool(ctx.store.get(key, self.initial)) if ctx.store is not None else self.initial
        new_state = not current

        sub = self._on_action if new_state else self._off_action
        result = await sub.execute(ctx)

        if ctx.store is not None:
            ctx.store.set(key, new_state)

        state = self.visual_for(new_state)
        if state:
            await ctx.send_frame(
                protocol.make_set_button_state(page=ctx.page, button=ctx.button, state=state)
            )

        label_state = "on" if new_state else "off"
        _logger.info("toggle %s -> %s", self.id, label_state)
        return ActionResult(ok=result.ok, detail=f"toggle {self.id} -> {label_state}")
