# PrestoDeck Configuration Guide

Your deck is described by a single YAML file, `deck.yaml`. The host reads it,
validates it, and streams the display parts to the Presto; button *actions* stay
and run on the host. This guide explains every part of that file, one section
per feature, so you can build your own layouts from scratch.

If you prefer clicking to typing, the host also serves a web editor at
`http://localhost:8080/ui` that writes this same file for you.

---

## 1. Where the file lives

The host looks for the deck in this order and uses the first it finds:

1. the `--config <path>` command-line flag,
2. the `PRESTODECK_CONFIG` environment variable,
3. `./config/deck.yaml` or `./deck.yaml` in the current directory,
4. `~/.config/prestodeck/deck.yaml`.

If none exist, it seeds an editable starter deck (with icons) at
`~/.config/prestodeck/deck.yaml` on first run. Icons live in an `icons/`
directory next to the deck file (or pass `--icons <dir>`).

The file is re-read automatically whenever you save it - see **Hot reload**.

---

## 2. Top-level document

Every deck is a YAML mapping with these top-level keys:

```yaml
version: 1              # required - schema version, always 1 today
host: { ... }           # optional - networking / OBS (section 4)
default_page: "main"    # required - which page shows at boot (section 5)
theme: { ... }          # optional - colours & shape (section 6)
pages: [ ... ]          # the screens of buttons (section 7)
```

Only `version` and `default_page` are strictly required; everything else has
sensible defaults. `default_page` **must** name a real page id or the deck is
rejected.

---

## 3. `version`

```yaml
version: 1
```

The configuration schema version. It exists so future changes can stay backward
compatible. Use `1`.

---

## 4. `host` - networking and integrations

Controls how the host serves the deck. Every field is optional; the defaults
shown are what you get if you omit the block entirely.

```yaml
host:
  bind: "0.0.0.0"          # network interface the device connects to
  port: 7878               # WebSocket port the Presto talks to
  service_name: "PrestoDeck"  # name advertised over mDNS for auto-discovery
  log_level: "INFO"        # DEBUG | INFO | WARNING | ERROR
  web_port: 8080           # port for the browser config editor
  obs: { ... }             # OBS Studio integration (section 4.1)
```

- **bind** - `0.0.0.0` accepts connections on any interface (normal). Set a
  specific IP to restrict it.
- **port** - must match nothing else on your machine; the device finds it
  automatically via mDNS, so you rarely change it.
- **service_name** - the name the deck advertises itself as on the network.
  Useful if you run more than one host.
- **log_level** - raise to `DEBUG` when troubleshooting.
- **web_port** - where `http://localhost:<web_port>/ui` is served.

### 4.1 `host.obs` - OBS Studio connection

```yaml
host:
  obs:
    enabled: true                 # default false - turn the integration on
    url: "ws://localhost:4455"    # obs-websocket address
    password: "your-obs-password" # omit if OBS auth is off
```

When `enabled: true`, the host keeps one persistent connection to OBS (retrying
if OBS isn't running yet) so `obs` actions and live feedback work. See section
13 for the `obs` action itself.

---

## 5. `default_page`

```yaml
default_page: "main"
```

The `id` of the page shown when the device boots or reconnects. Required, and
must match one of your `pages`.

---

## 6. `theme` - colours and shape

Global look of the rendered buttons. All optional.

```yaml
theme:
  background: [10, 10, 14]            # screen behind the buttons
  default_label_color: [240, 240, 240]  # text colour when a button sets none
  default_outline_color: [60, 200, 200] # border colour when a button sets none
  corner_radius: 12                   # button corner rounding, in pixels
```

- **background** - the whole-screen fill, an `[R, G, B]` triplet (see section 8).
- **default_label_color** - label colour for buttons that don't override it.
- **default_outline_color** - the accent/border colour for buttons with no
  `color` of their own.
- **corner_radius** - how rounded the button corners are.

> Note: labels are drawn with the device's built-in font, which only supports
> plain ASCII. Use icons (section 10) for symbols - a `theme.font` key exists in
> the schema but is not yet wired to the renderer.

---

## 7. `pages` - screens of buttons

A deck is a list of pages. You switch between them by **swiping** left/right on
the device (page-indicator dots show at the bottom) or with a `navigate` action.

```yaml
pages:
  - id: "main"          # unique page name (referenced by default_page/navigate)
    grid: [2, 3]        # [rows, cols] - this page is 2 rows x 3 columns
    buttons: [ ... ]    # the buttons on this page (section 8)

  - id: "tools"
    grid: [2, 3]
    buttons: [ ... ]
```

- **id** - unique per deck; used by `default_page` and `navigate` actions.
- **grid** - `[rows, cols]`, both >= 1. Defaults to `[4, 4]` if omitted. Every
  button's `row`/`col` must fit inside it.
- **buttons** - the button list. Cells may be left empty (no button there).

Validation rejects duplicate page ids, out-of-bounds buttons, and two buttons in
the same cell.

---

## 8. Buttons

Each button is one cell in the page grid.

```yaml
- id: "record"          # unique within the page
  row: 0                # 0-based row
  col: 2                # 0-based column
  label: "Record"       # text shown on the button (ASCII)
  icon: "record.png"    # optional icon (section 10)
  color: [200, 0, 0]    # optional accent colour (section 9)
  repeat_ms: 120        # optional hold-to-repeat (section 11)
  action: { ... }       # what happens on tap (section 12)
```

Field by field:

- **id** - required, unique within its page. Used in logs and by feedback.
- **row / col** - required 0-based position inside the page `grid`.
- **label** - text drawn on the button. Empty string by default. ASCII only.
- **icon** - file name of a PNG in the icons directory (section 10). When an
  icon is present it's drawn centered with the label beneath it.
- **color** - the button's accent `[R, G, B]`. Drives the **outline** when idle
  and the **fill** when pressed. Falls back to the theme default if omitted.
- **repeat_ms** - hold-to-repeat interval (section 11).
- **led** - optional per-button LED binding `{index, rgb}` (hardware LEDs).
- **action** - the action to run on tap (sections 12-14). A button with no
  action just lights up when pressed.

---

## 9. Colours

Colours are `[R, G, B]` lists, each channel `0`-`255`.

```yaml
color: [0, 120, 215]      # a blue
background: [10, 10, 14]  # near-black
```

There is no alpha channel. `color` on a button sets its outline (idle) and its
fill (pressed); the label uses the theme's `default_label_color` unless a
state override changes it (section 15).

---

## 10. Icons

Icons are PNG files kept in the icons directory beside your deck
(`host/config/icons/` in the repo, or `<config dir>/icons`). Reference one by
file name:

```yaml
icon: "mic.png"
```

How it works:

- The host advertises every PNG in the icons folder to the device. The device
  downloads and caches them (verified by content hash), so each icon transfers
  once and survives reboots.
- On the button, the icon is drawn centered with the label underneath.
- Any PNG referenced by a button **must exist** in the icons folder or the deck
  is rejected with a clear error.

**Built-in set.** The project ships a consistent icon set (record, play, pause,
stop, next, previous, volume_up/down/mute, speaker, check, mic, mic_muted,
monitor, broadcast, coffee, terminal, bell, globe, swap). They are white glyphs
on a transparent background, so one icon looks right on a button of any colour.

**Making your own.** Icons are 96x96 PNGs. To regenerate or extend the built-in
set, edit and run the generator:

```
python tools/make_icons.py --out host/config/icons
```

To rasterize your own source art (SVG/PNG/JPG) into device-ready PNGs, use:

```
python tools/render_icons.py --src my-art --out host/config/icons --size 96
```

---

## 11. Hold to repeat

Add `repeat_ms` to a button and *holding* it re-fires its action every
`repeat_ms` milliseconds until you lift your finger - ideal for volume, seeking,
or brightness.

```yaml
- id: "vol_up"
  row: 1
  col: 0
  label: "Vol +"
  icon: "volume_up.png"
  repeat_ms: 120           # re-fire every 120 ms while held
  action: {type: media, key: vol_up}
```

There's a short initial delay (~350 ms) before repeats begin, so a normal tap
fires exactly once and a swipe is never mistaken for a hold. Omit `repeat_ms`
(the default) for fire-once buttons. Must be a positive integer.

---

## 12. Actions

`action` says what a button does when tapped. It's a mapping whose `type` picks
the behaviour; the remaining keys are that action's parameters. Actions run on
the **host**, not the device.

| `type` | key fields | what it does |
| --- | --- | --- |
| `shell` | `cmd`, `cwd?`, `env?`, `timeout_s?` | Run a shell command. |
| `keystroke` | `combo` | Send a key combo, e.g. `"ctrl+alt+t"`. |
| `text` | `text`, `delay_ms?` | Type a string. |
| `http` | `method?`, `url`, `headers?`, `json?`, `body?`, `timeout_s?` | Make an HTTP request. |
| `media` | `key` | Tap a media key (section 12.5). |
| `macro` | `steps`, `delay_ms?` | Run several actions in order. |
| `navigate` | `page` | Switch to another page. |
| `notify` | `text`, `duration_ms?`, `color?` | Show a toast on the device. |
| `toggle` | `id`, `on`, `off`, ... | Alternate two actions with state (section 13). |
| `obs` | `request`, params, `feedback?`, ... | Drive OBS Studio (section 14). |
| `python` | `entry_point`, `args?` | Call a plugin action. |

### 12.1 `shell`

```yaml
action:
  type: shell
  cmd: "echo hello > /tmp/prestotest"
  cwd: "/home/me"        # optional working directory
  env: {FOO: "bar"}      # optional extra environment variables
  timeout_s: 5           # optional kill-after seconds
```

Runs `cmd` in a shell. Output goes to the host log; a non-zero exit is logged,
not surfaced on the device.

### 12.2 `keystroke`

```yaml
action: {type: keystroke, combo: "ctrl+shift+t"}
```

Sends one key combination to the focused window. Combine with `+`. Uses
uinput/ydotool/pynput depending on your platform.

### 12.3 `text`

```yaml
action: {type: text, text: "hello world", delay_ms: 10}
```

Types the string as if from the keyboard. `delay_ms` optionally paces the
keystrokes.

### 12.4 `http`

```yaml
action:
  type: http
  method: "POST"          # defaults to GET
  url: "http://127.0.0.1:8899/echo"
  headers: {Authorization: "Bearer x"}   # optional
  json: {msg: "from-presto"}             # optional JSON body
  body: "raw text"                       # optional raw body (use one of json/body)
  timeout_s: 10                          # optional, default 10
```

Fires an async HTTP request. Non-2xx responses are logged, not raised. Note the
key is `json:` in YAML (it maps a JSON object body).

### 12.5 `media`

```yaml
action: {type: media, key: play_pause}
```

Taps a system media key. Valid `key` values:

`play_pause`, `next`, `prev` (or `previous`), `vol_up`, `vol_down`, `mute`.

Great with `repeat_ms` (section 11) for volume.

### 12.6 `macro`

```yaml
action:
  type: macro
  delay_ms: 100           # optional pause between steps
  steps:
    - {type: keystroke, combo: "ctrl+s"}
    - {type: notify, text: "Saved!"}
```

Runs each step in order (each step is itself a full action). `delay_ms` inserts
a pause between steps.

### 12.7 `navigate`

```yaml
action: {type: navigate, page: "tools"}
```

Switches the device to another page. The target must be a real page id.
Navigation also works by **swiping** left/right, so you only need `navigate`
buttons if you want an explicit jump.

### 12.8 `notify`

```yaml
action:
  type: notify
  text: "Hello from PrestoDeck!"
  duration_ms: 2500        # optional, default 2000
  color: [0, 120, 215]     # optional accent
```

Pops a transient toast message on the device screen.

### 12.9 `python`

```yaml
action:
  type: python
  entry_point: obs_scene   # a registered plugin action
  args: {scene: "BRB"}
```

Dispatches to a third-party plugin action installed into the host. See
[action-authoring.md](action-authoring.md) for writing plugins.

---

## 13. `toggle` - two-state buttons

A `toggle` alternates between an `on` action and an `off` action, remembering
its state (even across host restarts), and updates the button's look each time.

```yaml
action:
  type: toggle
  id: "mic"                       # storage key for the on/off state
  on:  {type: notify, text: "Mic ON"}    # action run when switching to ON
  off: {type: notify, text: "Mic OFF"}   # action run when switching to OFF
  initial: false                  # starting state (default false = off)
  on_label: "Mic On"              # appearance while ON (section 15)
  on_color: [0, 200, 0]
  on_icon: "mic.png"
  off_label: "Mic Off"            # appearance while OFF
  off_color: [200, 0, 0]
  off_icon: "mic_muted.png"
```

- **id** - names the persisted state; keep it unique.
- **on / off** - full action mappings run on each transition.
- **initial** - the state before the first press.
- **on_* / off_*** - the two visual states (section 15).

> YAML gotcha: `on:` and `off:` are treated as **strings** here (not the YAML
> booleans `true`/`false`). The deck loader is set up for this on purpose.

---

## 14. `obs` - control OBS Studio

One generic action covers every OBS function. Set `request` to any obs-websocket
request type and add its parameters as sibling keys. Requires
`host.obs.enabled: true` (section 4.1).

```yaml
# Switch scenes
action: {type: obs, request: SetCurrentProgramScene, sceneName: "BRB"}
# Start/stop recording or streaming
action: {type: obs, request: ToggleRecord}
action: {type: obs, request: ToggleStream}
# Mute/unmute an audio input
action: {type: obs, request: ToggleInputMute, inputName: "Mic/Aux"}
# Show/hide a source, save the replay buffer
action: {type: obs, request: SetSceneItemEnabled, sceneName: "Live", sceneItemId: 3, sceneItemEnabled: false}
action: {type: obs, request: SaveReplayBuffer}
```

The full request catalog is the
[obs-websocket protocol reference](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md).

### 14.1 Live state feedback

Add `feedback` and the button mirrors real OBS state - even when you change it
inside OBS directly. Pair it with the `on_*` / `off_*` looks (section 15):

```yaml
- id: "record"
  row: 0
  col: 2
  label: "Record"
  icon: "record.png"
  action:
    type: obs
    request: ToggleRecord
    feedback: "record"        # see keys below
    on_label: "REC ON"
    on_color: [200, 0, 0]
    on_icon: "stop.png"
    off_label: "Record"
    off_color: [60, 60, 64]
    off_icon: "record.png"
```

**Feedback keys** (`feedback:` value):

- `record` - recording is active,
- `stream` - streaming is active,
- `replay` - the replay buffer is active,
- `mute:<inputName>` - that audio input is muted, e.g. `mute:Mic/Aux`,
- `scene:<sceneName>` - that scene is the current program scene, e.g.
  `scene:BRB`.

The correct state is pushed when OBS connects, when the deck reloads, and
whenever a device connects, so the buttons are right immediately.

---

## 15. On/off visual states (label, colour, icon)

Both `toggle` (section 13) and `obs` with `feedback` (section 14.1) can change
how the button *looks* in each state using these optional fields:

| field | effect when the state is ON / OFF |
| --- | --- |
| `on_label` / `off_label` | swap the button text |
| `on_color` / `off_color` | swap the accent colour `[R, G, B]` |
| `on_icon` / `off_icon` | swap the icon (a PNG file name) |

Only the fields you set change; anything you leave out keeps the button's base
`label`/`color`/`icon`. Example - a mic button that shows a live mic when open
and a struck-through mic when muted:

```yaml
icon: "mic.png"                 # base icon
action:
  type: obs
  request: ToggleInputMute
  inputName: "Mic/Aux"
  feedback: "mute:Mic/Aux"
  on_label: "Mic Muted"         # muted
  on_color: [200, 0, 0]
  on_icon: "mic_muted.png"
  off_label: "Mic"              # live
  off_color: [0, 150, 0]
  off_icon: "mic.png"
```

Any icon used in `on_icon`/`off_icon` must exist in the icons folder just like a
static `icon`.

### 15.1 State survives reconnects and reloads

Stateful buttons remember where they are and re-apply their look automatically -
you never have to press a button just to make it show the truth:

- **Toggle** state is persisted on the host (per device). When a device
  connects or the deck reloads, each toggle button is immediately re-sent its
  current on/off appearance. A freshly booted deck shows the real state, not the
  base label.
- **OBS feedback** buttons are re-synced from live OBS whenever OBS connects, a
  device connects, or the deck reloads - so if you muted an input or started
  recording while the deck was away, it catches up on its own.

---

## 16. Navigation and page dots

- **Swipe** left/right anywhere on the screen to move between pages. Small dots
  at the bottom show how many pages there are and which one you're on.
- A `navigate` action (section 12.7) jumps to a specific page on tap.

Both use the page `id`. Because swiping is built in, every grid cell can be a
real action button.

---

## 17. Validation and errors

The host refuses to serve an invalid deck and prints a specific reason. It
checks:

- valid YAML syntax (with the line/column of a syntax error),
- required fields and correct types (via the schema),
- `grid` is `[rows, cols]` with both >= 1,
- every button fits inside its page grid and no two share a cell,
- unique page ids, and `default_page` names a real page,
- every `navigate` target is a real page,
- every referenced `icon` exists in the icons folder.

Fix the reported item and save; the deck reloads automatically.

---

## 18. Hot reload

The host watches both the deck file and the icons directory. Save a change and
it re-validates and pushes the new layout to any connected device instantly - no
restart needed. If the new file is invalid, the host keeps serving the last good
version and logs the error.

---

## 19. A complete minimal deck

```yaml
version: 1

host:
  obs:
    enabled: false

default_page: "main"

theme:
  background: [10, 10, 14]
  default_outline_color: [60, 200, 200]
  corner_radius: 12

pages:
  - id: "main"
    grid: [2, 2]
    buttons:
      - id: "play"
        row: 0
        col: 0
        label: "Play"
        icon: "play.png"
        color: [22, 160, 72]
        action: {type: media, key: play_pause}

      - id: "vol_up"
        row: 0
        col: 1
        label: "Vol +"
        icon: "volume_up.png"
        color: [255, 185, 0]
        repeat_ms: 120
        action: {type: media, key: vol_up}

      - id: "term"
        row: 1
        col: 0
        label: "Term"
        icon: "terminal.png"
        action: {type: keystroke, combo: "ctrl+alt+t"}

      - id: "toast"
        row: 1
        col: 1
        label: "Hi"
        icon: "bell.png"
        action: {type: notify, text: "Hello!", duration_ms: 1500}
```

---

## See also

- [action-authoring.md](action-authoring.md) - deeper action reference and how
  to write your own plugin actions.
- The web editor at `http://localhost:8080/ui` - edit this file visually.
