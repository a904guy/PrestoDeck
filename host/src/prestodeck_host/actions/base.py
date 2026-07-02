"""Action plugin contract.

Defines the base :class:`Action` model, the :class:`ActionContext` passed to
each execution, and the :class:`ActionResult` returned. Built-in actions and
third-party plugins (entry points under ``prestodeck.actions``) subclass
:class:`Action`, declare their parameters as Pydantic fields, and implement
``async def execute(self, ctx) -> ActionResult``.

``ActionContext`` carries a ``send`` coroutine (to push frames back to the
originating device) plus the press event identity, rather than a live ``Session``
reference, to keep this module free of import cycles.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from prestodeck_host.obs import ObsClient
    from prestodeck_host.protocol import Envelope
    from prestodeck_host.state import StateStore

# A coroutine that writes one frame to the originating device.
SendFrame = Callable[["Envelope"], Awaitable[None]]


@dataclass
class ActionContext:
    """Execution context handed to :meth:`Action.execute`."""

    device_id: str
    page: str
    button: str
    send: SendFrame
    event: dict[str, Any] = field(default_factory=dict)
    store: StateStore | None = None
    obs: ObsClient | None = None

    async def send_frame(self, message: Envelope) -> None:
        """Send a protocol frame back to the originating device."""
        await self.send(message)


@dataclass
class ActionResult:
    """Outcome of an action execution."""

    ok: bool = True
    detail: str = ""


class Action(BaseModel):
    """Base class for all actions.

    Subclasses declare their parameters as Pydantic fields and implement
    :meth:`execute`. The base raises so an unimplemented action fails loudly.
    """

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Run the action and return its result. Subclasses must override."""
        raise NotImplementedError("action subclasses must implement execute()")
