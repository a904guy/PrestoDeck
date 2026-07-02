"""Built-in PrestoDeck actions and the action union.

Each module defines an :class:`~prestodeck_host.actions.base.Action` subtype.
``AnyAction`` is the Pydantic-discriminated union (on the ``type`` field) of all
built-in actions; :func:`parse_action` validates a raw mapping into the right
typed action. Third-party actions are distributed as packages registering entry
points under the ``prestodeck.actions`` group; see docs/action-authoring.md.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, TypeAdapter

from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.actions.http import HttpAction
from prestodeck_host.actions.keystroke import KeystrokeAction
from prestodeck_host.actions.macro import MacroAction
from prestodeck_host.actions.media import MediaAction
from prestodeck_host.actions.navigate import NavigateAction
from prestodeck_host.actions.notify import NotifyAction
from prestodeck_host.actions.obs import ObsAction
from prestodeck_host.actions.python import PythonAction
from prestodeck_host.actions.shell import ShellAction
from prestodeck_host.actions.text import TextAction
from prestodeck_host.actions.toggle import ToggleAction

# Discriminated union of all built-in actions, keyed by the ``type`` field.
_ACTION_TYPES = (
    ShellAction
    | KeystrokeAction
    | TextAction
    | HttpAction
    | MediaAction
    | MacroAction
    | NavigateAction
    | NotifyAction
    | ObsAction
    | PythonAction
    | ToggleAction
)
AnyAction = Annotated[_ACTION_TYPES, Field(discriminator="type")]

_ADAPTER: TypeAdapter[Action] = TypeAdapter(AnyAction)


def parse_action(data: dict[str, Any]) -> Action:
    """Validate a raw action mapping into a typed :class:`Action`.

    :raises pydantic.ValidationError: if ``data`` is not a valid action.
    """
    return _ADAPTER.validate_python(data)


__all__ = [
    "Action",
    "ActionContext",
    "ActionResult",
    "AnyAction",
    "HttpAction",
    "KeystrokeAction",
    "MacroAction",
    "MediaAction",
    "NavigateAction",
    "NotifyAction",
    "ObsAction",
    "PythonAction",
    "ShellAction",
    "TextAction",
    "ToggleAction",
    "parse_action",
]
