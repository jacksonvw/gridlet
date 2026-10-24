# Gridlet — Wayland port

The KDE Plasma **Wayland** build of Gridlet, tested on **SteamOS** (KWin 6.4)
and **Fedora 44** (Plasma 6.7.3). It matches the X11 original
([`../x11/`](../x11/)) exactly:
hold **Ctrl+Meta while dragging a window**, a grid overlay appears, paint a zone
across cells, release to snap. This folder is self-contained (it ships its own
copies of `config.py` and `editor.py`), apart from the app icon, which both
versions share from [`../icons/`](../icons/).

> Why a rewrite, not a port of `overlay.py`? X11 lets any app read the global
> keyboard state and move other apps' windows. Wayland forbids both by design.
> So the engine lives *inside* the compositor (a KWin script), and the one thing
> even a KWin script can't see — the held modifier — is read from the kernel
> input device by a tiny helper.

---

## Pieces

| Component | What it is |
|-----------|------------|
| **KWin script** (`kwin-script/`, QML) | The overlay + snapping engine. Installed to `~/.local/share/kwin/scripts/gridlet` and enabled, so KWin auto-loads it every login. Polls `Workspace.activeWindow.move` + `cursorPos` (mirroring the X11 loop), draws the grid, snaps via `window.frameGeometry`. |
| **Keyboard helper** (`gridlet-hotkey-helper.py`) | Pure Python stdlib. Reads `/dev/input/event*` to detect the Ctrl+Meta combo, then calls `kglobalaccel invokeShortcut GridletActivate/GridletDeactivate` — the script registers those two no-key shortcuts as the bridge. |
| **Tray** (`gridlet-tray.py`) | A StatusNotifierItem (dbus-python) — the only tray type KDE Wayland honours. Enable/disable (kill-switch), launch the editor, quit. |
| **Editor** (`editor.py`, tkinter) | Pick a monitor, then edit the shared default grid or give that monitor its own. "Save & Apply" runs `gridlet-apply.sh` to reload live. |

```
keyboard ─/dev/input→ helper ─invokeShortcut→ KWin script ─frameGeometry→ window
tray ─qdbus/pkill→ (enable/disable script + helper)          ▲ cursorPos / activeWindow.move (polled)
```

---

## Prerequisites off SteamOS (e.g. Fedora)

SteamOS satisfies these already; Fedora does not. Verified on Fedora 44 /
Plasma 6.7.3.

1. **Keyboard read access.** The helper reads evdev directly, and on Fedora
   `/dev/input/event*` is `root:input 0660` with the desktop user not in
   `input` — so it can open nothing and silently does nothing. Install the
   included udev rule, which tags **keyboards only** for `uaccess` (an ACL for
   the active seat user, dropped again at logout):

   ```bash
   sudo cp wayland/70-gridlet-input.rules /etc/udev/rules.d/
   sudo udevadm control --reload
   sudo udevadm trigger --subsystem-match=input --action=add
   getfacl -p /dev/input/event* | grep -c "user:$USER:rw"   # expect 1 or more
   ```

   If that prints `0`, reboot and check again: on some systems (Fedora 44 among
   them) the `trigger` alone doesn't apply the ACL, but it is there from boot
   onward. Don't check one fixed `eventN` — the numbers differ per machine and
   can change between boots.

   Tradeoff: while logged in, any process running as you can read keystrokes
   from those keyboards. Inherent to reading evdev; still narrower than
   `usermod -aG input`, which covers every input device, permanently.

2. **No `qdbus6`.** Fedora ships no qdbus at all (Qt's lives in the optional
   `qt6-qdbusviewer`). Everything therefore calls `gridlet-qdbus`, a shim that
   uses `qdbus6` when present and otherwise `gdbus` (glib2, always installed),
   reproducing qdbus6's output format so callers are unchanged.

3. **tkinter, for the Grid Editor only.** `python3-tkinter` is a separate
   package on Fedora. It is often pulled in as a weak dependency, but nothing
   requires it, so `sudo dnf install python3-tkinter` makes sure. Snapping and
   the tray don't need it (their `python3-dbus` / `python3-gobject` are core
   Fedora deps).

Nothing else is needed — in particular the engine's diagnostics require no
logging config, see below.

## Install / update / remove

```bash
bash wayland/install.sh      # install + enable + start now (re-run to update)
bash wayland/uninstall.sh    # remove everything (files, autostart, menu, shortcuts)
```

Installs to: `~/.local/share/kwin/scripts/gridlet` (script), `~/.local/share/gridlet`
(helper/tray/editor tooling), `~/.config/autostart/gridlet-{helper,tray}.desktop`
(autostart), `~/.local/share/applications/gridlet{,-editor}.desktop` (app menu),
`~/.local/share/icons/hicolor/*/apps/gridlet.{svg,png}` (icon), plus `kwinrc`
`Plugins/gridletEnabled=true`. It reads grid settings from
`~/.config/gridlet/config.json`. `uninstall.sh` removes all of the above and
unregisters the `GridletActivate`/`GridletDeactivate` shortcuts.

## Everyday use

- Drag a window, hold **Ctrl+Meta** → grid → paint → release to snap.
- **Gridlet** tray icon → enable / disable / quit. Reachable even if the overlay
  ever misbehaves, since the panel sits above everything.
- **Gridlet** / **Gridlet Grid Editor** in the app menu (Gridlet = re-start after
  a Quit; Editor = pick a monitor and set its grid's rows/cols/gap/margin,
  applied live on Save).

## Develop / debug

```bash
bash wayland/gridlet-dev-run.sh   # loads the script + runs the helper, streams logs; Ctrl+C to stop
```

Stages `main.qml` + a fresh `config.js` in a unique `/tmp` dir each run, because
**KWin caches compiled QML by file path**. Never test overlay changes by enabling
the installed script — test via the dev runner, so a bad build can't affect login.

The engine logs with `console.warn`, **not** `print`. KWin binds `print` to
`qCDebug(KWIN_SCRIPTING)`, and that category ships with `DEFAULT_SEVERITY
[WARNING]` — so on a stock Fedora every `print` is silently swallowed and the
dev runner streams nothing. `console.warn` emits a QML warning, which reaches
the journal with no logging config and no KWin restart. Keep it that way.

---

## Configuration

`~/.config/gridlet/config.json` (same file as X11):

```json
{ "grid": { "rows": 4, "cols": 6, "gap": 8, "margin": 4 },
  "monitors": { "DP-1": { "rows": 2, "cols": 3, "gap": 8, "margin": 4 } },
  "hotkey": { "ctrl": true, "shift": false, "alt": false, "meta": true } }
```

Apart from the `monitors` entry, these are the defaults. `gap` is the space
between zones, `margin` the space between the grid and the screen edge (both
in pixels).

- **grid** → the default grid, used on every monitor without its own. The QML
  can't read JSON, so `gen-config.py` translates the file into `config.js`,
  which `main.qml` imports. The editor's "Save & Apply" (`gridlet-apply.sh`)
  regenerates it and hot-reloads the script from a fresh path.
- **monitors** → a grid of its own for any monitor, by connector name (the
  `name` that `kscreen-doctor -o` lists, e.g. `DP-1`). A key it leaves out
  comes from `grid`. The overlay uses the grid of the monitor it appears on.
- **hotkey** → the helper reads it at startup (restart the helper to change it).

---

## Hard-won KWin constraints (read before editing the overlay)

1. **A declarative KWin script only renders if its ROOT object is the `Window`.**
   A `Window` nested in an `Item` root is force-hidden.
2. **`Qt.WindowTransparentForInput` is NOT honoured here.** An always-mapped
   fullscreen overlay swallows every click on the desktop. The overlay is only
   safe because it exists solely while KWin owns the drag (show/hide). Do not
   keep it mapped when idle.
3. **No held-modifier access** from scripts; bare-modifier shortcuts register but
   never fire. Hence the evdev helper + `invokeShortcut` bridge.
4. **`readConfig` and `file://` XHR don't work** in the KWin QML engine. Config
   arrives via the generated `config.js` import.
5. **Unloading a script does NOT disconnect handlers it `.connect()`ed** — they
   orphan and keep firing. The engine is poll-based (a Timer) and connects
   nothing per-window.
6. **KWin caches compiled QML by path** in a session — reload from a fresh path.
7. **Mapping/unmapping a Window triggers KWin's open/close animation.** The
   show/hide overlay therefore grows in and shrinks out. On Plasma 6 the
   culprit is the **Scale** effect (`kwin4_effect_scale`), which animates any
   window it considers normal — including our overlay. See the workaround
   under Known limitations.

---

## Files

| File | Role |
|------|------|
| `kwin-script/metadata.json`, `contents/ui/main.qml` | KWin script package + engine |
| `kwin-script/contents/ui/config.js` | Grid settings (generated from config.json) |
| `gridlet-hotkey-helper.py` | evdev → Ctrl+Meta → invokeShortcut bridge |
| `gridlet-qdbus` | qdbus6-compatible shim, falls back to gdbus (Fedora has no qdbus) |
| `70-gridlet-input.rules` | udev rule granting keyboard read access (non-SteamOS) |
| `gridlet-tray.py` | StatusNotifierItem tray control |
| `gen-config.py` | config.json → config.js |
| `gridlet-apply.sh` | Regenerate config.js + hot-reload + restart helper (live apply) |
| `gridlet-edit.sh` | Launch editor, then apply on save |
| `gridlet-start.sh` | Idempotent (re)start of script + helper + tray |
| `install.sh` / `uninstall.sh` | Install/enable/autostart, or remove |
| `gridlet-dev-run.sh` | Dev runner with live logs |
| `editor.py`, `config.py` | Grid editor (per monitor) + config, grown from the X11 versions |
| `../icons/hicolor/` | App icon: the source SVG and its PNG sizes (`../icons/render-pngs.sh` re-renders them) |

---

## Known limitations / TODO

- **Overlay open/close zoom** — KWin animates the Window map/unmap. On Plasma 6
  that's the **Scale** effect. Turning it off removes the grow-in entirely:

  ```bash
  kwriteconfig6 --file kwinrc --group Plugins --key scaleEnabled false
  gdbus call --session --dest org.kde.KWin --object-path /Effects \
    --method org.kde.kwin.Effects.unloadEffect scale     # applies now; reconfigure alone won't
  ```

  Note this is **global** — every window on the desktop then opens and closes
  without animation. Re-enable with `scaleEnabled true` + `loadEffect scale`.
  A Gridlet-only fix would mean giving the overlay a non-normal window type
  (e.g. `Qt.ToolTip`) so the effect skips it, which is untested — the window
  type also governs stacking and input, so it interacts with constraint #2.
- **Multi-monitor** picks the screen under the cursor (`activeOutput()`).
  Verified on Fedora 44 / Plasma 6.7.3 with two monitors of different
  resolutions, both at scale 1 — snapping is correct on both. Mixed *scale
  factors* remain untested. A monitor's own grid is keyed by its connector
  name, so it follows the port: plug the monitor in elsewhere and it gets the
  default grid there.
