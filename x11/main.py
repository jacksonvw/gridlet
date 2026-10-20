#!/usr/bin/env python3
"""
Gridlet — Main Entry Point

Runs the overlay as a background thread and shows a system tray icon
for control.

Usage:
    python3 main.py

The overlay still works standalone too:
    python3 overlay.py
"""

import os
import sys
import subprocess
import threading
import pystray
from PIL import Image, ImageDraw

import config as cfg
import overlay


def create_tray_icon(size=64):
    """
    Draw the tray icon: a dark background with four white outlined rectangles
    arranged in a 2×2 grid. Simple, clean, and readable at any tray size.

    Args:
        size: icon size in pixels (64×64 scales down nicely to 16–22px)

    Returns:
        PIL.Image.Image
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark background
    draw.rectangle([0, 0, size - 1, size - 1], fill=(28, 28, 45, 230))

    # Four cells in a 2×2 layout.
    # pad: space from icon edge to the grid
    # gap: space between the two cells in each axis
    pad = 6
    gap = 4
    mid = size // 2

    cells = [
        (pad,       pad,       mid - gap, mid - gap),   # top-left
        (mid + gap, pad,       size - pad, mid - gap),  # top-right
        (pad,       mid + gap, mid - gap, size - pad),  # bottom-left
        (mid + gap, mid + gap, size - pad, size - pad), # bottom-right
    ]

    for (x0, y0, x1, y1) in cells:
        draw.rectangle([x0, y0, x1, y1], outline=(200, 200, 240, 255), width=2)

    return img


def main():
    # Load config so we can show grid size in the tray menu
    config = cfg.load_config()

    # Determine hotkey label for the menu
    hotkey = config["hotkey"]
    mod_names = {
        "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "meta": "Meta"
    }
    hotkey_str = "+".join(v for k, v in mod_names.items() if hotkey.get(k))

    # We use a dict so nested functions can replace these values
    # (Python closures can't rebind plain variables from outer scopes)
    state = {
        "stop_event":     threading.Event(),
        "overlay_thread": None,
    }

    def start_overlay():
        t = threading.Thread(
            target=overlay.main,
            args=(state["stop_event"],),
            name="overlay",
            daemon=True,
        )
        t.start()
        state["overlay_thread"] = t

    def restart_overlay():
        """Stop the running overlay thread and start a fresh one."""
        print("  Restarting overlay...")
        state["stop_event"].set()
        state["overlay_thread"].join(timeout=3.0)
        state["stop_event"] = threading.Event()
        start_overlay()
        print("  ✓ Overlay restarted with new config")

    # --- Tray menu actions ---

    def on_quit(icon, item):
        """Stop the overlay thread then close the tray icon."""
        print("Quit requested from tray")
        state["stop_event"].set()
        icon.stop()

    def on_open_editor(icon, item):
        """
        Open the grid editor as a subprocess.

        The editor uses tkinter, which (like pystray's GTK backend) needs the
        main thread. Running it as a separate process gives it its own main
        thread — no conflict. A watcher thread waits for it to finish, then
        restarts the overlay if the user saved changes.
        """
        def run_editor():
            editor_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "editor.py")
            result = subprocess.run([sys.executable, editor_path])
            if result.returncode == 0:
                print("  Editor saved — restarting overlay...")
                restart_overlay()
            else:
                print("  Editor cancelled — no changes")

        threading.Thread(target=run_editor, name="editor-watcher", daemon=True).start()

    # --- Build menu ---

    g = config["grid"]
    menu = pystray.Menu(
        pystray.MenuItem("Gridlet", None, enabled=False),
        pystray.MenuItem(f"Grid: {g['cols']} × {g['rows']}, {g['gap']}px gap",
                         None, enabled=False),
        pystray.MenuItem(f"Hotkey: {hotkey_str}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Grid Editor", on_open_editor),
        pystray.MenuItem("Quit", on_quit),
    )

    tray = pystray.Icon(
        name="gridlet",
        icon=create_tray_icon(),
        title="Gridlet",
        menu=menu,
    )

    # Start overlay in background thread
    start_overlay()
    print("✓ Overlay thread started")

    # Run tray on main thread (GTK backend requires this)
    print("✓ Tray icon starting (right-click it to Quit)")
    try:
        tray.run()  # blocks until icon.stop() is called
    except KeyboardInterrupt:
        print("\n✓ Ctrl+C — exiting")
        state["stop_event"].set()

    # Tray has exited — wait briefly for the overlay thread to clean up
    if state["overlay_thread"] and state["overlay_thread"].is_alive():
        state["overlay_thread"].join(timeout=3.0)

    print("✓ Gridlet closed cleanly")


if __name__ == "__main__":
    main()
