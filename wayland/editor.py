#!/usr/bin/env python3
"""
Gridlet — Grid Editor

A settings window for the zone grid, per monitor:
  - A strip of your monitors, as they're arranged. Click one to choose it.
  - Whether that monitor has its own grid. Monitors without one share the
    default grid, so with a single monitor there is nothing to choose.
  - Columns (1–16) and rows (1–12)
  - Gap between zones in pixels (0–32)
  - Margin from the screen edge in pixels (0–64)

The preview draws the chosen monitor's grid in miniature, at the monitor's
own shape and true proportions.

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


# The boxes the monitor strip and the preview are drawn in. Each monitor keeps
# its own shape inside them.
STRIP_W, STRIP_H = 480, 120
PREVIEW_W, PREVIEW_H = 480, 270

# Each setting's range, as the spinboxes offer it.
LIMITS = {"cols": (1, 16), "rows": (1, 12), "gap": (0, 32), "margin": (0, 64)}

# Colours: background, cell fill, cell outline, and the outline of whatever
# isn't selected.
BG, CELL, LINE, DIM = "#1c1c2d", "#2a2a4a", "#9090cc", "#444466"

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


def list_monitors(root):
    """
    The enabled monitors, left to right, as dicts with "name" (the connector
    name, which the KWin script goes by too), "x", "y", "w", "h" in the
    logical pixels the grid is laid out in, and "primary".

    Tk only knows the combined desktop, which spans every monitor, so ask
    KScreen. Without it, this returns one unnamed monitor the size of Tk's
    screen, which can only use the default grid.
    """
    try:
        out = subprocess.run(["kscreen-doctor", "-j"], capture_output=True,
                             text=True, timeout=3).stdout
        monitors = []
        for o in json.loads(out)["outputs"]:
            if not o.get("enabled"):
                continue
            w, h = o["size"]["width"], o["size"]["height"]
            if o.get("rotation") in (2, 8):     # turned 90° either way
                w, h = h, w
            scale = o.get("scale") or 1
            monitors.append({"name": o["name"], "x": o["pos"]["x"], "y": o["pos"]["y"],
                             "w": round(w / scale), "h": round(h / scale),
                             "primary": o.get("priority") == 1})
        if monitors:
            return sorted(monitors, key=lambda m: (m["x"], m["y"]))
    except Exception:
        pass
    return [{"name": None, "x": 0, "y": 0, "w": root.winfo_screenwidth(),
             "h": root.winfo_screenheight(), "primary": True}]


def fit(w, h, box_w, box_h):
    """Scale factor and size of the largest w×h-shaped rectangle in the box."""
    s = min(box_w / w, box_h / h)
    return s, w * s, h * s


def draw_preview(canvas, grid, screen):
    """
    Redraw the zone preview: `grid` (cols, rows, gap, margin) on a monitor of
    size `screen`, drawn as that monitor in miniature, centred in the canvas.

    Mirrors the real overlay's geometry: the grid is inset from the edge by
    the margin, and adjacent zones are separated by the gap.
    """
    canvas.delete("all")
    box_w, box_h = int(canvas["width"]), int(canvas["height"])
    s, pw, ph = fit(screen[0], screen[1], box_w, box_h)
    ox, oy = (box_w - pw) / 2, (box_h - ph) / 2
    canvas.create_rectangle(ox, oy, ox + pw, oy + ph, fill=BG, outline="")

    # Shrink gap and margin by the factor that shrinks the monitor to the
    # preview, so they show at their true proportions. gap and margin share
    # it, so their relative sizes stay honest — which is the whole point of
    # being able to tune them against each other.
    cols, rows = grid["cols"], grid["rows"]
    g, m = grid["gap"] * s, grid["margin"] * s

    # Same share-out as the overlay: margins and inter-cell gaps come off first.
    cell_w = max(2, (pw - 2 * m - (cols - 1) * g) / cols)
    cell_h = max(2, (ph - 2 * m - (rows - 1) * g) / rows)

    for row in range(rows):
        for col in range(cols):
            x0 = ox + m + col * (cell_w + g)
            y0 = oy + m + row * (cell_h + g)
            canvas.create_rectangle(x0, y0, x0 + cell_w, y0 + cell_h,
                                    fill=CELL, outline=LINE, width=1)


class GridEditor:
    """The editor's window and state. `config` is edited in place."""

    def __init__(self, root, config, monitors):
        self.root = root
        self.config = config
        self.config.setdefault("monitors", {})
        self.monitors = monitors
        self.selected = next((i for i, m in enumerate(monitors) if m["primary"]), 0)
        self.saved = False
        self.loading = False    # True while the widgets are being filled in
        self.vars = {k: tk.IntVar() for k in LIMITS}
        self.own_var = tk.BooleanVar()
        self.build()
        self.select(self.selected)

    # ── State ────────────────────────────────────────────────────────────────

    @property
    def name(self):
        return self.monitors[self.selected]["name"]

    def grid_for(self, name):
        """The grid a monitor uses: its own if it has one, else the default."""
        return self.config["monitors"].get(name) or self.config["grid"]

    def shown_grid(self):
        """The values in the spinboxes, clamped to their ranges, or None mid-edit."""
        try:
            return {k: max(lo, min(hi, self.vars[k].get())) for k, (lo, hi) in LIMITS.items()}
        except tk.TclError:
            return None

    def select(self, index):
        """Show monitor `index` and the grid it uses."""
        self.selected = index
        m = self.monitors[index]
        self.loading = True
        for k, v in self.grid_for(m["name"]).items():
            if k in self.vars:
                self.vars[k].set(v)
        self.own_var.set(m["name"] in self.config["monitors"])
        self.loading = False
        self.own_check.configure(text="Give %s its own grid" % (m["name"] or "this screen"),
                                 state="normal" if m["name"] else "disabled")
        self.info.configure(text="%s · %d×%d%s" % (m["name"] or "Screen", m["w"], m["h"],
                                                   " · primary" if m["primary"] and len(self.monitors) > 1 else ""))
        self.redraw()

    def on_value_change(self, *_):
        if self.loading:
            return
        grid = self.shown_grid()
        if grid is None:
            return  # Spinbox mid-edit — ignore invalid transient state
        target = self.config["monitors"].get(self.name) or self.config["grid"]
        target.update(grid)
        self.redraw()

    def on_own_toggle(self):
        """Ticked: the monitor gets its own copy of the grid it was using.
        Cleared: it goes back to the default grid."""
        if self.own_var.get():
            self.config["monitors"][self.name] = dict(self.config["grid"])
        else:
            self.config["monitors"].pop(self.name, None)
        self.select(self.selected)

    def use_everywhere(self):
        """Make the grid on show the default and drop every monitor's own grid."""
        grid = self.shown_grid()
        if grid is None:
            return
        self.config["grid"].update(grid)
        self.config["monitors"].clear()
        self.select(self.selected)

    def save(self):
        if self.shown_grid() is None:
            return  # Invalid value in a spinbox — don't save
        cfg.save_config(self.config)
        g = self.config["grid"]
        print(f"  Saved default grid: {g['cols']} cols × {g['rows']} rows, "
              f"{g['gap']}px gap, {g['margin']}px margin")
        for name, g in sorted(self.config["monitors"].items()):
            print(f"  Saved {name}: {g['cols']} cols × {g['rows']} rows, "
                  f"{g['gap']}px gap, {g['margin']}px margin")
        self.saved = True
        self.root.destroy()

    # ── Drawing ──────────────────────────────────────────────────────────────

    def redraw(self):
        self.draw_monitors()
        m = self.monitors[self.selected]
        draw_preview(self.preview, self.grid_for(m["name"]), (m["w"], m["h"]))

    def monitor_rects(self):
        """Each monitor's rectangle in the strip, keeping their arrangement."""
        ms = self.monitors
        x0, y0 = min(m["x"] for m in ms), min(m["y"] for m in ms)
        x1 = max(m["x"] + m["w"] for m in ms)
        y1 = max(m["y"] + m["h"] for m in ms)
        s, w, h = fit(x1 - x0, y1 - y0, STRIP_W - 16, STRIP_H - 16)
        ox, oy = (STRIP_W - w) / 2, (STRIP_H - h) / 2
        return [(ox + (m["x"] - x0) * s + 2, oy + (m["y"] - y0) * s + 2,
                 ox + (m["x"] + m["w"] - x0) * s - 2, oy + (m["y"] + m["h"] - y0) * s - 2)
                for m in ms]

    def draw_monitors(self):
        c = self.strip
        c.delete("all")
        for i, (l, t, r, b) in enumerate(self.monitor_rects()):
            m, sel = self.monitors[i], i == self.selected
            c.create_rectangle(l, t, r, b, fill=CELL if sel else BG,
                               outline=LINE if sel else DIM, width=2 if sel else 1)
            g = self.grid_for(m["name"])
            own = m["name"] in self.config["monitors"]
            lines = [m["name"] or "Screen"]
            if b - t >= 34:
                lines.append("%s %d×%d" % ("own" if own else "default", g["cols"], g["rows"]))
            c.create_text((l + r) / 2, (t + b) / 2, text="\n".join(lines), justify="center",
                          fill="#ffffff" if sel else "#aaaacc", font=("TkDefaultFont", 8))

    def on_strip_click(self, event):
        for i, (l, t, r, b) in enumerate(self.monitor_rects()):
            if l <= event.x <= r and t <= event.y <= b:
                self.select(i)
                return

    # ── Widgets ──────────────────────────────────────────────────────────────

    def build(self):
        root = self.root
        top = ttk.Frame(root, padding=(16, 16, 16, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Monitor").pack(anchor="w")
        self.strip = tk.Canvas(top, width=STRIP_W, height=STRIP_H, bg=root.cget("bg"),
                               highlightthickness=0, cursor="hand2")
        self.strip.pack(pady=(4, 4))
        self.strip.bind("<Button-1>", self.on_strip_click)
        self.info = ttk.Label(top, text="")
        self.info.pack(anchor="w")
        self.own_check = ttk.Checkbutton(top, variable=self.own_var, command=self.on_own_toggle)
        self.own_check.pack(anchor="w", pady=(4, 0))
        ttk.Label(top, text="Monitors without their own grid share the default one.",
                  foreground="#777777").pack(anchor="w")

        controls = ttk.Frame(root, padding=16)
        controls.pack(fill="x")
        rows = (("Columns", "cols"), ("Rows", "rows"), ("Gap (px)", "gap"), ("Margin (px)", "margin"))
        for i, (label, key) in enumerate(rows):
            lo, hi = LIMITS[key]
            r, c = i // 2, (i % 2) * 2
            ttk.Label(controls, text=label, width=12).grid(row=r, column=c, sticky="w", pady=4)
            ttk.Spinbox(controls, from_=lo, to=hi, textvariable=self.vars[key], width=5,
                        command=self.on_value_change).grid(row=r, column=c + 1, sticky="w", padx=(0, 24))
            self.vars[key].trace_add("write", self.on_value_change)
        ttk.Label(controls, text="Gap = between zones.  Margin = around the screen edge.",
                  foreground="#777777").grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        frame = ttk.Frame(root, padding=(16, 0, 16, 0))
        frame.pack()
        self.preview = tk.Canvas(frame, width=PREVIEW_W, height=PREVIEW_H,
                                 bg=root.cget("bg"), highlightthickness=0)
        self.preview.pack()

        buttons = ttk.Frame(root, padding=16)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="left")
        ttk.Button(buttons, text="Save & Apply", command=self.save).pack(side="right")
        self.everywhere = ttk.Button(buttons, text="Use on every monitor", command=self.use_everywhere)
        if len(self.monitors) > 1:
            self.everywhere.pack(side="right", padx=8)


def open_editor():
    """
    Open the grid editor window and block until it closes.

    Returns:
        True  if the user clicked "Save & Apply"
        False if the user cancelled or closed the window
    """
    config = cfg.load_config()

    # className sets WM_CLASS, which the desktop entry's StartupWMClass matches
    root = tk.Tk(className="gridlet")
    root.title("Gridlet — Grid Editor")
    root.resizable(False, False)
    icons = load_icons()
    if icons:
        root.iconphoto(True, *icons)

    editor = GridEditor(root, config, list_monitors(root))

    # Centre the window on screen
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w  = root.winfo_width()
    h  = root.winfo_height()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    root.mainloop()
    return editor.saved


if __name__ == "__main__":
    import sys
    saved = open_editor()
    print("Saved." if saved else "Cancelled.")
    sys.exit(0 if saved else 1)
