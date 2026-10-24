#!/usr/bin/env python3
"""
Gridlet — Grid Editor

A settings window for the zone grid, per monitor:
  - A strip of your monitors, as they're arranged. Click one to choose it.
  - Whether that monitor has its own grid. Monitors without one share the
    default grid, so with a single monitor there is nothing to choose.
  - The layout, edited the way the FancyZones grid editor works, on the
    chosen monitor in miniature:
      click a zone to split it (hold Shift to split it the other way),
      drag a divider's handle to move it,
      drag across zones and press Merge to make them one,
      right-click a divider to remove it.
    Each zone shows its number and its size in pixels on that monitor.
  - Columns (1–16) and rows (1–12) start an even grid.
  - Gap between zones in pixels (0–32), margin from the screen edge (0–64).

Opens from the tray icon's "Grid Editor" menu item, or standalone:
    python3 editor.py

Saves changes to ~/.config/gridlet/config.json.
Returns True (saved) or False (cancelled) when called as open_editor().
"""

import json
import os
import subprocess
import tempfile
import tkinter as tk
from tkinter import messagebox, ttk

import config as cfg
from layout import Layout, UNIT, axis_px


# The boxes the monitor strip and the designer are drawn in. Each monitor
# keeps its own shape inside them.
STRIP_W, STRIP_H = 640, 120
DESIGN_W, DESIGN_H = 640, 360

# Each setting's range, as the spinboxes offer it.
LIMITS = {"cols": (1, 16), "rows": (1, 12), "gap": (0, 32), "margin": (0, 64)}

MIN_ZONE_PX = 48    # no zone narrower or shorter than this on the monitor
SNAP_PX = 6         # split lines and dividers snap to grid lines this close
DRAG_PX = 4         # a press that moves further than this is a drag

# Colours: background, zone fill, zone outline, whatever isn't selected,
# a zone picked for merging, and labels.
BG, CELL, LINE, DIM = "#1c1c2d", "#2a2a4a", "#9090cc", "#444466"
PICKED, TEXT = "#4a4a8a", "#c8c8ec"

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


# The KWin script that reports each monitor's work area back to the editor.
WORK_AREA_SCRIPT = """
var ss = workspace.screens, areas = {};
for (var i = 0; i < ss.length; i++) {
    var a = workspace.clientArea(0, ss[i], workspace.currentDesktop);
    areas[ss[i].name] = [a.x, a.y, a.width, a.height];
}
callDBus("%(service)s", "/WorkAreas", "org.gridlet.WorkAreas", "Report", JSON.stringify(areas));
"""


def kwin_work_areas(timeout=2.0):
    """
    Each monitor's work area (the part its panels leave free) as KWin sees
    it: {connector name: (x, y, w, h)} in logical pixels.

    Only KWin knows the work areas, so this loads a one-off KWin script that
    calls back over D-Bus with them. Returns {} if that doesn't work, and the
    editor then measures zones on the whole monitor instead.
    """
    try:
        import dbus
        import dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
    except ImportError:
        return {}
    got = {}
    try:
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        loop = GLib.MainLoop()

        class Receiver(dbus.service.Object):
            @dbus.service.method("org.gridlet.WorkAreas", in_signature="s")
            def Report(self, text):
                got.update(json.loads(text))
                loop.quit()

        receiver = Receiver(bus, "/WorkAreas")
        scripting = dbus.Interface(bus.get_object("org.kde.KWin", "/Scripting"),
                                   "org.kde.kwin.Scripting")
        fd, path = tempfile.mkstemp(suffix=".js", dir=os.environ.get("XDG_RUNTIME_DIR"))
        with os.fdopen(fd, "w") as f:
            f.write(WORK_AREA_SCRIPT % {"service": bus.get_unique_name()})
        plugin = "gridlet-editor-%d" % os.getpid()
        try:
            # loadScript is overloaded; ask for the (path, plugin name) one.
            scripting.loadScript(path, plugin, signature="ss")
            # start() runs whatever is loaded and not yet running. (The
            # script's own object path can't be trusted: KWin reuses ids.)
            scripting.start()
            GLib.timeout_add(int(timeout * 1000), loop.quit)
            loop.run()
        finally:
            scripting.unloadScript(plugin)
            os.remove(path)
            receiver.remove_from_connection()
    except Exception:
        pass
    return {name: tuple(int(v) for v in area) for name, area in got.items()}


def list_monitors(root):
    """
    The enabled monitors, left to right, as dicts with "name" (the connector
    name, which the KWin script goes by too), "x", "y", "w", "h" in the
    logical pixels the grid is laid out in, "primary", and "work": the
    (x, y, w, h) its panels leave free, which is what the grid fills.

    Tk only knows the combined desktop, which spans every monitor, so ask
    KScreen. Without it, this returns one unnamed monitor the size of Tk's
    screen, which can only use the default grid.
    """
    monitors = []
    try:
        out = subprocess.run(["kscreen-doctor", "-j"], capture_output=True,
                             text=True, timeout=3).stdout
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
    except Exception:
        pass
    if not monitors:
        monitors = [{"name": None, "x": 0, "y": 0, "w": root.winfo_screenwidth(),
                     "h": root.winfo_screenheight(), "primary": True}]
    areas = kwin_work_areas() if monitors[0]["name"] else {}
    for m in monitors:
        m["work"] = areas.get(m["name"], (m["x"], m["y"], m["w"], m["h"]))
    return sorted(monitors, key=lambda m: (m["x"], m["y"]))


def fit(w, h, box_w, box_h):
    """Scale factor and size of the largest w×h-shaped rectangle in the box."""
    s = min(box_w / w, box_h / h)
    return s, w * s, h * s


class AxisMap:
    """
    Converts along one axis between layout units and pixels on the monitor,
    exactly as the KWin script will place the cells: a position inside a
    cell maps proportionally across it, and a grid line sits in the middle
    of the gap that separates its two cells.
    """

    def __init__(self, lines, length, gap, margin):
        self.lines = lines
        self.starts, self.ends = axis_px(length, [b - a for a, b in zip(lines, lines[1:])],
                                         gap, margin)
        # Pixel position of every grid line, outer edges included.
        self.px = ([self.starts[0]] +
                   [(e + s) / 2 for e, s in zip(self.ends, self.starts[1:])] +
                   [self.ends[-1]])

    def to_px(self, u):
        for i in range(len(self.lines) - 1):
            a, b = self.lines[i], self.lines[i + 1]
            if u <= b or i == len(self.lines) - 2:
                if u in (a, b):
                    return self.px[i] if u == a else self.px[i + 1]
                return self.starts[i] + (u - a) / (b - a) * (self.ends[i] - self.starts[i])
        return self.px[-1]

    def to_units(self, p):
        for i in range(len(self.lines) - 1):
            if p < self.ends[i] or i == len(self.lines) - 2:
                if p <= self.starts[i]:
                    return self.lines[i]
                f = min(1.0, (p - self.starts[i]) / max(1, self.ends[i] - self.starts[i]))
                return round(self.lines[i] + f * (self.lines[i + 1] - self.lines[i]))
            if p < self.starts[i + 1]:      # in the gap after cell i: its line
                return self.lines[i + 1]
        return self.lines[-1]

    def cell_px(self, u0, u1):
        """Pixel extent of a zone spanning the lines u0..u1."""
        i, j = self.lines.index(u0), self.lines.index(u1)
        return self.starts[i], self.ends[j - 1]


class Designer:
    """
    The layout, drawn as the monitor's work area in miniature, and edited in
    place. `on_change(layout)` is called after every edit.
    """

    def __init__(self, parent, on_change):
        self.on_change = on_change
        self.canvas = tk.Canvas(parent, width=DESIGN_W, height=DESIGN_H,
                                bg=parent.winfo_toplevel().cget("bg"), highlightthickness=0)
        self.layout = Layout.even(1, 1)
        self.work = (0, 0, 1920, 1080)
        self.gap = self.margin = 0
        self.shift = False
        self.pointer = None     # where the mouse last moved over the canvas
        self.hover = None       # ("divider", index) or ("zone", index, axis, pos)
        self.press = None       # where button 1 went down, and on what
        self.dragged = None     # the layout while a divider is being dragged
        self.picked = []        # zones picked for merging
        self.merge_window = None
        c = self.canvas
        c.bind("<Motion>", self.on_motion)
        c.bind("<Leave>", self.on_leave)
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<ButtonPress-3>", self.on_right_click)
        top = parent.winfo_toplevel()
        for key in ("Shift_L", "Shift_R"):
            top.bind("<KeyPress-%s>" % key, lambda e: self.set_shift(True), add="+")
            top.bind("<KeyRelease-%s>" % key, lambda e: self.set_shift(False), add="+")
        top.bind("<Escape>", lambda e: self.cancel_merge(), add="+")

    def show(self, layout, work, gap, margin):
        self.layout, self.work, self.gap, self.margin = layout, work, gap, margin
        self.cancel_merge()
        self.hover = None
        self.redraw()

    # ── Geometry ─────────────────────────────────────────────────────────────

    def maps(self, layout=None):
        layout = layout or self.layout
        xs, ys = layout.lines()
        w, h = self.work[2], self.work[3]
        mx, my = AxisMap(xs, w, self.gap, self.margin), AxisMap(ys, h, self.gap, self.margin)
        s, pw, ph = fit(w, h, DESIGN_W, DESIGN_H)
        ox, oy = (DESIGN_W - pw) / 2, (DESIGN_H - ph) / 2
        return mx, my, s, ox, oy

    def min_units(self):
        """MIN_ZONE_PX in layout units, along x and along y."""
        xs, ys = self.layout.lines()
        w, h = self.work[2], self.work[3]
        ax = max(1, w - 2 * self.margin - (len(xs) - 2) * self.gap)
        ay = max(1, h - 2 * self.margin - (len(ys) - 2) * self.gap)
        return max(1, round(MIN_ZONE_PX / ax * UNIT)), max(1, round(MIN_ZONE_PX / ay * UNIT))

    def zone_rect(self, z, mx, my, s, ox, oy):
        """A zone's rectangle on the canvas, and its size on the monitor."""
        x0, x1 = mx.cell_px(z[0], z[2])
        y0, y1 = my.cell_px(z[1], z[3])
        return (ox + x0 * s, oy + y0 * s, ox + x1 * s, oy + y1 * s), (x1 - x0, y1 - y0)

    def divider_line(self, d, mx, my, s, ox, oy):
        """A divider as a canvas line segment: (x0, y0, x1, y1)."""
        if d.axis == "v":
            x = ox + mx.to_px(d.pos) * s
            ya, _ = my.cell_px(d.start, self.next_line(my, d.start))
            _, yb = my.cell_px(self.prev_line(my, d.end), d.end)
            return x, oy + ya * s, x, oy + yb * s
        y = oy + my.to_px(d.pos) * s
        xa, _ = mx.cell_px(d.start, self.next_line(mx, d.start))
        _, xb = mx.cell_px(self.prev_line(mx, d.end), d.end)
        return ox + xa * s, y, ox + xb * s, y

    @staticmethod
    def next_line(m, u):
        return m.lines[m.lines.index(u) + 1]

    @staticmethod
    def prev_line(m, u):
        return m.lines[m.lines.index(u) - 1]

    def snap(self, u, lines, m, s):
        """Snap a position to a grid line within SNAP_PX on the canvas."""
        best = min(lines, key=lambda line: abs(m.to_px(line) - m.to_px(u)))
        return best if abs(m.to_px(best) - m.to_px(u)) * s <= SNAP_PX else u

    def to_units(self, x, y, mx, my, s, ox, oy):
        return mx.to_units((x - ox) / s), my.to_units((y - oy) / s)

    # ── Drawing ──────────────────────────────────────────────────────────────

    def redraw(self):
        c = self.canvas
        c.delete("all")
        layout = self.dragged or self.layout
        mx, my, s, ox, oy = self.maps(layout)
        w, h = self.work[2] * s, self.work[3] * s
        c.create_rectangle(ox, oy, ox + w, oy + h, fill=BG, outline="")
        for i, z in enumerate(layout.zones):
            (l, t, r, b), (pw, ph) = self.zone_rect(z, mx, my, s, ox, oy)
            c.create_rectangle(l, t, r, b, outline=LINE, width=1,
                               fill=PICKED if i in self.picked else CELL)
            if r - l >= 44 and b - t >= 30:
                c.create_text((l + r) / 2, (t + b) / 2 - 7, text=str(i + 1), fill=TEXT,
                              font=("TkDefaultFont", 10, "bold"))
                c.create_text((l + r) / 2, (t + b) / 2 + 8, text="%d × %d" % (pw, ph),
                              fill=TEXT, font=("TkDefaultFont", 8))
        hover = self.hover
        for i, d in enumerate(layout.dividers()):
            x0, y0, x1, y1 = self.divider_line(d, mx, my, s, ox, oy)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            hw, hh = (3, 10) if d.axis == "v" else (10, 3)
            hot = hover == ("divider", i) or (self.press and self.press[0] == "divider"
                                              and self.press[1] == i)
            c.create_rectangle(cx - hw, cy - hh, cx + hw, cy + hh, outline="",
                               fill="#ffffff" if hot else LINE)
        if hover and hover[0] == "zone" and not self.picked and not self.dragged:
            _, i, axis, pos = hover
            z = layout.zones[i]
            (l, t, r, b), _ = self.zone_rect(z, mx, my, s, ox, oy)
            if axis == "v":
                x = ox + mx.to_px(pos) * s
                c.create_line(x, t, x, b, fill="#ffffff", dash=(4, 3))
            else:
                y = oy + my.to_px(pos) * s
                c.create_line(l, y, r, y, fill="#ffffff", dash=(4, 3))

    # ── Hit testing ──────────────────────────────────────────────────────────

    def divider_at(self, x, y):
        mx, my, s, ox, oy = self.maps()
        for i, d in enumerate(self.layout.dividers()):
            x0, y0, x1, y1 = self.divider_line(d, mx, my, s, ox, oy)
            reach = max(SNAP_PX, self.gap * s / 2 + 3)
            if d.axis == "v" and abs(x - x0) <= reach and y0 <= y <= y1:
                return i
            if d.axis == "h" and abs(y - y0) <= reach and x0 <= x <= x1:
                return i
        return None

    def split_at(self, x, y):
        """The zone under the point, and where clicking there would split it:
        across its longer side, or the other way while Shift is held."""
        mx, my, s, ox, oy = self.maps()
        ux, uy = self.to_units(x, y, mx, my, s, ox, oy)
        i = self.layout.zone_at(ux, uy)
        if i is None:
            return None
        z = self.layout.zones[i]
        (l, t, r, b), _ = self.zone_rect(z, mx, my, s, ox, oy)
        if not (l <= x <= r and t <= y <= b):
            return None
        axis = "v" if (r - l >= b - t) != self.shift else "h"
        xs, ys = self.layout.lines()
        if axis == "v":
            pos = self.snap(ux, xs, mx, s)
        else:
            pos = self.snap(uy, ys, my, s)
        min_w, min_h = self.min_units()
        if self.layout.split(i, axis, pos, min_w, min_h) is None:
            return None
        return i, axis, pos

    # ── Events ───────────────────────────────────────────────────────────────

    def set_shift(self, down):
        if self.shift != down:
            self.shift = down
            if self.hover and self.hover[0] == "zone":
                self.update_hover(*self.pointer)

    def on_motion(self, event):
        self.pointer = (event.x, event.y)
        self.update_hover(event.x, event.y)

    def update_hover(self, x, y):
        d = self.divider_at(x, y)
        if d is not None:
            axis = self.layout.dividers()[d].axis
            self.canvas.configure(cursor="sb_h_double_arrow" if axis == "v" else "sb_v_double_arrow")
            self.hover = ("divider", d)
        else:
            self.canvas.configure(cursor="")
            split = self.split_at(x, y)
            self.hover = ("zone",) + split if split else None
        self.redraw()

    def on_leave(self, event):
        if not self.press:
            self.hover = None
            self.redraw()

    def on_press(self, event):
        self.canvas.focus_set()
        if self.picked:
            self.cancel_merge()
        d = self.divider_at(event.x, event.y)
        self.press = ("divider", d, event.x, event.y) if d is not None else ("zone", None, event.x, event.y)

    def on_drag(self, event):
        if not self.press:
            return
        kind, d, px, py = self.press
        mx, my, s, ox, oy = self.maps()
        if kind == "divider":
            div = self.layout.dividers()[d]
            xs, ys = self.layout.lines()
            others = [l for l in (xs if div.axis == "v" else ys) if l != div.pos]
            ux, uy = self.to_units(event.x, event.y, mx, my, s, ox, oy)
            pos = self.snap(ux if div.axis == "v" else uy, others,
                            mx if div.axis == "v" else my, s)
            moved = self.layout.move(div, pos, *self.min_units())
            if moved is not None:
                self.dragged = moved
                self.redraw()
            return
        if abs(event.x - px) <= DRAG_PX and abs(event.y - py) <= DRAG_PX and not self.picked:
            return
        # A drag across zones picks them for merging.
        a = self.to_units(px, py, mx, my, s, ox, oy)
        b = self.to_units(event.x, event.y, mx, my, s, ox, oy)
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)
        # Zones the dragged rectangle overlaps, not just touches at an edge.
        hit = [i for i, z in enumerate(self.layout.zones)
               if z[0] < x1 and x0 < z[2] and z[1] < y1 and y0 < z[3]]
        self.picked = self.layout.closure(hit)[0]
        self.hover = None
        self.redraw()

    def on_release(self, event):
        press, self.press = self.press, None
        if not press:
            return
        if press[0] == "divider":
            if self.dragged is not None:
                self.layout, self.dragged = self.dragged, None
                self.changed()
            return
        if self.picked:
            if len(self.picked) > 1:
                self.offer_merge(event.x, event.y)
            else:
                self.cancel_merge()
            return
        split = self.split_at(event.x, event.y)
        if split:
            self.layout = self.layout.split(split[0], split[1], split[2], *self.min_units())
            self.changed()
            self.update_hover(event.x, event.y)

    def on_right_click(self, event):
        d = self.divider_at(event.x, event.y)
        if d is None:
            return
        menu = tk.Menu(self.canvas, tearoff=False)
        menu.add_command(label="Remove divider", command=lambda: self.remove_divider(d))
        menu.tk_popup(event.x_root, event.y_root)

    # ── Edits ────────────────────────────────────────────────────────────────

    def remove_divider(self, d):
        div = self.layout.dividers()[d]
        merged = self.layout.merge(div.before + div.after)
        if merged is not None:
            self.layout = merged
            self.changed()

    def offer_merge(self, x, y):
        frame = ttk.Frame(self.canvas, padding=4)
        ttk.Button(frame, text="Merge", command=self.merge_picked).pack(side="left")
        ttk.Button(frame, text="Cancel", command=self.cancel_merge).pack(side="left", padx=(4, 0))
        x = min(max(x, 90), DESIGN_W - 90)
        y = min(max(y, 24), DESIGN_H - 24)
        self.merge_window = self.canvas.create_window(x, y, window=frame)

    def merge_picked(self):
        merged = self.layout.merge(self.picked)
        self.cancel_merge()
        if merged is not None:
            self.layout = merged
            self.changed()

    def cancel_merge(self):
        if self.merge_window is not None:
            self.canvas.delete(self.merge_window)
            self.merge_window = None
        if self.picked:
            self.picked = []
            self.redraw()

    def changed(self):
        self.hover = None
        self.redraw()
        self.on_change(self.layout)


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

    def set_grid(self, grid):
        """Replace the grid the chosen monitor uses (its own, or the default)."""
        if self.name in self.config["monitors"]:
            self.config["monitors"][self.name] = grid
        else:
            self.config["grid"] = grid

    def spacing(self):
        """Gap and margin from the spinboxes, clamped, or None mid-edit."""
        try:
            return {k: max(LIMITS[k][0], min(LIMITS[k][1], self.vars[k].get()))
                    for k in ("gap", "margin")}
        except tk.TclError:
            return None

    def select(self, index):
        """Show monitor `index` and the grid it uses."""
        self.selected = index
        m = self.monitors[index]
        self.own_var.set(m["name"] in self.config["monitors"])
        self.own_check.configure(text="Give %s its own grid" % (m["name"] or "this screen"),
                                 state="normal" if m["name"] else "disabled")
        self.info.configure(text="%s · %d×%d%s" % (m["name"] or "Screen", m["w"], m["h"],
                                                   " · primary" if m["primary"] and len(self.monitors) > 1 else ""))
        self.load_grid()

    def load_grid(self):
        """Fill the spinboxes and the designer from the chosen monitor's grid."""
        grid = self.grid_for(self.name)
        layout = Layout.from_grid(grid)
        cols, rows = len(layout.lines()[0]) - 1, len(layout.lines()[1]) - 1
        self.loading = True
        self.vars["cols"].set(cols)
        self.vars["rows"].set(rows)
        self.vars["gap"].set(grid.get("gap", 0))
        self.vars["margin"].set(grid.get("margin", 0))
        self.loading = False
        self.show_layout(layout)

    def show_layout(self, layout):
        sp = self.spacing() or {"gap": 0, "margin": 0}
        self.designer.show(layout, self.monitors[self.selected]["work"], sp["gap"], sp["margin"])
        self.draw_monitors()

    def store(self, layout):
        """Write a layout and the spacing into the chosen monitor's grid."""
        sp = self.spacing()
        if sp is None:
            return
        self.set_grid(dict(layout.to_grid(), **sp))
        self.draw_monitors()

    def on_layout_change(self, layout):
        self.store(layout)
        self.loading = True
        self.vars["cols"].set(len(layout.lines()[0]) - 1)
        self.vars["rows"].set(len(layout.lines()[1]) - 1)
        self.loading = False

    def on_spacing_change(self, *_):
        if self.loading or self.spacing() is None:
            return  # Spinbox mid-edit — ignore invalid transient state
        self.store(self.designer.layout)
        self.show_layout(self.designer.layout)

    def on_size_change(self, *_):
        """Columns or rows changed: start an even grid of that size. Zones laid
        out by hand would be lost, so that needs a yes first."""
        if self.loading:
            return
        try:
            cols = max(LIMITS["cols"][0], min(LIMITS["cols"][1], self.vars["cols"].get()))
            rows = max(LIMITS["rows"][0], min(LIMITS["rows"][1], self.vars["rows"].get()))
        except tk.TclError:
            return
        layout = self.designer.layout
        xs, ys = layout.lines()
        if (cols, rows) == (len(xs) - 1, len(ys) - 1) and layout.is_even_grid():
            return
        if not layout.is_even_grid() and not messagebox.askyesno(
                "Even grid", "Replace the zones you laid out with an even %d × %d grid?" % (cols, rows),
                parent=self.root):
            self.load_grid()    # put the spinboxes back
            return
        even = Layout.even(cols, rows)
        self.store(even)
        self.show_layout(even)

    def on_own_toggle(self):
        """Ticked: the monitor gets its own copy of the grid it was using.
        Cleared: it goes back to the default grid."""
        if self.own_var.get():
            self.config["monitors"][self.name] = json.loads(json.dumps(self.config["grid"]))
        else:
            self.config["monitors"].pop(self.name, None)
        self.select(self.selected)

    def use_everywhere(self):
        """Make the grid on show the default and drop every monitor's own grid."""
        self.config["grid"] = json.loads(json.dumps(self.grid_for(self.name)))
        self.config["monitors"].clear()
        self.select(self.selected)

    def save(self):
        if self.spacing() is None:
            return  # Invalid value in a spinbox — don't save
        cfg.save_config(self.config)
        for name, g in [("default grid", self.config["grid"])] + sorted(self.config["monitors"].items()):
            zones = len({z for row in g["zones"] for z in row}) if "zones" in g else g["cols"] * g["rows"]
            print(f"  Saved {name}: {g['cols']} cols × {g['rows']} rows, {zones} zones, "
                  f"{g['gap']}px gap, {g['margin']}px margin")
        self.saved = True
        self.root.destroy()

    # ── Monitor strip ────────────────────────────────────────────────────────

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
                zones = len({z for row in g["zones"] for z in row}) if "zones" in g else None
                lines.append("%s %s" % ("own" if own else "default",
                                        "%d zones" % zones if zones else "%d×%d" % (g["cols"], g["rows"])))
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

        controls = ttk.Frame(root, padding=(16, 12, 16, 8))
        controls.pack(fill="x")
        fields = (("Columns", "cols", self.on_size_change), ("Rows", "rows", self.on_size_change),
                  ("Gap (px)", "gap", self.on_spacing_change),
                  ("Margin (px)", "margin", self.on_spacing_change))
        for i, (label, key, handler) in enumerate(fields):
            lo, hi = LIMITS[key]
            ttk.Label(controls, text=label).grid(row=0, column=2 * i, sticky="w", padx=(0, 6))
            ttk.Spinbox(controls, from_=lo, to=hi, textvariable=self.vars[key], width=4,
                        command=handler).grid(row=0, column=2 * i + 1, sticky="w", padx=(0, 18))
            self.vars[key].trace_add("write", handler)
        ttk.Label(controls, foreground="#777777", justify="left", text=(
            "Columns and rows start an even grid. Gap is between zones, margin around the edge.\n"
            "Click a zone to split it (Shift: the other way). Drag a handle to move a divider.\n"
            "Drag across zones to merge them. Right-click a handle to remove its divider.")
        ).grid(row=1, column=0, columnspan=8, sticky="w", pady=(8, 0))

        frame = ttk.Frame(root, padding=(16, 0, 16, 0))
        frame.pack()
        self.designer = Designer(frame, self.on_layout_change)
        self.designer.canvas.pack()

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
