#!/usr/bin/env python3
"""
Gridlet — zone layouts

A layout is a set of rectangular zones that tile the grid. It is modelled the
way the FancyZones grid editor models one: each zone is a rectangle in a
UNIT × UNIT space, and every distinct zone edge is a grid line. So the zones
give the grid the KWin script draws — how wide each column and how tall each
row is, and which zone each cell belongs to — and the grid gives the zones.

  - Splitting a zone adds a grid line through that zone only.
  - Merging zones replaces them by their bounding rectangle, grown until it
    cuts through no other zone.
  - A divider is a stretch of grid line with different zones on its two
    sides; moving it moves every zone edge along that stretch.

In config.json a grid is stored as
    {"cols": 3, "rows": 2, "col_sizes": [2500, 5000, 2500],
     "row_sizes": [5000, 5000], "zones": [[0, 1, 2], [0, 3, 4]], ...}
where the sizes are relative and "zones" maps each cell, row by row, to its
zone. An even grid of single-cell zones needs only "cols" and "rows".
"""

import math

UNIT = 10000    # the layout's coordinate space along each axis


def js_round(x):
    """Round half up, like JavaScript's Math.round, which the engine uses."""
    return math.floor(x + 0.5)


def axis_px(length, sizes, gap, margin):
    """
    Lay out cells along one axis of `length` pixels exactly as the KWin script
    does: the margin at both ends, `gap` between neighbours, the rest shared
    out by `sizes`, each edge rounded on its own. Returns (starts, ends).
    """
    n, total, acc = len(sizes), sum(sizes), 0
    avail = max(n, length - 2 * margin - (n - 1) * gap)
    starts, ends = [], []
    for j, size in enumerate(sizes):
        a = js_round(avail * acc / total)
        acc += size
        b = js_round(avail * acc / total)
        starts.append(margin + j * gap + a)
        ends.append(margin + j * gap + max(a + 1, b))
    return starts, ends


def split_evenly(total, n):
    """n whole numbers that add up to `total`, as even as they can be."""
    return [(total * (i + 1)) // n - (total * i) // n for i in range(n)]


class Divider:
    """A stretch of grid line with different zones on its two sides.

    axis "v" is a vertical line at x = pos, running from y = start to y = end,
    with `before` the zones to its left and `after` those to its right; "h" is
    a horizontal line at y = pos, from x = start to x = end, `before` above.
    """

    def __init__(self, axis, pos, start, end, before, after):
        self.axis, self.pos, self.start, self.end = axis, pos, start, end
        self.before, self.after = before, after

    def __repr__(self):
        return "Divider(%s %d %d-%d %s|%s)" % (self.axis, self.pos, self.start, self.end,
                                               self.before, self.after)


class Layout:
    """Zones as (x0, y0, x1, y1) rectangles in UNIT space, in reading order."""

    def __init__(self, zones):
        self.zones = sorted((tuple(z) for z in zones), key=lambda z: (z[1], z[0]))

    # ── Conversions ──────────────────────────────────────────────────────────

    @classmethod
    def even(cls, cols, rows):
        xs = [0] + _cumulative(split_evenly(UNIT, cols))
        ys = [0] + _cumulative(split_evenly(UNIT, rows))
        return cls([(xs[c], ys[r], xs[c + 1], ys[r + 1])
                    for r in range(rows) for c in range(cols)])

    @classmethod
    def from_grid(cls, grid):
        """The layout a config grid describes. Sizes or a zone map that don't
        fit the grid are ignored, leaving even sizes and one zone per cell."""
        cols, rows = int(grid.get("cols", 1)), int(grid.get("rows", 1))
        col_sizes = _sizes(grid.get("col_sizes"), cols)
        row_sizes = _sizes(grid.get("row_sizes"), rows)
        xs = [0] + _cumulative(_to_units(col_sizes))
        ys = [0] + _cumulative(_to_units(row_sizes))
        spans = _zone_spans(grid.get("zones"), cols, rows)
        if spans is None:
            spans = [(c, r, c, r) for r in range(rows) for c in range(cols)]
        return cls([(xs[c0], ys[r0], xs[c1 + 1], ys[r1 + 1]) for c0, r0, c1, r1 in spans])

    def lines(self):
        """The grid lines: the distinct zone edges along x and along y."""
        xs = sorted({z[0] for z in self.zones} | {z[2] for z in self.zones})
        ys = sorted({z[1] for z in self.zones} | {z[3] for z in self.zones})
        return xs, ys

    def cell_map(self):
        """For each row of cells, the index of the zone each cell is in."""
        xs, ys = self.lines()
        grid = [[0] * (len(xs) - 1) for _ in range(len(ys) - 1)]
        for i, (x0, y0, x1, y1) in enumerate(self.zones):
            for r in range(ys.index(y0), ys.index(y1)):
                for c in range(xs.index(x0), xs.index(x1)):
                    grid[r][c] = i
        return grid

    def is_even_grid(self):
        """Every cell its own zone, and the cells as even as they can be."""
        xs, ys = self.lines()
        cols, rows = len(xs) - 1, len(ys) - 1
        return (len(self.zones) == cols * rows
                and _diffs(xs) == split_evenly(UNIT, cols)
                and _diffs(ys) == split_evenly(UNIT, rows))

    def to_grid(self):
        """The config grid for this layout (without gap and margin)."""
        xs, ys = self.lines()
        grid = {"cols": len(xs) - 1, "rows": len(ys) - 1}
        if not self.is_even_grid():
            grid["col_sizes"] = _diffs(xs)
            grid["row_sizes"] = _diffs(ys)
            grid["zones"] = self.cell_map()
        return grid

    # ── Queries ──────────────────────────────────────────────────────────────

    def zone_at(self, x, y):
        """The zone containing the point, a zone's right/bottom edge counting
        as the next zone's."""
        for i, (x0, y0, x1, y1) in enumerate(self.zones):
            if x0 <= x < x1 and y0 <= y < y1:
                return i
        # The far edges themselves: clamp to the last zone along them.
        x, y = min(x, UNIT - 1), min(y, UNIT - 1)
        for i, (x0, y0, x1, y1) in enumerate(self.zones):
            if x0 <= x < x1 and y0 <= y < y1:
                return i
        return None

    def closure(self, indices):
        """The zones to merge for `indices`: their bounding rectangle, grown
        until it cuts through no other zone, and every zone inside it."""
        if not indices:
            return [], None
        x0 = min(self.zones[i][0] for i in indices)
        y0 = min(self.zones[i][1] for i in indices)
        x1 = max(self.zones[i][2] for i in indices)
        y1 = max(self.zones[i][3] for i in indices)
        grown = True
        while grown:
            grown = False
            for zx0, zy0, zx1, zy1 in self.zones:
                overlap = max(0, min(x1, zx1) - max(x0, zx0)) * max(0, min(y1, zy1) - max(y0, zy0))
                if overlap and overlap != (zx1 - zx0) * (zy1 - zy0):
                    x0, y0 = min(x0, zx0), min(y0, zy0)
                    x1, y1 = max(x1, zx1), max(y1, zy1)
                    grown = True
        inside = [i for i, (zx0, zy0, zx1, zy1) in enumerate(self.zones)
                  if x0 <= zx0 and zx1 <= x1 and y0 <= zy0 and zy1 <= y1]
        return inside, (x0, y0, x1, y1)

    def dividers(self):
        """Every divider, found where neighbouring cells belong to different
        zones; runs of such cells along one grid line make one divider."""
        xs, ys = self.lines()
        grid = self.cell_map()
        rows, cols = len(ys) - 1, len(xs) - 1
        found = []
        for c in range(1, cols):            # vertical lines, between columns c-1 and c
            r = 0
            while r < rows:
                if grid[r][c - 1] == grid[r][c]:
                    r += 1
                    continue
                end = r
                while end + 1 < rows and grid[end + 1][c - 1] != grid[end + 1][c]:
                    end += 1
                found.append(Divider("v", xs[c], ys[r], ys[end + 1],
                                     _unique(grid[k][c - 1] for k in range(r, end + 1)),
                                     _unique(grid[k][c] for k in range(r, end + 1))))
                r = end + 1
        for r in range(1, rows):            # horizontal lines, between rows r-1 and r
            c = 0
            while c < cols:
                if grid[r - 1][c] == grid[r][c]:
                    c += 1
                    continue
                end = c
                while end + 1 < cols and grid[r - 1][end + 1] != grid[r][end + 1]:
                    end += 1
                found.append(Divider("h", ys[r], xs[c], xs[end + 1],
                                     _unique(grid[r - 1][k] for k in range(c, end + 1)),
                                     _unique(grid[r][k] for k in range(c, end + 1))))
                c = end + 1
        return found

    # ── Edits ────────────────────────────────────────────────────────────────
    # Each returns the new Layout, or None if the edit would make a zone
    # narrower than min_w or shorter than min_h (both in UNIT space).

    def split(self, index, axis, pos, min_w=1, min_h=1):
        """Split a zone with a vertical ("v", at x = pos) or horizontal ("h",
        at y = pos) line."""
        x0, y0, x1, y1 = self.zones[index]
        if axis == "v":
            if not x0 + min_w <= pos <= x1 - min_w:
                return None
            parts = [(x0, y0, pos, y1), (pos, y0, x1, y1)]
        else:
            if not y0 + min_h <= pos <= y1 - min_h:
                return None
            parts = [(x0, y0, x1, pos), (x0, pos, x1, y1)]
        return Layout(self.zones[:index] + parts + self.zones[index + 1:])

    def merge(self, indices):
        inside, rect = self.closure(indices)
        if len(inside) < 2:
            return None
        return Layout([z for i, z in enumerate(self.zones) if i not in inside] + [rect])

    def move(self, divider, pos, min_w=1, min_h=1):
        """Move a divider to `pos`, taking the zone edges along it with it."""
        lo, hi = (0, 2) if divider.axis == "v" else (1, 3)
        least = min_w if divider.axis == "v" else min_h
        zones = list(self.zones)
        for i in divider.before:
            z = list(zones[i])
            z[hi] = pos
            if z[hi] - z[lo] < least:
                return None
            zones[i] = tuple(z)
        for i in divider.after:
            z = list(zones[i])
            z[lo] = pos
            if z[hi] - z[lo] < least:
                return None
            zones[i] = tuple(z)
        return Layout(zones)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cumulative(values):
    out, acc = [], 0
    for v in values:
        acc += v
        out.append(acc)
    return out


def _diffs(values):
    return [b - a for a, b in zip(values, values[1:])]


def _unique(values):
    out = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


def _sizes(sizes, n):
    """Relative sizes as given, if there are n of them and all positive;
    otherwise n equal ones."""
    try:
        sizes = [float(s) for s in sizes]
        if len(sizes) == n and all(s > 0 for s in sizes):
            return sizes
    except (TypeError, ValueError):
        pass
    return [1.0] * n


def _to_units(sizes):
    """Relative sizes as whole numbers of UNIT that add up to UNIT exactly.
    Edges round down, as split_evenly's do, so equal sizes come out even."""
    total = sum(sizes)
    edges = [math.floor(UNIT * acc / total + 1e-9) for acc in _cumulative(sizes)]
    edges[-1] = UNIT
    return _diffs([0] + edges)


def _zone_spans(zones, cols, rows):
    """Each zone's (c0, r0, c1, r1) cell span from a zone map, or None if the
    map doesn't fit the grid or a zone isn't a filled rectangle of cells."""
    try:
        if len(zones) != rows or any(len(row) != cols for row in zones):
            return None
        spans = {}
        for r, row in enumerate(zones):
            for c, z in enumerate(row):
                z = int(z)
                c0, r0, c1, r1 = spans.get(z, (c, r, c, r))
                spans[z] = (min(c0, c), min(r0, r), max(c1, c), max(r1, r))
        for z, (c0, r0, c1, r1) in spans.items():
            if any(int(zones[r][c]) != z for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)):
                return None
        return list(spans.values())
    except (TypeError, ValueError):
        return None
