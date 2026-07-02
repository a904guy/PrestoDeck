# Authoring PrestoDeck Actions

Actions run on the **host** when a button is pressed. Each action is a Pydantic
model discriminated by its `type` field; the engine routes a `button_press` to
the action configured for that page/button and calls its `execute`.

## Built-in actions

| `type` | fields | behaviour |
| --- | --- | --- |
| `shell` | `cmd`, `cwd?`, `env?`, `timeout_s?` | Runs via `asyncio.create_subprocess_shell`; output to the log. |
| `keystroke` | `combo` | Sends a key combo (`"ctrl+shift+t"`) via uinput/ydotool/pynput. |
| `text` | `text`, `delay_ms?` | Types a string. |
| `http` | `method`, `url`, `headers?`, `json?`, `body?`, `timeout_s?` | Async via `httpx`; non-2xx logged, not raised. |
| `media` | `key` | `play_pause` / `next` / `prev` / `vol_up` / `vol_down` / `mute`. |
| `macro` | `steps: [action, ...]`, `delay_ms?` | Runs steps in order with a delay between them. |
| `navigate` | `page` | Host-driven page switch (device repaints, emits `page_changed`). Users can also swipe left/right without a button. |
| `notify` | `text`, `duration_ms?`, `color?` | Sends a transient toast to the device. |
| `toggle` | `id`, `on`, `off`, `initial?`, `on_label?`/`off_label?`, `on_color?`/`off_color?` | Alternates two sub-actions with persistent state; pushes `set_button_state`. |
| `obs` | `request`, request params, `feedback?`, `on_*`/`off_*` | Drives OBS over obs-websocket (see below). |
| `python` | `entry_point`, `args?` | Dispatches to a registered plugin (below). |

> YAML note: the toggle keys `on:` / `off:` are NOT booleans here - the deck
> loader treats `on`/`off`/`yes`/`no` as strings so they parse as action keys.

## Hold to repeat

Add `repeat_ms` to a button and holding it re-fires the action every `repeat_ms`
milliseconds until you lift - useful for volume, seeking, or brightness. There's
a short initial delay (~350 ms) before repeats start, so a normal tap still fires
exactly once and a swipe is never mistaken for a hold. Omit `repeat_ms` (the
default) for fire-once buttons.

```yaml
- id: vol_up
  row: 1
  col: 0
  label: "Vol +"
  repeat_ms: 120            # hold to keep raising the volume
  action: {type: media, key: vol_up}
```

## Controlling OBS

PrestoDeck talks to OBS Studio over its built-in **obs-websocket** server (OBS
28+). Enable it once in OBS via **Tools -> WebSocket Server Settings**, then turn
it on in your deck's `host` block:

```yaml
host:
  obs:
    enabled: true
    url: "ws://localhost:4455"   # default
    password: "your-obs-password"  # omit if auth is off
```

The host keeps one persistent connection to OBS (reconnecting if OBS isn't up
yet). Then any button can send an obs-websocket **request** - set `request` and
add the request's parameters as sibling keys:

```yaml
# Switch scenes
action: {type: obs, request: SetCurrentProgramScene, sceneName: "BRB"}
# Start/stop streaming or recording
action: {type: obs, request: ToggleStream}
action: {type: obs, request: ToggleRecord}
# Mute an audio input
action: {type: obs, request: ToggleInputMute, inputName: "Mic/Aux"}
# Show/hide a source in a scene (needs its sceneItemId) and save the replay buffer
action: {type: obs, request: SetSceneItemEnabled, sceneName: "Live", sceneItemId: 3, sceneItemEnabled: false}
action: {type: obs, request: SaveReplayBuffer}
```

The full request catalog is the [obs-websocket protocol reference](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md).

### Live state feedback

Add `feedback` and OBS will keep the button's appearance in sync with real OBS
state - even when you change it in OBS directly. Use the `on_*` / `off_*` fields
(same as `toggle`) for the two looks:

```yaml
- id: rec
  row: 0
  col: 0
  label: "Record"
  action:
    type: obs
    request: ToggleRecord
    feedback: record          # record | stream | replay | mute:<input> | scene:<name>
    on_label: "REC ON"
    on_color: [200, 0, 0]
    off_label: "Record"
    off_color: [60, 60, 60]
```

Feedback keys: `record`, `stream`, `replay` (output active), `mute:<inputName>`
(muted), and `scene:<sceneName>` (that scene is live). The correct state is
pushed when OBS connects, when the deck reloads, and whenever a device connects.

> Label note: the device renders labels with a bitmap font, so stick to plain
> ASCII. Symbols like `●`/`▶`/emoji won't render - convey state with the colour
> and a word (e.g. `REC ON`) instead.

## Writing a plugin action

Distribute your action as an installable Python package that registers an entry
point under the `prestodeck.actions` group. A plugin subclasses
`prestodeck_host.actions.base.Action`, declares its parameters as Pydantic
fields, and implements `execute`:

```python
# my_plugin/obs.py
from __future__ import annotations
from prestodeck_host.actions.base import Action, ActionContext, ActionResult

class OBSSceneAction(Action):
    scene: str = "BRB"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        # ... call OBS, send device frames via ctx.send_frame, read/write
        # per-device state via ctx.store ...
        return ActionResult(ok=True, detail=f"scene -> {self.scene}")
```

```toml
# my_plugin/pyproject.toml
[project.entry-points."prestodeck.actions"]
obs_scene = "my_plugin.obs:OBSSceneAction"
```

Install the plugin into the same environment as `prestodeck-host`, then invoke
it from `deck.yaml`:

```yaml
action:
  type: python
  entry_point: obs_scene
  args: {scene: "BRB"}
```

### `ActionContext`

`execute` receives an `ActionContext` with:

- `device_id`, `page`, `button` - the originating press,
- `send` / `send_frame(envelope)` - push a frame back to the device,
- `event` - the raw press payload,
- `store` - a persistent `StateStore` (`get`/`set`), namespaced per device.

`execute` returns an `ActionResult(ok: bool, detail: str)`; the engine logs it
and isolates exceptions so one bad action never takes down the session.
