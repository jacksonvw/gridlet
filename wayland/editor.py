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

import tkinter as tk
from tkinter import ttk
import config as cfg


# Preview canvas size (the box that shows the zone layout)
PREVIEW_W = 400
PREVIEW_H = 225   # 16:9 — matches a typical widescreen monitor


def draw_preview(canvas, cols, rows, gap, margin):
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
    """
    canvas.delete("all")

    # Background
    canvas.create_rectangle(0, 0, PREVIEW_W, PREVIEW_H, fill="#1c1c2d", outline="")

    # Scale proportionally so it looks right at preview size. The real grid is
    # ~3840px wide, the preview is 400px, so *8 keeps small values visible.
    # gap and margin share one scale factor, so their relative sizes stay honest
    # — which is the whole point of being able to tune them against each other.
    scale = (PREVIEW_W / 3840) * 8
    g = gap * scale
    m = margin * scale

    # Same share-out as the overlay: margins and inter-cell gaps come off first.
    cell_w = max(2, (PREVIEW_W - 2 * m - (cols - 1) * g) / cols)
    cell_h = max(2, (PREVIEW_H - 2 * m - (rows - 1) * g) / rows)

    for row in range(rows):
        for col in range(cols):
            x0 = m + col * (cell_w + g)
            y0 = m + row * (cell_h + g)
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

    root = tk.Tk()
    root.title("Gridlet — Grid Editor")
    root.resizable(False, False)

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
            draw_preview(canvas, c, r, g, m)
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
                 gap_var.get(), margin_var.get())

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
