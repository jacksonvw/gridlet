# Gridlet

FancyZones-style window snapping for KDE Plasma on X11.

Hold a hotkey while dragging any window, paint a zone across the grid overlay,
release — the window snaps to that zone. Inspired by Microsoft PowerToys
FancyZones on Windows 11.

---

## Requirements

- Fedora KDE Plasma, X11 session (not Wayland)
- Python 3.10+

### Python packages

```bash
# System packages (preferred on Fedora):
sudo dnf install python3-xlib python3-cairo

# pip packages:
pip install pystray Pillow
```

Or install everything from the requirements file:

```bash
pip install -r requirements.txt
```

---

## How to run

```bash
python3 main.py
```

A tray icon appears in the system tray. Right-click it to open the Grid Editor
or quit.

The overlay can also be run standalone (no tray icon):

```bash
python3 overlay.py
```

---

## How to use

1. Click and hold the titlebar of any window to start dragging it
2. While dragging, press **Ctrl+Meta** (that's Ctrl + the Windows/Super key)
3. A grid overlay appears on the monitor your cursor is on
4. Keep dragging — cells highlight to show the selected zone
5. Release the mouse button — the window snaps to the highlighted zone
6. To cancel: release Ctrl+Meta before releasing the mouse

---

## Configuration

Settings are stored at `~/.config/gridlet/config.json`. The file is created
automatically on first run with sensible defaults.

You can edit it by hand, or use the **Grid Editor** from the tray icon menu.

```json
{
    "grid": {
        "rows": 4,
        "cols": 6,
        "gap": 4
    },
    "hotkey": {
        "ctrl": true,
        "shift": false,
        "alt": false,
        "meta": true
    }
}
```

| Setting | Description |
|---------|-------------|
| `rows` | Number of grid rows (1–12) |
| `cols` | Number of grid columns (1–16) |
| `gap` | Pixels of space between zones (0–32) |
| `hotkey` | Which modifier keys trigger the overlay |

**Note on hotkeys:** Avoid using Shift — KDE Plasma intercepts Shift+drag for
its own tiling feature and the conflict cannot be disabled.

---

## Autostart with KDE

To have Gridlet start automatically when you log in:

1. Open **System Settings → Autostart**
2. Click **Add** → **Add Application**
3. Browse to `gridlet.desktop` in this folder, or enter the command:
   `python3 /path/to/gridlet/main.py`

Alternatively, copy the desktop file manually:

```bash
# Edit gridlet.desktop first — update the Exec= path to match where you put the folder
cp gridlet.desktop ~/.config/autostart/gridlet.desktop
```

---

## Troubleshooting

**Overlay gets stuck on screen:**
Press Ctrl+C in the terminal, or find Gridlet's process with `pgrep -af main.py`
in a second terminal and `kill` that PID. This cannot harm your system.

**Window snapped to wrong position:**
Drag the window back manually. Right-click its titlebar → More Actions →
Special Window Settings can reset geometry if needed.

**KWin behaves oddly after a crash:**
Run `kwin_x11 --replace &` in a terminal — this restarts the window manager
safely without logging out.

**"No module named pystray" or similar:**
```bash
pip install pystray Pillow
```

---

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point — tray icon + starts overlay thread |
| `overlay.py` | Grid overlay + window snapping engine |
| `config.py` | Reads/writes `~/.config/gridlet/config.json` |
| `editor.py` | Grid Editor GUI (tkinter) |
| `requirements.txt` | Python package dependencies |
| `gridlet.desktop` | KDE desktop entry for autostart/app launcher |
