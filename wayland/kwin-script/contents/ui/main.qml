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
 * Order of operations (identical to overlay.py):
 *   - Overlay shows only while BOTH dragging a window AND holding the hotkey.
 *   - start cell = cell under cursor when the overlay first appears.
 *   - Zone = rectangle spanning start cell → current cell (multi-cell paint).
 *   - Look: 30% dim, each zone inset by gap; non-selected = white outline,
 *     selected = filled white.
 *   - Release hotkey first = cancel, but a 330ms grace still allows the
 *     mouse-release snap.
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
    property int rows: GCfg.rows
    property int cols: GCfg.cols
    // gap    = space BETWEEN adjacent zones
    // margin = space between the grid and the work-area edge
    // These are independent: the old single `gap` was inset on every side of
    // every cell, which forced edge spacing to be exactly half the spacing
    // between cells. Now each is set on its own.
    property int gap: GCfg.gap
    property int margin: GCfg.margin

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
    property int cellW: 0
    property int cellH: 0
    property int startCol: -1
    property int startRow: -1

    // ---- selection bounds for highlighting ----
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
                model: overlay.rows * overlay.cols
                Rectangle {
                    property int c: index % overlay.cols
                    property int r: Math.floor(index / overlay.cols)
                    property bool sel: overlay.selMinCol >= 0 &&
                                       c >= overlay.selMinCol && c <= overlay.selMaxCol &&
                                       r >= overlay.selMinRow && r <= overlay.selMaxRow
                    x: overlay.margin + c * (overlay.cellW + overlay.gap)
                    y: overlay.margin + r * (overlay.cellH + overlay.gap)
                    width: overlay.cellW
                    height: overlay.cellH
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

    // Hit test. Each cell owns its trailing gap, and the outer margins clamp to
    // the first/last cell — so there are no dead zones: dragging over a gap or
    // into the margin still selects the neighbouring cell rather than nothing.
    function cellAt(px, py) {
        var lx = px - workArea.x;
        var ly = py - workArea.y;
        if (lx < 0 || ly < 0 || lx >= workArea.width || ly >= workArea.height)
            return null;
        var col = Math.floor((lx - margin) / (cellW + gap));
        var row = Math.floor((ly - margin) / (cellH + gap));
        return { "col": Math.max(0, Math.min(col, cols - 1)),
                 "row": Math.max(0, Math.min(row, rows - 1)) };
    }

    function computeZone(c1, r1, c2, r2) {
        var minC = Math.min(c1, c2), maxC = Math.max(c1, c2);
        var minR = Math.min(r1, r2), maxR = Math.max(r1, r2);
        // A multi-cell zone absorbs the gaps between the cells it spans.
        return {
            "x": workArea.x + margin + minC * (cellW + gap),
            "y": workArea.y + margin + minR * (cellH + gap),
            "w": (maxC - minC + 1) * cellW + (maxC - minC) * gap,
            "h": (maxR - minR + 1) * cellH + (maxR - minR) * gap
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
        // Cells share out what's left after the outer margins and the inter-cell
        // gaps are taken off. Floor of 1px so a silly margin/gap can't produce a
        // zero or negative cell size.
        cellW = Math.max(1, Math.floor((workArea.width  - 2 * margin - (cols - 1) * gap) / cols));
        cellH = Math.max(1, Math.floor((workArea.height - 2 * margin - (rows - 1) * gap) / rows));

        startCol = -1; startRow = -1;
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
        console.warn("Gridlet: ▶ overlay shown  screen=" + g.width + "x" + g.height +
              "  work=" + workArea.width + "x" + workArea.height + "  cell=" + cellW + "x" + cellH +
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
        if (startCol < 0) { startCol = cell.col; startRow = cell.row; }
        selMinCol = Math.min(startCol, cell.col);
        selMaxCol = Math.max(startCol, cell.col);
        selMinRow = Math.min(startRow, cell.row);
        selMaxRow = Math.max(startRow, cell.row);
        pendingGeometry = computeZone(startCol, startRow, cell.col, cell.row);
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
        ", gap " + gap + ", margin " + margin + ") — root-Window, poll-based");
}
