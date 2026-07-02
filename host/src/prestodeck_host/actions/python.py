"""Python entry-point action: dispatch to a registered plugin action.

Resolves ``entry_point`` against the ``prestodeck.actions`` entry-point group,
validates that it is an :class:`Action` subclass, instantiates it with ``args``,
and executes it. This is the native extension surface.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any, Literal

from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)

ENTRY_POINT_GROUP = "prestodeck.actions"


class PythonAction(Action):
    """Invoke a registered ``prestodeck.actions`` entry point with ``args``."""

    type: Literal["python"]
    entry_point: str
    args: dict[str, Any] | None = None

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Resolve, validate, instantiate, and run the plugin action."""
        resolved = self._resolve()
        if resolved is None:
            return ActionResult(ok=False, detail=f"entry point {self.entry_point!r} not found")
        if not (isinstance(resolved, type) and issubclass(resolved, Action)):
            return ActionResult(
                ok=False, detail=f"entry point {self.entry_point!r} is not an Action subclass"
            )
        try:
            plugin = resolved.model_validate(self.args or {})
        except Exception as exc:
            _logger.warning("plugin %s failed to construct: %s", self.entry_point, exc)
            return ActionResult(ok=False, detail=str(exc))
        return await plugin.execute(ctx)

    def _resolve(self) -> Any:
        """Return the class registered under :attr:`entry_point`, or ``None``."""
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            if ep.name == self.entry_point:
                return ep.load()
        return None
