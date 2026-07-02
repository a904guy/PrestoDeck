"""Tests for the OBS client, the obs action, and the live-state feedback bridge.

Everything runs against a mock obs-websocket server (``tests/mock_obs.py``), so
the real handshake/auth, request/response, and event paths are exercised without
a running OBS.
"""

from __future__ import annotations

import asyncio
import hashlib
from base64 import b64encode

import pytest

from prestodeck_host.actions.base import ActionContext
from prestodeck_host.actions.obs import ObsAction
from prestodeck_host.config import ButtonConfig, PageConfig
from prestodeck_host.obs import ObsClient, build_auth
from prestodeck_host.obs_feedback import FeedbackBinding, ObsFeedback, bindings_from_config
from tests.mock_obs import MockOBS


async def _wait_for(predicate, timeout: float = 3.0) -> None:
    """Poll ``predicate`` until true or fail the test on timeout."""
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met within timeout")


def test_build_auth_matches_spec() -> None:
    """build_auth follows base64(sha256(base64(sha256(pw+salt)) + challenge))."""
    secret = b64encode(hashlib.sha256(b"pw" + b"salt").digest()).decode()
    expected = b64encode(hashlib.sha256((secret + "chal").encode()).digest()).decode()
    assert build_auth("pw", "salt", "chal") == expected


async def test_request_roundtrip() -> None:
    """A request reaches OBS and its response data comes back."""
    mock = MockOBS(responses={"GetVersion": {"obsVersion": "30.1.0"}})
    url = await mock.start()
    client = ObsClient(url)
    task = asyncio.create_task(client.run())
    try:
        await _wait_for(lambda: client.connected)
        data = await client.request("GetVersion")
        assert data == {"obsVersion": "30.1.0"}
        assert mock.requests[-1][0] == "GetVersion"
    finally:
        task.cancel()
        await mock.stop()


async def test_authenticated_connect() -> None:
    """The client authenticates when OBS requires a password."""
    mock = MockOBS(password="hunter2")
    url = await mock.start()
    client = ObsClient(url, password="hunter2")
    task = asyncio.create_task(client.run())
    try:
        await _wait_for(lambda: client.connected)
        assert client.connected
    finally:
        task.cancel()
        await mock.stop()


async def test_obs_action_sends_request() -> None:
    """The obs action forwards request + extra keys and reports success."""
    action = ObsAction.model_validate(
        {"type": "obs", "request": "SetCurrentProgramScene", "sceneName": "BRB"}
    )
    assert action.request_data() == {"sceneName": "BRB"}

    sent: list[tuple[str, dict]] = []

    class _FakeObs:
        connected = True

        async def request(self, request_type, data=None):
            sent.append((request_type, data))
            return {}

    ctx = ActionContext(device_id="d", page="p", button="b", send=_noop, obs=_FakeObs())
    result = await action.execute(ctx)
    assert result.ok
    assert sent == [("SetCurrentProgramScene", {"sceneName": "BRB"})]


async def test_obs_action_without_connection_fails() -> None:
    """The obs action reports failure (not crash) when OBS is unavailable."""
    action = ObsAction.model_validate({"type": "obs", "request": "ToggleRecord"})
    ctx = ActionContext(device_id="d", page="p", button="b", send=_noop, obs=None)
    result = await action.execute(ctx)
    assert not result.ok


def test_bindings_from_config() -> None:
    """Only obs actions with a feedback key produce feedback bindings."""
    page = PageConfig(
        id="live",
        grid=[1, 2],
        buttons=[
            ButtonConfig.model_validate(
                {
                    "id": "rec", "row": 0, "col": 0,
                    "action": {
                        "type": "obs", "request": "ToggleRecord", "feedback": "record",
                        "on_label": "REC", "on_color": [200, 0, 0],
                    },
                }
            ),
            ButtonConfig.model_validate(
                {"id": "scene", "row": 0, "col": 1,
                 "action": {"type": "obs", "request": "SetCurrentProgramScene", "sceneName": "A"}},
            ),
        ],
    )
    bindings = bindings_from_config([page])
    assert len(bindings) == 1
    assert bindings[0].key == "record"
    assert bindings[0].on_color == (200, 0, 0)


async def test_feedback_reflects_events_and_resync() -> None:
    """Feedback pushes off-state on resync, then on-state when OBS emits an event."""
    mock = MockOBS(responses={"GetRecordStatus": {"outputActive": False}})
    url = await mock.start()
    client = ObsClient(url)
    pushed: list[tuple[str, str, dict]] = []

    async def push(page: str, button: str, state: dict) -> None:
        pushed.append((page, button, state))

    binding = FeedbackBinding(
        page="live", button="rec", key="record",
        on_label="REC", off_label="Record",
        on_color=(200, 0, 0), off_color=(60, 60, 60),
    )
    ObsFeedback(client, lambda: [binding], push)
    task = asyncio.create_task(client.run())
    try:
        await _wait_for(lambda: client.connected)
        # on_connect -> resync -> GetRecordStatus False -> off appearance pushed
        await _wait_for(lambda: any(s.get("label") == "Record" for _, _, s in pushed))
        # OBS starts recording -> on appearance pushed
        await mock.emit("RecordStateChanged", {"outputActive": True})
        await _wait_for(lambda: any(s.get("label") == "REC" for _, _, s in pushed))
        on_push = [p for p in pushed if p[2].get("label") == "REC"][-1]
        assert on_push[0] == "live" and on_push[1] == "rec"
        assert on_push[2]["color"] == [200, 0, 0]
    finally:
        task.cancel()
        await mock.stop()


async def _noop(_message) -> None:
    pass


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
