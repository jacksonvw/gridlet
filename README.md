# Gridlet

FancyZones-style window snapping for KDE Plasma. Hold **Ctrl+Meta while dragging**
a window, paint a zone across a grid overlay, release — the window snaps to it.

This repo holds two implementations:

| Folder | Platform | Status |
|--------|----------|--------|
| [`wayland/`](wayland/) | **KDE Plasma 6 on Wayland** (tested on SteamOS and Fedora 44) | The current version. A KWin script + a small keyboard helper. |
| [`x11/`](x11/) | KDE Plasma on X11 (the original, Fedora) | The original app + the behavioural spec the Wayland port matches. |

Each folder is self-contained.

## Requirements (Wayland)

- KDE Plasma 6 in a Wayland session
- Python 3 with `dbus-python` and PyGObject (tray icon) and tkinter (Grid Editor).
  The keyboard helper itself uses only the standard library.
- Read access to the keyboard's input device. SteamOS grants it; on Fedora it
  takes the one-time step below.

## Install (Wayland)

**On Fedora, once per machine** (SteamOS needs none of this): give Gridlet read
access to the keyboard and make sure the Grid Editor's GUI toolkit is present,
then **reboot** — the reboot is what reliably applies the keyboard permission.
Without it, Ctrl+Meta silently does nothing. What the permission grants, and
why: [`wayland/README.md`](wayland/README.md#prerequisites-off-steamos-eg-fedora).

```bash
sudo cp wayland/70-gridlet-input.rules /etc/udev/rules.d/
sudo dnf install python3-tkinter      # usually already installed; harmless if so
```

Then (after that reboot, on Fedora):

```bash
bash wayland/install.sh     # install, enable, and start (also autostarts on login)
bash wayland/uninstall.sh   # remove everything
```

Then just drag a window and hold **Ctrl+Meta**. A **Gridlet** tray icon lets you
enable/disable/quit it, and **Gridlet Grid Editor** (app menu) edits the grid.

See [`wayland/README.md`](wayland/README.md) for how it works, configuration, the
dev loop, and the KWin gotchas.

## The original (X11)

The X11 version lives in [`x11/`](x11/) (`python3 x11/main.py`). It remains the
reference for exact behaviour and appearance; see [`x11/README.md`](x11/README.md).
Why the Wayland version is a rewrite rather than a port: X11 lets any app read
global modifiers and move other apps' windows; Wayland forbids both by design, so
the engine had to move inside the compositor (KWin), with the held-modifier read
from the kernel input device by the helper.

## License

MIT — see [`LICENSE`](LICENSE).
