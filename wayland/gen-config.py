#!/usr/bin/env python3
"""
Generate config.js (read by the KWin QML script) from ~/.config/gridlet/config.json.

The QML engine can't read the JSON file itself (no readConfig, and file:// XHR
doesn't work), but it CAN import a sibling .js. So we translate the grid settings
into a tiny .js the script imports. Run by install.sh and gridlet-dev-run.sh.

It holds the default grid and, by connector name, each monitor's own grid:
    var grid = {"rows": 4, "cols": 6, "gap": 8, "margin": 4};
    var monitors = {"DP-1": {"rows": 2, "cols": 3, "gap": 8, "margin": 4}};

Usage: gen-config.py <output-path>
"""
import json
import os
import sys

CONFIG_FILE = os.path.expanduser("~/.config/gridlet/config.json")
# Same as config.py. gap = space between zones, margin = space at the screen edge.
DEFAULTS = {"rows": 4, "cols": 6, "gap": 8, "margin": 4}
# The smallest value each setting may take. A hand-edited zero or negative
# would otherwise reach the engine, which divides by the row and column counts.
MINIMUM = {"rows": 1, "cols": 1, "gap": 0, "margin": 0}


def clean(grid, fallback):
    """One grid's settings as whole numbers within range. Anything missing or
    not a number keeps its value from `fallback`."""
    out = dict(fallback)
    for k in out:
        try:
            out[k] = max(MINIMUM[k], int(grid.get(k, out[k])))
        except (AttributeError, TypeError, ValueError):
            pass  # not a number (or not a grid at all) → keep the fallback
    return out


def summary(grid):
    return "%(cols)dx%(rows)d gap=%(gap)d margin=%(margin)d" % grid


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
