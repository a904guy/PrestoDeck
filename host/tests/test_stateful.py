"""Tests for stateful actions: toggle persistence and the python plugin action."""

from __future__ import annotations

from pathlib import Path

import pytest

from prestodeck_host.actions import parse_action
from prestodeck_host.actions.base import Action, ActionContext, ActionResult
from prestodeck_host.protocol import Envelope, MessageType
from prestodeck_host.state import StateStore


class _Recorder:
    def __init__(self) -> None:
        self.frames: list[Envelope] = []

    async def send(self, frame: Envelope) -> None:
        self.frames.append(frame)


def _toggle_spec() -> dict[str, object]:
    return {
        "type": "toggle",
        "id": "mic",
        "initial": False,
        "on": {"type": "notify", "text": "muted off"},
        "off": {"type": "notify", "text": "muted on"},
        "on_label": "On",
        "on_color": [0, 255, 0],
        "off_label": "Off",
        "off_color": [255, 0, 0],
    }


def test_state_store_persists(tmp_path: Path) -> None:
    """Values written to the store survive a reopen (restart)."""
    store = StateStore(tmp_path / "state.json")
    store.set("k", {"a": 1})
    assert StateStore(tmp_path / "state.json").get("k") == {"a": 1}
    assert StateStore(tmp_path / "state.json").get("missing", 7) == 7


async def test_toggle_flips_persists_and_updates_button(tmp_path: Path) -> None:
    """Toggle alternates state, persists it, and pushes set_button_state visuals."""
    path = tmp_path / "state.json"
    rec = _Recorder()
    ctx = ActionContext(
        device_id="dev", page="main", button="mic", send=rec.send, store=StateStore(path)
    )
    action = parse_action(_toggle_spec())

    # First press: off -> on, green "On".
    r1 = await action.execute(ctx)
    assert r1.ok and "-> on" in r1.detail
    sbs = next(f for f in reversed(rec.frames) if f.type is MessageType.SET_BUTTON_STATE)
    assert sbs.payload == {
        "page": "main",
        "button": "mic",
        "state": {"label": "On", "color": [0, 255, 0]},
    }
    assert StateStore(path).get("dev:mic") is True  # persisted

    # Second press: on -> off, red "Off".
    r2 = await action.execute(ctx)
    assert r2.ok and "-> off" in r2.detail
    sbs2 = next(f for f in reversed(rec.frames) if f.type is MessageType.SET_BUTTON_STATE)
    assert sbs2.payload["state"] == {"label": "Off", "color": [255, 0, 0]}
    assert StateStore(path).get("dev:mic") is False


async def test_toggle_state_survives_restart(tmp_path: Path) -> None:
    """A fresh ActionContext (simulated restart) reads the persisted toggle state."""
    path = tmp_path / "state.json"
    rec = _Recorder()
    ctx1 = ActionContext(
        device_id="dev", page="main", button="mic", send=rec.send, store=StateStore(path)
    )
    await parse_action(_toggle_spec()).execute(ctx1)  # -> on (True)

    # New store instance == process restart.
    ctx2 = ActionContext(
        device_id="dev", page="main", button="mic", send=rec.send, store=StateStore(path)
    )
    result = await parse_action(_toggle_spec()).execute(ctx2)
    assert "-> off" in result.detail  # continued from persisted True


class _EchoPlugin(Action):
    message: str = "hi"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        return ActionResult(ok=True, detail=f"echo:{self.message}")


class _FakeEntryPoint:
    def __init__(self, name: str, target: object) -> None:
        self.name = name
        self._target = target

    def load(self) -> object:
        return self._target


def _ctx() -> ActionContext:
    return ActionContext(device_id="dev", page="main", button="b", send=_Recorder().send)


async def test_python_action_dispatches_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The python action resolves an entry point and runs the plugin with args."""
    from prestodeck_host.actions import python as pymod

    monkeypatch.setattr(
        pymod, "entry_points", lambda group=None: [_FakeEntryPoint("echo", _EchoPlugin)]
    )
    action = parse_action({"type": "python", "entry_point": "echo", "args": {"message": "yo"}})
    result = await action.execute(_ctx())
    assert result.ok and result.detail == "echo:yo"


async def test_python_action_unknown_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown entry point yields a not-ok result, no crash."""
    from prestodeck_host.actions import python as pymod

    monkeypatch.setattr(pymod, "entry_points", lambda group=None: [])
    result = await parse_action({"type": "python", "entry_point": "nope"}).execute(_ctx())
    assert not result.ok and "not found" in result.detail


async def test_python_action_rejects_non_action(monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry point that is not an Action subclass is rejected."""
    from prestodeck_host.actions import python as pymod

    monkeypatch.setattr(
        pymod, "entry_points", lambda group=None: [_FakeEntryPoint("bad", dict)]
    )
    result = await parse_action({"type": "python", "entry_point": "bad"}).execute(_ctx())
    assert not result.ok and "not an Action subclass" in result.detail
