#!/usr/bin/env python3
"""
Gridlet — Grid Editor

A small settings window for adjusting the zone grid layout:
  - Columns (1–16)
  - Rows (1–12)
  - Gap between zones in pixels (0–32)

Opens from the tray icon's "Grid Editor" menu item, or standalone:
    python3 editor.py

Saves changes to ~/.config/gridlet/config.json.
Returns True (saved) or False (cancelled) when called as open_editor().
"""

import tkinter as tk
from tkinter import ttk
import Xlib.display
import config as cfg


# Preview canvas size (the box that shows the zone layout)
PREVIEW_W = 400
PREVIEW_H = 225   # 16:9 — matches a typical widescreen monitor


def primary_monitor_size(root):
    """
    (width, height) of the primary monitor.

    Tk only knows the combined desktop, which spans every monitor, so ask
    XRandR the way overlay.py does. Falls back to Tk's screen size.
    """
    try:
        display = Xlib.display.Display()
        try:
            monitors = display.screen().root.xrandr_get_monitors(is_active=True).monitors
        finally:
            display.close()
        mon = next((m for m in monitors if m.primary), monitors[0])
        return mon.width_in_pixels, mon.height_in_pixels
    except Exception:
        return root.winfo_screenwidth(), root.winfo_screenheight()


def draw_preview(canvas, cols, rows, gap, screen):
    """
    Redraw the zone preview on the canvas.

    Shows each zone as a filled rectangle inset by `gap` pixels from the
    cell boundary — exactly as it appears in the real overlay.

    Args:
        canvas: tkinter Canvas widget
        cols: number of columns
        rows: number of rows
        gap: gap in pixels (scaled to canvas size)
        screen: (width, height) of the monitor the preview stands for
    """
    canvas.delete("all")

    # Background
    canvas.create_rectangle(0, 0, PREVIEW_W, PREVIEW_H, fill="#1c1c2d", outline="")

    cell_w = PREVIEW_W / cols
    cell_h = PREVIEW_H / rows

    # Shrink the gap by the same factors that shrink the screen to the preview,
    # so it shows at its true proportion. Each axis has its own factor, since
    # the screen need not be 16:9 like the preview.
    gap_x = gap * PREVIEW_W / screen[0]
    gap_y = gap * PREVIEW_H / screen[1]

    for row in range(rows):
        for col in range(cols):
            x0 = col * cell_w + gap_x
            y0 = row * cell_h + gap_y
            x1 = (col + 1) * cell_w - gap_x
            y1 = (row + 1) * cell_h - gap_y
            canvas.create_rectangle(x0, y0, x1, y1,
                                    fill="#2a2a4a", outline="#9090cc", width=1)


def open_editor():
    """
    Open the grid editor window and block until it closes.

    Returns:
        True  if the user clicked "Save & Apply"
        False if the user cancelled or closed the window
    """
    config = cfg.load_config()

    result = {"saved": False}

    root = tk.Tk()
    root.title("Gridlet — Grid Editor")
    root.resizable(False, False)
    screen = primary_monitor_size(root)

    # ── Controls ──────────────────────────────────────────────────────────────

    controls = ttk.Frame(root, padding=16)
    controls.pack(fill="x")

    # Spinbox variables
    cols_var = tk.IntVar(value=config["grid"]["cols"])
    rows_var = tk.IntVar(value=config["grid"]["rows"])
    gap_var  = tk.IntVar(value=config["grid"]["gap"])

    def on_change(*_):
        try:
            c = max(1, min(16, cols_var.get()))
            r = max(1, min(12, rows_var.get()))
            g = max(0, min(32, gap_var.get()))
            draw_preview(canvas, c, r, g, screen)
        except tk.TclError:
            pass  # Spinbox mid-edit — ignore invalid transient state

    def make_row(parent, label, var, from_, to, row):
        ttk.Label(parent, text=label, width=10).grid(
            row=row, column=0, sticky="w", pady=4)
        spin = ttk.Spinbox(parent, from_=from_, to=to, textvariable=var,
                           width=5, command=on_change)
        spin.grid(row=row, column=1, sticky="w", padx=8)
        var.trace_add("write", on_change)
        return spin

    make_row(controls, "Columns",  cols_var, 1, 16, 0)
    make_row(controls, "Rows",     rows_var, 1, 12, 1)
    make_row(controls, "Gap (px)", gap_var,  0, 32, 2)

    # ── Preview canvas ────────────────────────────────────────────────────────

    canvas_frame = ttk.Frame(root, padding=(16, 0, 16, 0))
    canvas_frame.pack()

    canvas = tk.Canvas(canvas_frame, width=PREVIEW_W, height=PREVIEW_H,
                       bg="#1c1c2d", highlightthickness=1,
                       highlightbackground="#444466")
    canvas.pack()

    draw_preview(canvas, cols_var.get(), rows_var.get(), gap_var.get(), screen)

    # ── Buttons ───────────────────────────────────────────────────────────────

    buttons = ttk.Frame(root, padding=16)
    buttons.pack(fill="x")

    def on_cancel():
        root.destroy()

    def on_save():
        try:
            cols = max(1, min(16, cols_var.get()))
            rows = max(1, min(12, rows_var.get()))
            gap  = max(0, min(32,  gap_var.get()))
        except tk.TclError:
            return  # Invalid value in spinbox — don't save

        # Merge into existing config (preserves hotkey and any other keys)
        config["grid"]["cols"] = cols
        config["grid"]["rows"] = rows
        config["grid"]["gap"]  = gap
        cfg.save_config(config)
        print(f"  Saved grid: {cols} cols × {rows} rows, {gap}px gap")

        result["saved"] = True
        root.destroy()

    ttk.Button(buttons, text="Cancel",       command=on_cancel).pack(side="left")
    ttk.Button(buttons, text="Save & Apply", command=on_save).pack(side="right")

    # Centre the window on screen
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w  = root.winfo_width()
    h  = root.winfo_height()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    root.mainloop()
    return result["saved"]


if __name__ == "__main__":
    import sys
    saved = open_editor()
    print("Saved." if saved else "Cancelled.")
    sys.exit(0 if saved else 1)
