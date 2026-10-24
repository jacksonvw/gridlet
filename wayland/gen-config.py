#!/usr/bin/env python3
"""
Generate config.js (read by the KWin QML script) from ~/.config/gridlet/config.json.

The QML engine can't read the JSON file itself (no readConfig, and file:// XHR
doesn't work), but it CAN import a sibling .js. So we translate the grid settings
into a tiny .js the script imports. Run by install.sh and gridlet-dev-run.sh.

It holds the default grid and, by connector name, each monitor's own grid:
    var grid = {"rows": 4, "cols": 6, "gap": 8, "margin": 4};
    var monitors = {"DP-1": {"rows": 2, "cols": 3, "gap": 8, "margin": 4}};
A grid laid out in the editor also carries "col_sizes", "row_sizes" and a
"zones" map (see layout.py).

Usage: gen-config.py <output-path>
"""
import json
import os
import sys

from layout import Layout

CONFIG_FILE = os.path.expanduser("~/.config/gridlet/config.json")
# Same as config.py. gap = space between zones, margin = space at the screen edge.
DEFAULTS = {"rows": 4, "cols": 6, "gap": 8, "margin": 4}
# The smallest value each setting may take. A hand-edited zero or negative
# would otherwise reach the engine, which divides by the row and column counts.
MINIMUM = {"rows": 1, "cols": 1, "gap": 0, "margin": 0}


# The keys that describe a grid's zones, as opposed to its spacing.
LAYOUT_KEYS = ("cols", "rows", "col_sizes", "row_sizes", "zones")


def clean(grid, fallback):
    """One grid's settings as whole numbers within range, plus its zones.
    Anything missing or not a number keeps its value from `fallback`, and a
    grid that says nothing about its zones takes fallback's zones too."""
    if not isinstance(grid, dict):
        grid = {}
    out = {}
    for k in DEFAULTS:
        try:
            out[k] = max(MINIMUM[k], int(grid.get(k, fallback[k])))
        except (TypeError, ValueError):
            out[k] = fallback[k]  # not a number → keep the fallback
    src = grid if any(k in grid for k in LAYOUT_KEYS) else fallback
    # Sizes or a zone map that don't fit the grid are dropped by Layout, and
    # an even grid of single-cell zones comes back as just cols and rows.
    out.update(Layout.from_grid({"cols": out["cols"], "rows": out["rows"],
                                 "col_sizes": src.get("col_sizes"),
                                 "row_sizes": src.get("row_sizes"),
                                 "zones": src.get("zones")}).to_grid())
    return out


def summary(grid):
    zones = len({z for row in grid["zones"] for z in row}) if "zones" in grid else None
    return ("%(cols)dx%(rows)d" % grid + (" (%d zones)" % zones if zones else "") +
            " gap=%(gap)d margin=%(margin)d" % grid)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "config.js"
    try:
        with open(CONFIG_FILE) as f:
            user = json.load(f)
    except Exception:
        user = {}  # missing/broken config → defaults
    if not isinstance(user, dict):
        user = {}
    grid = clean(user.get("grid", {}), DEFAULTS)
    monitors = {}
    own = user.get("monitors")
    for name, g in (own.items() if isinstance(own, dict) else ()):
        if isinstance(g, dict):
            # A monitor's grid only overrides what it sets; the rest is the default.
            monitors[str(name)] = clean(g, grid)
    with open(out, "w") as f:
        f.write(".pragma library\n")
        f.write("var grid = %s;\n" % json.dumps(grid))
        f.write("var monitors = %s;\n" % json.dumps(monitors, sort_keys=True))
    print("gridlet: config.js → default " + summary(grid) + "".join(
        "; %s %s" % (name, summary(g)) for name, g in sorted(monitors.items())))


if __name__ == "__main__":
    main()
