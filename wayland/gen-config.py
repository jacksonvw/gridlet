#!/usr/bin/env python3
"""
Generate config.js (read by the KWin QML script) from ~/.config/gridlet/config.json.

The QML engine can't read the JSON file itself (no readConfig, and file:// XHR
doesn't work), but it CAN import a sibling .js. So we translate the grid settings
into a tiny .js the script imports. Run by install.sh and gridlet-dev-run.sh.

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


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "config.js"
    grid = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            user = json.load(f).get("grid", {})
    except Exception:
        user = {}  # missing/broken config → defaults
    for k in grid:
        try:
            grid[k] = max(MINIMUM[k], int(user.get(k, grid[k])))
        except (TypeError, ValueError):
            pass  # not a number → keep the default for this one
    with open(out, "w") as f:
        f.write(".pragma library\n")
        f.write("var rows = %d;\n" % grid["rows"])
        f.write("var cols = %d;\n" % grid["cols"])
        f.write("var gap = %d;\n" % grid["gap"])
        f.write("var margin = %d;\n" % grid["margin"])
    print("gridlet: config.js → rows=%(rows)d cols=%(cols)d "
          "gap=%(gap)d margin=%(margin)d" % grid)


if __name__ == "__main__":
    main()
