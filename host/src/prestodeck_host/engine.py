"""Action engine.

Resolves a ``button_press`` to the action configured for that page/button and
executes it with an :class:`~prestodeck_host.actions.base.ActionContext`,
isolating failures so one bad action never takes down the session.
"""

from __future__ import annotations

from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.config import DeckConfig
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)


class ActionEngine:
    """Routes button presses to their configured actions."""

    def __init__(self, config: DeckConfig) -> None:
        self._config = config

    def set_config(self, config: DeckConfig) -> None:
        """Swap in a reloaded config in place so existing sessions see it."""
        self._config = config

    def lookup(self, page_id: str, button_id: str) -> Action | None:
        """Return the action configured for ``page_id``/``button_id``, or ``None``."""
        for page in self._config.pages:
            if page.id == page_id:
                for button in page.buttons:
                    if button.id == button_id:
                        return button.action
        return None

    async def dispatch(
        self, page_id: str, button_id: str, ctx: ActionContext
    ) -> ActionResult | None:
        """Execute the action for ``page_id``/``button_id``; isolate failures.

        :returns: the :class:`ActionResult`, or ``None`` if no action is configured.
        """
        action = self.lookup(page_id, button_id)
        if action is None:
            _logger.info("no action configured for %s/%s", page_id, button_id)
            return None
        try:
            result = await action.execute(ctx)
        except NotImplementedError as exc:
            _logger.warning("action %s/%s not implemented: %s", page_id, button_id, exc)
            return ActionResult(ok=False, detail=str(exc))
        except Exception as exc:  # one bad action must not kill the session
            _logger.exception("action %s/%s raised: %s", page_id, button_id, exc)
            return ActionResult(ok=False, detail=str(exc))
        _logger.info(
            "action %s/%s -> ok=%s %s", page_id, button_id, result.ok, result.detail
        )
        return result
