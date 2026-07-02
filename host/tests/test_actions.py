"""Unit tests for the built-in actions and the action engine.

Side effects are kept local and safe: shell actions write into tmp_path, http is
mocked, and the pynput-backed actions (keystroke/text/media) are patched so no
real input is injected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from prestodeck_host.actions import parse_action
from prestodeck_host.actions._input import parse_combo
from prestodeck_host.actions.base import ActionContext
from prestodeck_host.config import ButtonConfig, DeckConfig, PageConfig
from prestodeck_host.engine import ActionEngine
from prestodeck_host.protocol import Envelope, MessageType


class _Recorder:
    """Collects frames an action sends back to the device."""

    def __init__(self) -> None:
        self.frames: list[Envelope] = []

    async def send(self, frame: Envelope) -> None:
        self.frames.append(frame)


def _ctx(rec: _Recorder | None = None) -> ActionContext:
    rec = rec or _Recorder()
    return ActionContext(device_id="dev", page="main", button="b", send=rec.send)


async def test_shell_creates_file(tmp_path: Path) -> None:
    """A shell action runs and its side effect (a created file) is visible."""
    target = tmp_path / "out.txt"
    action = parse_action({"type": "shell", "cmd": f"echo hello > {target}"})
    result = await action.execute(_ctx())
    assert result.ok
    assert target.read_text().strip() == "hello"


async def test_shell_nonzero_exit_not_ok() -> None:
    """A non-zero shell exit yields a not-ok result with the return code."""
    result = await parse_action({"type": "shell", "cmd": "exit 3"}).execute(_ctx())
    assert not result.ok
    assert "rc=3" in result.detail


async def test_http_post_sends_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """An http action issues the configured method/url/json (httpx mocked)."""
    seen: dict[str, Any] = {}

    class _Resp:
        status_code = 204

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def request(self, method: str, url: str, **kwargs: Any) -> _Resp:
            seen.update(method=method, url=url, kwargs=kwargs)
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    action = parse_action(
        {"type": "http", "method": "post", "url": "http://x/y", "json": {"a": 1}}
    )
    result = await action.execute(_ctx())
    assert result.ok
    assert seen["method"] == "POST"
    assert seen["url"] == "http://x/y"
    assert seen["kwargs"]["json"] == {"a": 1}


def test_parse_combo() -> None:
    """A combo splits into modifiers and the final key."""
    assert parse_combo("ctrl+shift+t") == (["ctrl", "shift"], "t")
    assert parse_combo("space") == ([], "space")
    with pytest.raises(ValueError, match="empty"):
        parse_combo("  ")


async def test_keystroke_taps_combo(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keystroke action delegates to the input helper with its combo."""
    from prestodeck_host.actions import keystroke

    calls: list[str] = []
    monkeypatch.setattr(keystroke._input, "tap_combo", calls.append)
    result = await parse_action({"type": "keystroke", "combo": "ctrl+alt+t"}).execute(_ctx())
    assert result.ok
    assert calls == ["ctrl+alt+t"]


async def test_media_taps_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The media action delegates to the input helper with its key."""
    from prestodeck_host.actions import media

    calls: list[str] = []
    monkeypatch.setattr(media._input, "tap_media", calls.append)
    result = await parse_action({"type": "media", "key": "play_pause"}).execute(_ctx())
    assert result.ok
    assert calls == ["play_pause"]


async def test_text_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """The text action delegates to the input helper with its string."""
    from prestodeck_host.actions import text

    calls: list[str] = []
    monkeypatch.setattr(text._input, "type_text", calls.append)
    result = await parse_action({"type": "text", "text": "hi there"}).execute(_ctx())
    assert result.ok
    assert calls == ["hi there"]


async def test_navigate_sends_set_page() -> None:
    """A navigate action sends a set_page frame for the target page."""
    rec = _Recorder()
    result = await parse_action({"type": "navigate", "page": "macros"}).execute(_ctx(rec))
    assert result.ok
    assert rec.frames[0].type is MessageType.SET_PAGE
    assert rec.frames[0].payload == {"page": "macros"}


async def test_notify_sends_notify() -> None:
    """A notify action sends a notify frame with text and duration."""
    rec = _Recorder()
    action = parse_action({"type": "notify", "text": "hi", "duration_ms": 500})
    result = await action.execute(_ctx(rec))
    assert result.ok
    assert rec.frames[0].type is MessageType.NOTIFY
    assert rec.frames[0].payload["text"] == "hi"
    assert rec.frames[0].payload["duration_ms"] == 500


async def test_macro_runs_steps_in_order(tmp_path: Path) -> None:
    """A macro runs its steps sequentially with the configured delay."""
    seq = tmp_path / "seq.txt"
    action = parse_action(
        {
            "type": "macro",
            "delay_ms": 5,
            "steps": [
                {"type": "shell", "cmd": f"echo a >> {seq}"},
                {"type": "shell", "cmd": f"echo b >> {seq}"},
                {"type": "shell", "cmd": f"echo c >> {seq}"},
            ],
        }
    )
    result = await action.execute(_ctx())
    assert result.ok
    assert seq.read_text().split() == ["a", "b", "c"]


async def test_engine_dispatches_button_action(tmp_path: Path) -> None:
    """The engine resolves a page/button to its action and runs it."""
    target = tmp_path / "engine.txt"
    config = DeckConfig(
        version=1,
        default_page="main",
        pages=[
            PageConfig(
                id="main",
                grid=[1, 1],
                buttons=[
                    ButtonConfig.model_validate(
                        {
                            "id": "b1",
                            "row": 0,
                            "col": 0,
                            "action": {"type": "shell", "cmd": f"echo ok > {target}"},
                        }
                    )
                ],
            )
        ],
    )
    engine = ActionEngine(config)
    result = await engine.dispatch("main", "b1", _ctx())
    assert result is not None and result.ok
    assert target.read_text().strip() == "ok"
    # Unknown button -> no action, no crash.
    assert await engine.dispatch("main", "nope", _ctx()) is None


async def test_engine_isolates_unimplemented_action() -> None:
    """A not-yet-implemented action (python/toggle) is caught, not raised."""
    config = DeckConfig(
        version=1,
        default_page="main",
        pages=[
            PageConfig(
                id="main",
                grid=[1, 1],
                buttons=[
                    ButtonConfig.model_validate(
                        {
                            "id": "b1",
                            "row": 0,
                            "col": 0,
                            "action": {"type": "python", "entry_point": "x:y"},
                        }
                    )
                ],
            )
        ],
    )
    result = await ActionEngine(config).dispatch("main", "b1", _ctx())
    assert result is not None and not result.ok
