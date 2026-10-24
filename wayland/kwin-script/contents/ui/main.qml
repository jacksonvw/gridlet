import QtQuick
import QtQuick.Window
import org.kde.kwin as KWin
import "config.js" as GCfg    // grid settings, generated from config.json

/*
 * Gridlet — overlay + snapping engine, KWin (Wayland) port of overlay.py.
 *
 * IMPORTANT structural note: a KWin declarative script only renders on screen
 * if its ROOT object is the Window. A Window nested inside an Item root is
 * force-hidden by KWin. So the overlay Window is the root here, and all logic
 * (poll timer, shortcut bridge, functions) hangs off it.
 *
 * Faithful to the X11 original, including its poll-based loop (it polled
 * query_pointer() at 16ms active / 50ms idle). Here a Timer polls the same
 * state — activeWindow.move for the drag, cursorPos for position — and the
 * modifier arrives from the helper via GridletActivate / GridletDeactivate.
 *
 * Order of operations (as in overlay.py):
 *   - Overlay shows only while BOTH dragging a window AND holding the hotkey.
 *   - start zone = zone under cursor when the overlay first appears.
 *   - Selection = rectangle spanning start zone → current zone (multi-zone
 *     paint), grown so that zones merged in the editor are taken whole.
 *   - Look: 30% dim, zones separated by gap; non-selected = white outline,
 *     selected = filled white.
 *   - Release hotkey first = cancel, but a 330ms grace still allows the
 *     mouse-release snap.
 *
 * Unlike the X11 original, the grid can differ per monitor, and its columns,
 * rows and zones can be laid out freely in the Grid Editor.
 */
Window {
    id: overlay

    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput
    // Shown only during the gesture (visible toggled). NOTE: do NOT keep this
    // Window permanently mapped — Qt.WindowTransparentForInput is not honored on
    // this KWin/Wayland, so an always-mapped fullscreen overlay swallows all
    // clicks. It's only safe because it exists solely while KWin owns the drag.
    // Transparent at the Window level; the 30% dim is a Rectangle inside
    // fadeLayer instead, so it can fade in with the grid. Animating the
    // scene-graph rather than the Window's own opacity keeps this ordinary QML
    // rendering, independent of whether the compositor honours surface opacity.
    color: "transparent"
    visible: false

    // ---- config (from config.js, generated from ~/.config/gridlet/config.json) ----
    // The default grid, and each monitor's own grid by connector name (e.g.
    // "DP-1"). Monitors without their own use the default.
    readonly property var defaultGrid: GCfg.grid
    readonly property var monitorGrids: GCfg.monitors

    // The grid in use, set from the monitor under the cursor when the overlay
    // appears.
    property int rows: defaultGrid.rows
    property int cols: defaultGrid.cols
    // gap    = space BETWEEN adjacent zones
    // margin = space between the grid and the work-area edge
    // These are independent: the old single `gap` was inset on every side of
    // every cell, which forced edge spacing to be exactly half the spacing
    // between cells. Now each is set on its own.
    property int gap: defaultGrid.gap
    property int margin: defaultGrid.margin

    readonly property var ws: KWin.Workspace

    // ---- interaction state (mirrors overlay.py) ----
    property bool modHeld: false
    property bool dragging: false
    property var draggedWindow: null
    property bool overlayShown: false
    property bool snapSessionActive: false
    property var pendingGeometry: null
    property double snapGraceUntil: 0

    // ---- session geometry (locked when the overlay appears) ----
    property rect workArea: Qt.rect(0, 0, 0, 0)
    // Cell edges inside the work area (column c spans colStart[c]..colEnd[c]),
    // the zones as cell spans {c0, r0, c1, r1}, and the zone of every cell
    // (zoneAt[row][col]). A zone is one cell, or several merged in the editor.
    // Replaced as one object, so the zones never see a half-updated layout.
    property var layout: ({ "colStart": [], "colEnd": [], "rowStart": [], "rowEnd": [],
                            "zones": [], "zoneAt": [] })
    property int startZone: -1

    // ---- selection bounds for highlighting (a rectangle of cells) ----
    property int selMinCol: -1
    property int selMaxCol: -1
    property int selMinRow: -1
    property int selMaxRow: -1

    // =====================================================================
    //  Fade — everything visible lives under this, so one opacity animation
    //  brings up the dim and the grid together. KWin's own map animation (the
    //  Scale effect) is off; this replaces it with something subtler that we
    //  control. Fade IN only: the overlay swallows clicks while it is mapped,
    //  so fading OUT would keep it eating input after the mouse is released.
    // =====================================================================
    Item {
        id: fadeLayer
        anchors.fill: parent
        opacity: 0

        Rectangle {         // the 30% black dim, matching the X11 overlay
            anchors.fill: parent
            color: "#4D000000"
        }

        // =====================================================================
        //  Grid — drawn only inside the work area; the rest is the plain dim.
        // =====================================================================
        Item {
            id: gridLayer
            x: overlay.workArea.x - overlay.x
            y: overlay.workArea.y - overlay.y
            width: overlay.workArea.width
            height: overlay.workArea.height

            Repeater {
                model: overlay.layout.zones.length
                Rectangle {
                    // A zone can briefly be missing while the Repeater rebuilds
                    // for a layout with fewer zones; it then draws as nothing.
                    property var span: overlay.layout.zones[index] || ({ "c0": 0, "r0": 0, "c1": -1, "r1": -1 })
                    property bool sel: overlay.selMinCol >= 0 &&
                                       span.c0 >= overlay.selMinCol && span.c1 <= overlay.selMaxCol &&
                                       span.r0 >= overlay.selMinRow && span.r1 <= overlay.selMaxRow
                    // A zone of several cells absorbs the gaps between them.
                    x: overlay.layout.colStart[span.c0] || 0
                    y: overlay.layout.rowStart[span.r0] || 0
                    width: (overlay.layout.colEnd[span.c1] - overlay.layout.colStart[span.c0]) || 0
                    height: (overlay.layout.rowEnd[span.r1] - overlay.layout.rowStart[span.r0]) || 0
                    // Matches the X11 original: 30% white lines / 30% white fill.
                    color: sel ? "#4DFFFFFF" : "transparent"
                    border.color: "#4DFFFFFF"
                    border.width: sel ? 0 : 1
                }
            }
        }
    }   // fadeLayer

    // Explicit animation rather than `Behavior on opacity`, so hideOverlay can
    // stop it and reset to 0 deterministically — otherwise a quick re-drag
    // could start the next fade from a half-finished value.
    NumberAnimation {
        id: fadeIn
        target: fadeLayer
        property: "opacity"
        from: 0; to: 1
        duration: 200
        easing.type: Easing.OutCubic
    }

    // =====================================================================
    //  Modifier bridge — the helper invokes these over kglobalaccel
    // =====================================================================
    KWin.ShortcutHandler {
        name: "GridletActivate"
        text: "Gridlet: hotkey pressed (internal)"
        sequence: ""
        onActivated: { overlay.modHeld = true; console.warn("Gridlet: hotkey DOWN"); overlay.reevaluate(); }
    }
    KWin.ShortcutHandler {
        name: "GridletDeactivate"
        text: "Gridlet: hotkey released (internal)"
        sequence: ""
        onActivated: { overlay.modHeld = false; console.warn("Gridlet: hotkey UP"); overlay.reevaluate(); }
    }

    // =====================================================================
    //  Geometry helpers
    // =====================================================================
    function activeOutput() {
        try {
            if (ws.screenAt) {
                var s = ws.screenAt(ws.cursorPos);
                if (s) return s;
            }
        } catch (e) {}
        return ws.activeScreen;
    }

    // Lay out cells along one axis of `length` pixels: the margin at both ends,
    // `gap` between neighbours, and the rest shared out by `weights`. Every
    // edge is rounded on its own, so leftover pixels spread across the cells
    // and both margins come out exactly as configured.
    function axis(length, weights) {
        var n = weights.length, total = 0, acc = 0;
        for (var i = 0; i < n; i++) total += weights[i];
        // At least 1px per cell, even if margins and gaps eat everything.
        var avail = Math.max(n, length - 2 * margin - (n - 1) * gap);
        var starts = [], ends = [];
        for (var j = 0; j < n; j++) {
            var a = Math.round(avail * acc / total);
            acc += weights[j];
            var b = Math.round(avail * acc / total);
            starts.push(margin + j * gap + a);
            ends.push(margin + j * gap + Math.max(a + 1, b));
        }
        return { "starts": starts, "ends": ends };
    }

    function equalWeights(n) {
        var w = [];
        for (var i = 0; i < n; i++) w.push(1);
        return w;
    }

    // The zones of a grid as cell spans, and the zone of every cell. Without
    // a zone map (from the editor), every cell is a zone of its own.
    // gen-config.py has checked that each zone is a filled rectangle of cells.
    function zonesOf(grid) {
        var zones = [], zoneAt = [], byIndex = {};
        for (var r = 0; r < grid.rows; r++) {
            zoneAt.push([]);
            for (var c = 0; c < grid.cols; c++) {
                var key = grid.zones ? grid.zones[r][c] : r * grid.cols + c;
                var z = byIndex[key];
                if (z === undefined) {
                    z = byIndex[key] = zones.length;
                    zones.push({ "c0": c, "r0": r, "c1": c, "r1": r });
                }
                var s = zones[z];
                s.c0 = Math.min(s.c0, c); s.c1 = Math.max(s.c1, c);
                s.r0 = Math.min(s.r0, r); s.r1 = Math.max(s.r1, r);
                zoneAt[r].push(z);
            }
        }
        return { "zones": zones, "zoneAt": zoneAt };
    }

    // Grow a rectangle of cells until it cuts through no zone, so a zone of
    // several cells is always taken whole (FancyZones' merge closure).
    function closure(c0, r0, c1, r1) {
        var zs = layout.zones, grown = true;
        while (grown) {
            grown = false;
            for (var i = 0; i < zs.length; i++) {
                var z = zs[i];
                var overlaps = z.c0 <= c1 && z.c1 >= c0 && z.r0 <= r1 && z.r1 >= r0;
                var inside = z.c0 >= c0 && z.c1 <= c1 && z.r0 >= r0 && z.r1 <= r1;
                if (overlaps && !inside) {
                    c0 = Math.min(c0, z.c0); c1 = Math.max(c1, z.c1);
                    r0 = Math.min(r0, z.r0); r1 = Math.max(r1, z.r1);
                    grown = true;
                }
            }
        }
        return { "c0": c0, "r0": r0, "c1": c1, "r1": r1 };
    }

    // Which cell along an axis holds `pos`: each cell owns the gap after it,
    // and the margins clamp to the first and last cells.
    function indexAt(pos, starts) {
        var i = 0;
        while (i + 1 < starts.length && pos >= starts[i + 1]) i++;
        return i;
    }

    // Hit test. There are no dead zones: dragging over a gap or into the
    // margin still selects the neighbouring cell rather than nothing.
    function cellAt(px, py) {
        var lx = px - workArea.x;
        var ly = py - workArea.y;
        if (lx < 0 || ly < 0 || lx >= workArea.width || ly >= workArea.height)
            return null;
        return { "col": indexAt(lx, layout.colStart), "row": indexAt(ly, layout.rowStart) };
    }

    function computeZone(c1, r1, c2, r2) {
        var minC = Math.min(c1, c2), maxC = Math.max(c1, c2);
        var minR = Math.min(r1, r2), maxR = Math.max(r1, r2);
        // A multi-cell zone absorbs the gaps between the cells it spans.
        var l = layout;
        return {
            "x": workArea.x + l.colStart[minC],
            "y": workArea.y + l.rowStart[minR],
            "w": l.colEnd[maxC] - l.colStart[minC],
            "h": l.rowEnd[maxR] - l.rowStart[minR]
        };
    }

    // =====================================================================
    //  Overlay show / hide / highlight
    // =====================================================================
    function showOverlay() {
        var out = activeOutput();
        workArea = ws.clientArea(0, out, ws.currentDesktop);
        var g = out.geometry;
        overlay.x = g.x; overlay.y = g.y;
        overlay.width = g.width; overlay.height = g.height;
        var grid = monitorGrids[out.name] || defaultGrid;
        rows = grid.rows; cols = grid.cols;
        gap = grid.gap; margin = grid.margin;
        // Cells share out what's left after the outer margins and the inter-cell
        // gaps are taken off, by the column and row sizes set in the editor.
        var cx = axis(workArea.width, grid.col_sizes || equalWeights(cols));
        var cy = axis(workArea.height, grid.row_sizes || equalWeights(rows));
        var zs = zonesOf(grid);
        layout = { "colStart": cx.starts, "colEnd": cx.ends,
                   "rowStart": cy.starts, "rowEnd": cy.ends,
                   "zones": zs.zones, "zoneAt": zs.zoneAt };

        startZone = -1;
        selMinCol = -1;
        pendingGeometry = null;
        snapSessionActive = true;
        snapGraceUntil = 0;

        // Highlight before the fade starts, so the first frame drawn already
        // has the correct cell selected rather than flashing an empty grid.
        overlay.visible = true;
        overlay.raise();
        overlayShown = true;
        updateHighlight();
        fadeIn.restart();
        console.warn("Gridlet: ▶ overlay shown  " + out.name +
              (monitorGrids[out.name] ? " (own grid)" : " (default grid)") +
              "  screen=" + g.width + "x" + g.height +
              "  work=" + workArea.width + "x" + workArea.height + "  cell=" +
              (cx.ends[0] - cx.starts[0]) + "x" + (cy.ends[0] - cy.starts[0]) +
              "  grid=" + cols + "x" + rows + "  zones=" + zs.zones.length +
              "  gap=" + gap + " margin=" + margin);
    }

    function hideOverlay() {
        fadeIn.stop();          // reset deterministically for the next show
        fadeLayer.opacity = 0;
        overlay.visible = false;
        overlayShown = false;
        selMinCol = -1;       // clear highlight (keep pendingGeometry for grace snap)
    }

    function updateHighlight() {
        if (!overlayShown) return;
        var cp = ws.cursorPos;
        var cell = cellAt(cp.x, cp.y);
        if (!cell) return;
        // The zone painted from is the one under the cursor when the overlay
        // appeared; the selection runs from it to the zone under the cursor now.
        var here = layout.zoneAt[cell.row][cell.col];
        if (startZone < 0) startZone = here;
        var a = layout.zones[startZone], b = layout.zones[here];
        var s = closure(Math.min(a.c0, b.c0), Math.min(a.r0, b.r0),
                        Math.max(a.c1, b.c1), Math.max(a.r1, b.r1));
        selMinCol = s.c0; selMaxCol = s.c1;
        selMinRow = s.r0; selMaxRow = s.r1;
        pendingGeometry = computeZone(s.c0, s.r0, s.c1, s.r1);
    }

    // Overlay visible iff (hotkey held) AND (dragging a window).
    function reevaluate() {
        var shouldShow = modHeld && dragging;
        if (shouldShow && !overlayShown) {
            showOverlay();
        } else if (!shouldShow && overlayShown) {
            hideOverlay();
            if (dragging && !modHeld) {          // hotkey released mid-drag → grace
                snapGraceUntil = Date.now() + 330;
                snapSessionActive = false;
                console.warn("Gridlet: hotkey released — 330ms grace");
            }
        }
    }

    function snapTo(w) {
        if (!w || !pendingGeometry) return;
        var pg = pendingGeometry;
        try { w.setMaximize(false, false); } catch (e) {}
        // Releasing at a screen edge can also make KWin quick-tile the window,
        // which would leave it tied to that tile. Untile first: untiling puts
        // back the window's old geometry, so it must come before ours.
        try { if (w.tile) w.tile = null; } catch (e) {}
        try {
            w.frameGeometry = Qt.rect(pg.x, pg.y, pg.w, pg.h);
            console.warn("Gridlet: ✓ snapped '" + w.caption + "' to " +
                  pg.x + "," + pg.y + " " + pg.w + "x" + pg.h);
        } catch (e) { console.warn("Gridlet: ✗ snap failed: " + e); }
    }

    // =====================================================================
    //  Poll loop — mirrors overlay.py's event loop.
    // =====================================================================
    Timer {
        id: pollTimer
        interval: 50; repeat: true; running: true
        onTriggered: overlay.poll()
    }

    function poll() {
        var w = ws.activeWindow;
        var isDrag = !!(w && w.normalWindow && w.move);

        if (isDrag && !dragging) {
            dragging = true;
            draggedWindow = w;
            pollTimer.interval = 16;
            console.warn("Gridlet: drag start '" + w.caption + "'");
            reevaluate();
        } else if (!isDrag && dragging) {
            dragging = false;
            pollTimer.interval = 50;
            var withinGrace = snapGraceUntil > 0 && Date.now() < snapGraceUntil;
            if (snapSessionActive || withinGrace) snapTo(draggedWindow);
            hideOverlay();
            snapSessionActive = false;
            snapGraceUntil = 0;
            draggedWindow = null;
        } else if (isDrag) {
            if (overlayShown) updateHighlight();
            else if (modHeld) reevaluate();
        }
    }

    Component.onCompleted: console.warn("Gridlet: engine loaded (" + cols + "x" + rows +
        ", gap " + gap + ", margin " + margin +
        (Object.keys(monitorGrids).length ? "; own grids: " + Object.keys(monitorGrids).join(", ") : "") +
        ") — root-Window, poll-based");
}
