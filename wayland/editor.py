#!/usr/bin/env python3
"""
Gridlet — Grid Editor

A small settings window for adjusting the zone grid layout:
  - Columns (1–16)
  - Rows (1–12)
  - Gap between zones in pixels (0–32)
  - Margin from the screen edge in pixels (0–64)

Opens from the tray icon's "Grid Editor" menu item, or standalone:
    python3 editor.py

Saves changes to ~/.config/gridlet/config.json.
Returns True (saved) or False (cancelled) when called as open_editor().
"""

import json
import os
import subprocess
import tkinter as tk
from tkinter import ttk
import config as cfg


# Preview canvas size (the box that shows the zone layout)
PREVIEW_W = 400
PREVIEW_H = 225   # 16:9 — matches a typical widescreen monitor

ICON_SIZES = (16, 32, 48, 64, 128, 256)


def load_icons():
    """
    The Gridlet icon at every size it ships in, as Tk images.

    The PNGs sit in an hicolor tree next to this file's folder: icons/ in the
    repo, and ~/.local/share/icons once installed (this file then lives in
    ~/.local/share/gridlet). Tk 8.6 can't read the SVG, hence the PNGs.
    """
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "icons", "hicolor")
    paths = [os.path.join(base, f"{n}x{n}", "apps", "gridlet.png") for n in ICON_SIZES]
    return [tk.PhotoImage(file=p) for p in paths if os.path.exists(p)]


def primary_monitor_size(root):
    """
    (width, height) of the primary monitor, in the logical pixels the KWin
    script lays the grid out in.

    Tk only knows the combined desktop, which spans every monitor, so ask
    KScreen instead. Falls back to Tk's screen size if that fails.
    """
    try:
        out = subprocess.run(["kscreen-doctor", "-j"], capture_output=True,
                             text=True, timeout=3).stdout
        outputs = [o for o in json.loads(out)["outputs"] if o.get("enabled")]
        o = min(outputs, key=lambda o: o.get("priority") or 99)  # 1 = primary
        w, h = o["size"]["width"], o["size"]["height"]
        if o.get("rotation") in (2, 8):     # turned 90° either way
            w, h = h, w
        scale = o.get("scale") or 1
        return round(w / scale), round(h / scale)
    except Exception:
        return root.winfo_screenwidth(), root.winfo_screenheight()


def draw_preview(canvas, cols, rows, gap, margin, screen):
    """
    Redraw the zone preview on the canvas.

    Mirrors the real overlay's geometry exactly: the grid is inset from the
    edge by `margin`, and adjacent zones are separated by `gap`.

    Args:
        canvas: tkinter Canvas widget
        cols: number of columns
        rows: number of rows
        gap: pixels between adjacent zones (scaled to canvas size)
        margin: pixels between the grid and the screen edge (likewise)
        screen: (width, height) of the monitor the preview stands for
    """
    canvas.delete("all")

    # Background
    canvas.create_rectangle(0, 0, PREVIEW_W, PREVIEW_H, fill="#1c1c2d", outline="")

    # Shrink gap and margin by the same factors that shrink the screen to the
    # preview, so they show at their true proportions. Each axis has its own
    # factor, since the screen need not be 16:9 like the preview. gap and margin
    # share each factor, so their relative sizes stay honest — which is the
    # whole point of being able to tune them against each other.
    sx = PREVIEW_W / screen[0]
    sy = PREVIEW_H / screen[1]
    gx, gy = gap * sx, gap * sy
    mx, my = margin * sx, margin * sy

    # Same share-out as the overlay: margins and inter-cell gaps come off first.
    cell_w = max(2, (PREVIEW_W - 2 * mx - (cols - 1) * gx) / cols)
    cell_h = max(2, (PREVIEW_H - 2 * my - (rows - 1) * gy) / rows)

    for row in range(rows):
        for col in range(cols):
            x0 = mx + col * (cell_w + gx)
            y0 = my + row * (cell_h + gy)
            canvas.create_rectangle(x0, y0, x0 + cell_w, y0 + cell_h,
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

    # className sets WM_CLASS, which the desktop entry's StartupWMClass matches
    root = tk.Tk(className="gridlet")
    root.title("Gridlet — Grid Editor")
    root.resizable(False, False)
    icons = load_icons()
    if icons:
        root.iconphoto(True, *icons)
    screen = primary_monitor_size(root)

    # ── Controls ──────────────────────────────────────────────────────────────

    controls = ttk.Frame(root, padding=16)
    controls.pack(fill="x")

    # Spinbox variables
    cols_var   = tk.IntVar(value=config["grid"]["cols"])
    rows_var   = tk.IntVar(value=config["grid"]["rows"])
    gap_var    = tk.IntVar(value=config["grid"]["gap"])
    margin_var = tk.IntVar(value=config["grid"]["margin"])

    def on_change(*_):
        try:
            c = max(1, min(16, cols_var.get()))
            r = max(1, min(12, rows_var.get()))
            g = max(0, min(32, gap_var.get()))
            m = max(0, min(64, margin_var.get()))
            draw_preview(canvas, c, r, g, m, screen)
        except tk.TclError:
            pass  # Spinbox mid-edit — ignore invalid transient state

    def make_row(parent, label, var, from_, to, row):
        ttk.Label(parent, text=label, width=12).grid(
            row=row, column=0, sticky="w", pady=4)
        spin = ttk.Spinbox(parent, from_=from_, to=to, textvariable=var,
                           width=5, command=on_change)
        spin.grid(row=row, column=1, sticky="w", padx=8)
        var.trace_add("write", on_change)
        return spin

    make_row(controls, "Columns",     cols_var,   1, 16, 0)
    make_row(controls, "Rows",        rows_var,   1, 12, 1)
    make_row(controls, "Gap (px)",    gap_var,    0, 32, 2)
    make_row(controls, "Margin (px)", margin_var, 0, 64, 3)

    ttk.Label(controls, text="Gap = between zones.  Margin = around the screen edge.",
              foreground="#777777").grid(row=4, column=0, columnspan=3,
                                         sticky="w", pady=(8, 0))

    # ── Preview canvas ────────────────────────────────────────────────────────

    canvas_frame = ttk.Frame(root, padding=(16, 0, 16, 0))
    canvas_frame.pack()

    canvas = tk.Canvas(canvas_frame, width=PREVIEW_W, height=PREVIEW_H,
                       bg="#1c1c2d", highlightthickness=1,
                       highlightbackground="#444466")
    canvas.pack()

    draw_preview(canvas, cols_var.get(), rows_var.get(),
                 gap_var.get(), margin_var.get(), screen)

    # ── Buttons ───────────────────────────────────────────────────────────────

    buttons = ttk.Frame(root, padding=16)
    buttons.pack(fill="x")

    def on_cancel():
        root.destroy()

    def on_save():
        try:
            cols   = max(1, min(16, cols_var.get()))
            rows   = max(1, min(12, rows_var.get()))
            gap    = max(0, min(32, gap_var.get()))
            margin = max(0, min(64, margin_var.get()))
        except tk.TclError:
            return  # Invalid value in spinbox — don't save

        # Merge into existing config (preserves hotkey and any other keys)
        config["grid"]["cols"]   = cols
        config["grid"]["rows"]   = rows
        config["grid"]["gap"]    = gap
        config["grid"]["margin"] = margin
        cfg.save_config(config)
        print(f"  Saved grid: {cols} cols × {rows} rows, "
              f"{gap}px gap, {margin}px margin")

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
