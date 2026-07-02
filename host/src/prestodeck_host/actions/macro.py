"""Macro action: run an ordered sequence of sub-actions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from pydantic import PrivateAttr, model_validator

from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.log import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

_logger = get_logger(__name__)


class MacroAction(Action):
    """Run ``steps`` in order, sleeping ``delay_ms`` between them.

    Steps are stored as raw mappings and parsed into typed actions at validation
    time (so an invalid sub-action is rejected when the deck loads), then run in
    sequence at execution time.
    """

    type: Literal["macro"]
    steps: list[dict[str, Any]]
    delay_ms: int | None = None

    _parsed: Sequence[Action] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _parse_steps(self) -> MacroAction:
        # Lazy import avoids an import cycle: the action union lives in the
        # package __init__, which imports this module.
        from prestodeck_host.actions import parse_action

        self._parsed = [parse_action(step) for step in self.steps]
        return self

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Execute each parsed step in order with the configured inter-step delay."""
        ok_all = True
        for index, step in enumerate(self._parsed):
            if index > 0 and self.delay_ms:
                await asyncio.sleep(self.delay_ms / 1000)
            result = await step.execute(ctx)
            ok_all = ok_all and result.ok
        _logger.info("macro ran %d step(s), ok=%s", len(self._parsed), ok_all)
        return ActionResult(ok=ok_all, detail=f"macro {len(self._parsed)} steps")
