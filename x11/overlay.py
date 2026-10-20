#!/usr/bin/env python3
"""
Gridlet — Overlay and Snapping Engine

Full-screen click-through grid overlay for FancyZones-style window snapping
on KDE Plasma X11.

Interaction model:
  1. Click and hold on a window titlebar (start dragging normally)
  2. While dragging, press the hotkey (default: Ctrl+Meta) → grid appears
  3. Continue dragging — cells highlight to show selected zone
  4. Release mouse → window snaps to highlighted zone
  5. OR release hotkey first → cancel (no snap)

Can be run standalone for testing:
    python3 overlay.py
"""

import threading  # For stop_event (signalled by tray icon to shut down)
import Xlib.display
import Xlib.X
import Xlib.XK
import Xlib.ext.shape  # This extension lets us make the window click-through
import select  # For non-blocking event checking
import time  # For small delays between operations
import config as cfg  # Stage 7: config file support


# ============================================================================


def main(stop_event=None):
    """
    Main overlay event loop.

    Args:
        stop_event: a threading.Event. When set (e.g. by the tray icon's Quit
                    button), the event loop exits cleanly. If None, a local
                    Event is created so overlay.py still works standalone.
    """
    if stop_event is None:
        stop_event = threading.Event()

    # Load config here (inside main) so every thread start picks up
    # the latest config.json — this is what makes "Save & Apply" work
    # without restarting the whole application.
    _config = cfg.load_config()
    GRID_ROWS          = _config['grid']['rows']
    GRID_COLS          = _config['grid']['cols']
    GRID_GAP           = _config['grid']['gap']
    REQUIRED_MODIFIERS = _config['hotkey']

    # Connect to the X server (like connecting to the DOM in a browser)
    display = Xlib.display.Display()
    screen = display.screen()
    root = screen.root  # The root window is like the <html> element

    # Get total virtual screen dimensions (spans all monitors combined)
    width = screen.width_in_pixels
    height = screen.height_in_pixels

    # Detect individual monitors via XRandR
    # Think of this like detecting multiple browser windows on different screens
    monitors = []
    try:
        mon_data = root.xrandr_get_monitors(is_active=True)
        for mon in mon_data.monitors:
            monitors.append({
                'name': display.get_atom_name(mon.name),
                'x': mon.x,
                'y': mon.y,
                'width': mon.width_in_pixels,
                'height': mon.height_in_pixels,
                'primary': bool(mon.primary),
            })
    except Exception as e:
        # Fallback: treat entire screen as one monitor
        print(f"  ⚠ Could not detect monitors via XRandR: {e}")
        monitors.append({
            'name': 'default',
            'x': 0,
            'y': 0,
            'width': width,
            'height': height,
            'primary': True,
        })

    # Detect panels/docks by finding windows with _NET_WM_WINDOW_TYPE_DOCK
    # and subtracting their area from each monitor's usable space.
    #
    # Why not _NET_WORKAREA? It gives ONE rectangle for the entire virtual screen,
    # which can't represent a panel at the bottom of one monitor in a multi-monitor
    # setup (the panel is in the middle of the virtual screen, not at any edge).
    # Detecting actual panel windows works on any edge of any monitor.
    #
    # We use _NET_CLIENT_LIST (not root.query_tree()) because KWin reparents
    # dock windows, so they're not direct children of root.
    panels = []
    try:
        dock_type = display.intern_atom('_NET_WM_WINDOW_TYPE_DOCK')
        wm_type_atom = display.intern_atom('_NET_WM_WINDOW_TYPE')
        client_list_atom = display.intern_atom('_NET_CLIENT_LIST')

        client_list = root.get_full_property(client_list_atom, Xlib.X.AnyPropertyType)
        for wid in (client_list.value if client_list else []):
            try:
                win = display.create_resource_object('window', wid)
                type_prop = win.get_full_property(wm_type_atom, Xlib.X.AnyPropertyType)
                if type_prop and dock_type in type_prop.value:
                    geom = win.get_geometry()
                    # Walk up the parent chain to get absolute screen position
                    # (translate_coords gives wrong results for reparented windows)
                    abs_x, abs_y = 0, 0
                    current = win
                    while True:
                        parent = current.query_tree().parent
                        g = current.get_geometry()
                        abs_x += g.x
                        abs_y += g.y
                        if parent.id == root.id:
                            break
                        current = parent
                    panels.append({
                        'x': abs_x,
                        'y': abs_y,
                        'width': geom.width,
                        'height': geom.height,
                    })
            except Exception:
                continue
    except Exception:
        pass

    if panels:
        print(f"  Detected {len(panels)} panel(s):")
        for p in panels:
            print(f"    Panel at ({p['x']}, {p['y']}) size {p['width']}x{p['height']}")

    # For each monitor, subtract any overlapping panel from the usable work area.
    # The grid and snap geometry will use the work area, so windows never land behind panels.
    for mon in monitors:
        mon['work_x'] = mon['x']
        mon['work_y'] = mon['y']
        mon['work_width'] = mon['width']
        mon['work_height'] = mon['height']

        for panel in panels:
            px, py, pw, ph = panel['x'], panel['y'], panel['width'], panel['height']
            mx, my, mw, mh = mon['x'], mon['y'], mon['width'], mon['height']

            # Check if panel overlaps this monitor at all
            if px + pw <= mx or px >= mx + mw:
                continue  # No horizontal overlap
            if py + ph <= my or py >= my + mh:
                continue  # No vertical overlap

            # Panel overlaps — determine which edge it's on and shrink work area
            # Top panel: touching the top edge of the monitor
            if py <= my + 5:
                panel_bottom = py + ph
                inset = panel_bottom - mon['work_y']
                if inset > 0:
                    mon['work_y'] += inset
                    mon['work_height'] -= inset

            # Bottom panel: touching the bottom edge of the monitor
            elif py + ph >= my + mh - 5:
                panel_top = py
                work_bottom = mon['work_y'] + mon['work_height']
                if panel_top < work_bottom:
                    mon['work_height'] = panel_top - mon['work_y']

            # Left panel: touching the left edge of the monitor
            elif px <= mx + 5:
                panel_right = px + pw
                inset = panel_right - mon['work_x']
                if inset > 0:
                    mon['work_x'] += inset
                    mon['work_width'] -= inset

            # Right panel: touching the right edge of the monitor
            elif px + pw >= mx + mw - 5:
                panel_left = px
                work_right = mon['work_x'] + mon['work_width']
                if panel_left < work_right:
                    mon['work_width'] = panel_left - mon['work_x']

    print(f"Creating full-screen overlay: {width}x{height}")
    print(f"  Detected {len(monitors)} monitor(s):")
    for i, mon in enumerate(monitors):
        flag = " (primary)" if mon['primary'] else ""
        panel_note = ""
        if (mon['work_y'] != mon['y'] or mon['work_x'] != mon['x'] or
                mon['work_width'] != mon['width'] or mon['work_height'] != mon['height']):
            panel_note = f" (work area: {mon['work_width']}x{mon['work_height']} at {mon['work_x']},{mon['work_y']})"
        print(f"    [{i}] {mon['name']}: {mon['width']}x{mon['height']} at ({mon['x']}, {mon['y']}){flag}{panel_note}")

    # We need a visual that supports transparency (ARGB = Alpha + RGB)
    # This is like saying we want rgba() colors, not just rgb()
    # Default visual is 24-bit (RGB), we need 32-bit (ARGB) for transparency

    # Find a 32-bit visual (supports alpha channel for transparency)
    visual = None
    for depth in [32, 24]:  # Try 32-bit first, fall back to 24-bit
        try:
            visual = screen.root_visual
            if depth == 32:
                # This is a simplified approach - on most systems the default visual
                # at 32-bit depth supports ARGB
                visual_info = screen.root_visual
                break
        except:
            continue

    # Create the overlay window
    # In web terms: this is like createElement('div') and setting its style
    window = root.create_window(
        0, 0,           # x, y position (top-left corner = 0, 0)
        width, height,  # full screen dimensions
        0,              # border width (0 = no border)
        screen.root_depth,  # color depth (how many colors we can display)
        Xlib.X.InputOutput,  # window class (can receive input and display output)
        Xlib.X.CopyFromParent,  # visual (how colors are represented)

        # Window attributes (like CSS properties):
        background_pixel=0,  # Black background
        override_redirect=True,  # Bypass window manager (like a popup that ignores normal window rules)
        event_mask=Xlib.X.ExposureMask  # Only get notified when window needs redrawing
        # Note: We DON'T listen for keyboard events on this window because it won't have focus
        # Instead, we'll listen for keyboard on the root window (the desktop)
    )

    # Set window properties to make it behave like an overlay
    # These are X11 "atoms" (like CSS property names, but for X11 windows)

    # Tell the window manager this is a "dock" type window (always on top)
    # Similar to z-index in CSS
    window_type = display.intern_atom('_NET_WM_WINDOW_TYPE')
    window_type_dock = display.intern_atom('_NET_WM_WINDOW_TYPE_DOCK')
    window.change_property(
        window_type,
        Xlib.Xatom.ATOM,
        32,
        [window_type_dock]
    )

    # Make the window appear on all virtual desktops
    # Like making sure a modal overlay appears no matter which tab is active
    wm_state = display.intern_atom('_NET_WM_STATE')
    wm_state_above = display.intern_atom('_NET_WM_STATE_ABOVE')
    wm_state_sticky = display.intern_atom('_NET_WM_STATE_STICKY')
    window.change_property(
        wm_state,
        Xlib.Xatom.ATOM,
        32,
        [wm_state_above, wm_state_sticky]
    )

    # Set window opacity (transparency level)
    # 0xFFFFFFFF = fully opaque, 0x00000000 = fully transparent
    # We'll use about 30% opacity (0x4CCCCCCC) so you can see through it
    # In web terms: opacity: 0.3; or background: rgba(0, 0, 0, 0.3);
    opacity_atom = display.intern_atom('_NET_WM_WINDOW_OPACITY')
    opacity_value = int(0.3 * 0xFFFFFFFF)  # 30% opacity
    window.change_property(
        opacity_atom,
        Xlib.Xatom.CARDINAL,
        32,
        [opacity_value]
    )

    # Give the window a name (helpful for debugging)
    window.set_wm_name("Gridlet")
    window.set_wm_class("gridlet", "Gridlet")

    # Create a pixmap (off-screen drawable) to render our grid to
    # Think of this like an off-screen <canvas> in web dev
    pixmap = window.create_pixmap(width, height, screen.root_depth)

    # Create a graphics context for drawing on the pixmap
    gc = pixmap.create_gc()

    # Start with a black pixmap — the grid will be drawn fresh each session
    # when we know which monitor the cursor is on
    gc.change(foreground=screen.black_pixel)
    pixmap.fill_rectangle(gc, 0, 0, width, height)

    # Set this pixmap as the window's background
    window.change_attributes(background_pixmap=pixmap)
    window.clear_area(0, 0, width, height)

    # DON'T map the window yet - it starts hidden
    # We'll show it only when the user starts dragging AND presses Ctrl+Alt
    # The correct FancyZones flow is: drag first, then modifiers, not the other way around
    display.flush()  # Send all commands to the X server

    # Now make the window click-through using the Shape extension
    # This is like CSS pointer-events: none;
    # It means mouse clicks go through this window to whatever is behind it
    try:
        # Set the input shape to an empty rectangle (no input region)
        # Signature: rectangles(self, operation, destination_kind, ordering, x_offset, y_offset, rectangles)
        # SO.Set = shape operation "set" (replace existing shape)
        # SK.Input = shape kind "input" (affects mouse/keyboard input, not visual)
        # ordering = 0 (UnSorted, YXSorted, YXBanded, etc. - doesn't matter for empty list)
        # Empty list [] = no rectangles = no input region at all
        Xlib.ext.shape.rectangles(
            window,  # self: The window to modify
            Xlib.ext.shape.SO.Set,  # operation: Set (replace existing shape)
            Xlib.ext.shape.SK.Input,  # destination_kind: Input (not Bounding/visual)
            0,  # ordering: 0 = Unsorted (doesn't matter for empty list)
            0, 0,  # x_offset, y_offset
            []  # rectangles: Empty list = no input region at all
        )
        display.flush()
        print("✓ Click-through enabled (pointer-events: none)")
    except Exception as e:
        print(f"⚠ Could not enable click-through: {e}")
        print("  Window will still work, but clicks won't pass through")

    # No key grabs at all — modifier state is read by polling query_pointer().mask.
    # Grabbing any key system-wide disrupts other apps using that key, so we avoid
    # it entirely. Exit is handled by the tray icon (Quit) or Ctrl+C in terminal.
    grabbed_keycodes = []  # Nothing grabbed; kept for clean-up loop compatibility

    print("✓ Modifier detection: polling (zero system interference)")

    display.flush()

    # Track state (like boolean flags in JavaScript)
    # We track all modifiers, even ones not in REQUIRED_MODIFIERS
    modifiers_pressed = {
        'ctrl': False,
        'shift': False,
        'alt': False,
        'meta': False
    }
    mouse_button_pressed = False
    overlay_visible = False
    drag_window_id = None  # The window being dragged

    # Snap intent (set as soon as the overlay appears, updated continuously)
    # This is separate from the drag/overlay state to avoid timing race conditions.
    snap_session_active = False   # True while user could snap (overlay shown this drag)
    pending_snap_window_id = None # Which window to snap
    pending_snap_geometry = None  # What geometry to snap it to (updated every cell move)
    snap_grace_until = None       # If hotkey released, snap still fires until this time

    # Cell highlighting state (Stage 5)
    start_cell = None  # (col, row) where the overlay first appeared
    current_cell = None  # (col, row) where the cursor currently is
    last_highlighted_rect = None  # Last highlighted rectangle to avoid unnecessary redraws

    # Multi-monitor state (Stage 8a)
    # These are set fresh each time the overlay appears, based on cursor position
    active_monitor = None  # Which monitor dict the grid is on this session
    cell_width = 0         # Computed from active_monitor['work_width'] // GRID_COLS
    cell_height = 0        # Computed from active_monitor['work_height'] // GRID_ROWS

    # Helper function to find which monitor contains a screen coordinate
    def get_monitor_at(x, y):
        """
        Given absolute screen coordinates, return the monitor dict that contains
        that point. Returns None if the point is in dead space between monitors.

        Think of it like document.elementFromPoint() but for physical screens.
        """
        for mon in monitors:
            if (mon['x'] <= x < mon['x'] + mon['width'] and
                    mon['y'] <= y < mon['y'] + mon['height']):
                return mon
        return None

    # Helper function to check if required modifiers are pressed
    def check_required_modifiers():
        # Check that all REQUIRED modifiers are pressed
        # We allow extra modifiers (e.g., if user accidentally holds Shift too)
        # This makes the trigger more forgiving and easier to use
        for key, required in REQUIRED_MODIFIERS.items():
            if required and not modifiers_pressed[key]:
                return False  # Required modifier is missing
        return True  # All required modifiers are present (extras are OK)

    # Helper function to check if user is currently dragging a window
    def check_pointer_state():
        nonlocal mouse_button_pressed, drag_window_id
        nonlocal snap_session_active, pending_snap_window_id, pending_snap_geometry, snap_grace_until
        nonlocal start_cell, current_cell, last_highlighted_rect
        try:
            pointer_data = root.query_pointer()
            button1_pressed = bool(pointer_data.mask & Xlib.X.Button1Mask)

            if button1_pressed and not mouse_button_pressed:
                # Drag just started — record which window is being dragged
                mouse_button_pressed = True
                try:
                    active_window_atom = display.intern_atom('_NET_ACTIVE_WINDOW')
                    prop = root.get_full_property(active_window_atom, Xlib.X.AnyPropertyType)
                    if prop and prop.value:
                        drag_window_id = prop.value[0]
                        print(f"  Drag detected (window {drag_window_id})")
                    else:
                        print("  Drag detected (no active window)")
                except Exception as e:
                    print(f"  Drag detected (could not get active window: {e})")

            elif not button1_pressed and mouse_button_pressed:
                # Mouse released — fire snap if session active (or within grace period)
                mouse_button_pressed = False
                print("  Mouse released")

                # Determine if we should snap
                within_grace = snap_grace_until is not None and time.time() < snap_grace_until
                should_snap = snap_session_active or within_grace

                if should_snap and pending_snap_window_id:
                    # If geometry wasn't set yet (released very fast), compute it from
                    # start_cell on the spot as a fallback
                    geometry = pending_snap_geometry
                    if geometry is None and start_cell:
                        geometry = calculate_zone_geometry(start_cell, start_cell)

                    if geometry:
                        print(f"  → Snapping window {pending_snap_window_id} to {geometry}")
                        snap_window_to_zone(pending_snap_window_id, geometry)
                    else:
                        print(f"  → No zone selected, skipping snap")

                # Reset all drag/snap state
                snap_session_active = False
                snap_grace_until = None
                pending_snap_window_id = None
                pending_snap_geometry = None
                drag_window_id = None
                start_cell = None
                current_cell = None
                last_highlighted_rect = None

        except Exception as e:
            print(f"  ⚠ Could not query pointer state: {e}")

    # Helper function to calculate zone geometry from cell coordinates
    def calculate_zone_geometry(from_cell, to_cell):
        """
        Calculate the screen geometry (x, y, width, height) for a zone
        spanning from from_cell to to_cell.

        Returns (x, y, width, height) in pixels.
        """
        if not from_cell or not to_cell:
            return None

        col1, row1 = from_cell
        col2, row2 = to_cell

        # Get min/max to handle dragging in any direction
        min_col = min(col1, col2)
        max_col = max(col1, col2)
        min_row = min(row1, row2)
        max_row = max(row1, row2)

        # Calculate geometry in absolute screen pixels, inset by gap on all sides
        # The monitor offset converts cell-local coords to absolute screen coords
        # so the window lands exactly where the visual highlight shows
        mon_x = active_monitor['work_x'] if active_monitor else 0
        mon_y = active_monitor['work_y'] if active_monitor else 0

        x = mon_x + min_col * cell_width + GRID_GAP
        y = mon_y + min_row * cell_height + GRID_GAP
        w = (max_col - min_col + 1) * cell_width - 2 * GRID_GAP
        h = (max_row - min_row + 1) * cell_height - 2 * GRID_GAP

        return (x, y, w, h)

    # Helper function to snap a window to a zone
    def snap_window_to_zone(window_id, zone_geometry):
        """
        Move and resize a window to fit the specified zone geometry.
        Uses EWMH for KWin compatibility, with fallback to direct X11 calls.

        Args:
            window_id: X11 window ID
            zone_geometry: (x, y, width, height) tuple in pixels
        """
        if not zone_geometry:
            print("  ⚠ Cannot snap: invalid zone geometry")
            return

        x, y, w, h = zone_geometry

        try:
            # Get the window object from ID
            win = display.create_resource_object('window', window_id)

            # First, remove maximized state (KWin won't resize maximized windows)
            state_atom = display.intern_atom('_NET_WM_STATE')
            max_horz_atom = display.intern_atom('_NET_WM_STATE_MAXIMIZED_HORZ')
            max_vert_atom = display.intern_atom('_NET_WM_STATE_MAXIMIZED_VERT')

            # Send client message to remove maximized state
            # This is like telling KWin "unmaximize this window"
            data = [
                0,  # _NET_WM_STATE_REMOVE (0 = remove, 1 = add, 2 = toggle)
                max_horz_atom,
                max_vert_atom,
                1,  # source indication: 1 = application
                0
            ]

            event = Xlib.protocol.event.ClientMessage(
                window=win,
                client_type=state_atom,
                data=(32, data)
            )

            root.send_event(event, event_mask=Xlib.X.SubstructureRedirectMask | Xlib.X.SubstructureNotifyMask)
            display.flush()

            # Account for window frame decorations (title bar + borders).
            #
            # There are two distinct cases:
            #
            # 1. Server-side decorations (SSD) — KWin draws the titlebar/borders
            #    OUTSIDE the X window. _NET_FRAME_EXTENTS = [left, right, top, bottom]
            #    of those external decorations. We shrink the client rect so the
            #    full decorated frame fits the zone:
            #      client_x = x + frame_left,  client_w = w - frame_left - frame_right
            #
            # 2. Client-side decorations (CSD) — the app draws its own titlebar/shadow
            #    INSIDE the X window (GTK apps: Firefox, Thunderbird, Librewolf, etc.).
            #    _NET_FRAME_EXTENTS reflects the internal shadow (~40–50px each side),
            #    NOT external KWin decorations. If we adjusted by those values the
            #    window would end up ~50px inset on every side — exactly the bug.
            #    Detection: GTK CSD apps set _GTK_FRAME_EXTENTS; if present, skip
            #    the frame adjustment and let the zone geometry stand as-is.

            # Step 1: check for GTK CSD
            # GTK apps (Firefox, Thunderbird, etc.) render a drop-shadow INSIDE
            # the X window. The shadow thickness is declared in _GTK_FRAME_EXTENTS.
            # To make the visible content fill the zone we must EXPAND the X window
            # target by those shadow amounts (so shadow bleeds outside/behind the zone
            # boundary and the content is flush with it).
            is_gtk_csd = False
            gtk_l = gtk_r = gtk_t = gtk_b = 0
            try:
                gtk_frame_atom = display.intern_atom('_GTK_FRAME_EXTENTS')
                gtk_prop = win.get_full_property(gtk_frame_atom, Xlib.X.AnyPropertyType)
                if gtk_prop and gtk_prop.value and len(gtk_prop.value) >= 4:
                    is_gtk_csd = True
                    gtk_l, gtk_r, gtk_t, gtk_b = gtk_prop.value[:4]
                    print(f"  GTK CSD: shadow=[L{gtk_l} R{gtk_r} T{gtk_t} B{gtk_b}]")
                elif gtk_prop and gtk_prop.value:
                    is_gtk_csd = True
                    print(f"  GTK CSD window (shadow extents unavailable)")
            except Exception:
                pass

            # Step 2: compute client coords from zone geometry + frame info
            if is_gtk_csd:
                client_x = x - gtk_l
                client_y = y - gtk_t
                client_w = w + gtk_l + gtk_r
                client_h = h + gtk_t + gtk_b
            else:
                frame_left = frame_right = frame_top = frame_bottom = 0
                try:
                    frame_atom = display.intern_atom('_NET_FRAME_EXTENTS')
                    prop = win.get_full_property(frame_atom, Xlib.X.AnyPropertyType)
                    if prop and prop.value and len(prop.value) >= 4:
                        frame_left, frame_right, frame_top, frame_bottom = prop.value[:4]
                        if any([frame_left, frame_right, frame_top, frame_bottom]):
                            print(f"  Frame extents: L={frame_left} R={frame_right} T={frame_top} B={frame_bottom}")
                except Exception:
                    pass
                client_x = x + frame_left
                client_y = y + frame_top
                client_w = w - frame_left - frame_right
                client_h = h - frame_top - frame_bottom

            # Now move and resize the window using EWMH
            # _NET_MOVERESIZE_WINDOW is the KWin-friendly way
            moveresize_atom = display.intern_atom('_NET_MOVERESIZE_WINDOW')

            # Flags format (from EWMH spec):
            # Bits 0-4: Which values are set (x, y, width, height, gravity)
            # Bits 8-11: Gravity
            # Bits 12-15: Source indication
            #
            # We're setting: x (bit 0), y (bit 1), width (bit 2), height (bit 3)
            # Gravity: StaticGravity = 10 (0b1010) at bits 8-11
            # Source: Application = 1 (0b0001) at bits 12-15

            # _NET_MOVERESIZE_WINDOW flags layout (from EWMH spec + wmctrl):
            #   bits 0–7:  gravity (ICCCM value: StaticGravity = 10)
            #   bit  8:    x is provided
            #   bit  9:    y is provided
            #   bit  10:   width is provided
            #   bit  11:   height is provided
            #   bit  12:   source (1 = application, 2 = pager)
            flags = (
                10        |   # StaticGravity = 10 (ICCCM) in bits 0–7
                (1 << 8)  |   # x is set
                (1 << 9)  |   # y is set
                (1 << 10) |   # width is set
                (1 << 11) |   # height is set
                (1 << 12)     # source = application
            )

            # python-xlib encodes position values as unsigned integers, but the
            # X11 protocol defines them as signed (INT32 in ClientMessage, INT16
            # in ConfigureWindow). For CSD windows near the screen edge, shadow
            # expansion can produce negative coords (e.g. x=2 - shadow=45 → -43).
            # Fix: pass the two's-complement unsigned equivalent. X11 and KWin read
            # the same bits and interpret them as negative — the correct result.
            def u32(v): return v & 0xFFFFFFFF if v < 0 else v  # for 32-bit EWMH
            def u16(v): return v & 0xFFFF     if v < 0 else v  # for 16-bit configure

            # Data format: [flags, x, y, width, height] — using client area coords
            data = [flags, u32(client_x), u32(client_y), client_w, client_h]

            event = Xlib.protocol.event.ClientMessage(
                window=win,
                client_type=moveresize_atom,
                data=(32, data)
            )

            root.send_event(event, event_mask=Xlib.X.SubstructureRedirectMask | Xlib.X.SubstructureNotifyMask)
            display.flush()

            # For SSD windows only: also send a direct ConfigureRequest as a backup.
            # EWMH alone was unreliable for SSD on this KWin setup (discovered earlier).
            #
            # For CSD windows we skip configure() entirely. configure() uses
            # parent-relative (frame-relative) coords, which conflict with EWMH's
            # StaticGravity root-relative coords and produce wrong x positions.
            # EWMH alone correctly handles both positive and negative values for CSD.
            if not is_gtk_csd:
                try:
                    win.configure(x=u16(client_x), y=u16(client_y),
                                   width=client_w, height=client_h)
                    display.flush()
                except Exception:
                    pass

            print(f"  ✓ Snapped window to zone: x={x}, y={y}, w={w}, h={h} (frame-adjusted)")

        except Exception as e:
            print(f"  ⚠ Could not snap window: {e}")
            print(f"  Attempted geometry: x={x}, y={y}, w={w}, h={h}")

    # Helper function to get which cell the cursor is over
    def get_cell_at_position(x, y):
        """
        Calculate which cell (col, row) contains the given screen coordinates.
        Converts absolute screen coords to monitor-local coords first.
        Returns (col, row) tuple, or None if outside the active monitor.
        """
        if not active_monitor or cell_width == 0 or cell_height == 0:
            return None

        # Convert absolute screen coords to work-area-local
        local_x = x - active_monitor['work_x']
        local_y = y - active_monitor['work_y']

        # Bounds check against the active monitor's work area
        if (local_x < 0 or local_y < 0 or
                local_x >= active_monitor['work_width'] or
                local_y >= active_monitor['work_height']):
            return None

        col = min(local_x // cell_width, GRID_COLS - 1)
        row = min(local_y // cell_height, GRID_ROWS - 1)
        return (col, row)

    # Helper function to read current modifier key state from X11
    def poll_modifier_state():
        """
        Read which modifier keys are currently held by checking query_pointer().mask.

        This is the X11 bitmask of currently-active modifiers and mouse buttons.
        Reading it is a simple query — no grab, no event interception, no side effects.

        Standard X11 modifier bits:
          ShiftMask   = 0x01  (Shift)
          ControlMask = 0x04  (Ctrl)
          Mod1Mask    = 0x08  (Alt / Option)
          Mod4Mask    = 0x40  (Super / Meta / Win key)

        Returns True if any modifier state changed (caller should then re-check
        whether the overlay should appear or disappear).
        """
        nonlocal modifiers_pressed
        try:
            mask = root.query_pointer().mask
            new_state = {
                'ctrl':  bool(mask & Xlib.X.ControlMask),
                'shift': bool(mask & Xlib.X.ShiftMask),
                'alt':   bool(mask & Xlib.X.Mod1Mask),
                'meta':  bool(mask & Xlib.X.Mod4Mask),
            }
            if new_state == modifiers_pressed:
                return False
            for key in new_state:
                if new_state[key] != modifiers_pressed[key]:
                    print(f"  {key.capitalize()} {'pressed' if new_state[key] else 'released'}")
            modifiers_pressed.update(new_state)
            return True
        except Exception:
            return False

    # Helper function to redraw the overlay with highlighted cells
    def redraw_overlay_with_highlight(from_cell, to_cell):
        """
        Redraw the grid with cells highlighted from from_cell to to_cell.
        All drawing is scoped to the active monitor's area only.

        Each zone is rendered as an inset rectangle — inset by GRID_GAP from
        the cell boundary on all four sides. This makes the gaps between zones
        visually explicit: the "gap" is simply empty space between adjacent
        rectangles. Highlighted zones are filled; others show just an outline.

        This creates a rectangle selection effect like painting in FancyZones.
        """
        if not active_monitor:
            return

        mon_x = active_monitor['work_x']
        mon_y = active_monitor['work_y']

        # Clear the entire pixmap (areas outside active monitor stay black,
        # which shows through the translucent overlay as "no grid here")
        gc.change(foreground=screen.black_pixel)
        pixmap.fill_rectangle(gc, 0, 0, width, height)

        # Determine the highlighted range (or -1 sentinel when nothing is selected)
        if from_cell and to_cell:
            col1, row1 = from_cell
            col2, row2 = to_cell
            min_col = min(col1, col2)
            max_col = max(col1, col2)
            min_row = min(row1, row2)
            max_row = max(row1, row2)
        else:
            min_col = max_col = min_row = max_row = -1

        # Draw every zone as a GRID_GAP-inset rectangle within its cell.
        # The gap creates visible empty space between adjacent zones and from
        # the monitor edges — the grid lines effectively disappear and you see
        # discrete, separated zone boxes instead.
        #
        # Highlighted zones: filled (solid white block)
        # Non-highlighted zones: outline only (faint border, no fill)
        #
        # We collect all rects first then draw in two batched calls:
        # poly_fill_rectangle fills, poly_rectangle outlines.
        fill_rects = []
        outline_rects = []
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                rect = {
                    'x': mon_x + col * cell_width + GRID_GAP,
                    'y': mon_y + row * cell_height + GRID_GAP,
                    'width': cell_width - 2 * GRID_GAP,
                    'height': cell_height - 2 * GRID_GAP,
                }
                if min_col <= col <= max_col and min_row <= row <= max_row:
                    fill_rects.append(rect)
                else:
                    outline_rects.append(rect)

        gc.change(foreground=screen.white_pixel)
        if fill_rects:
            pixmap.poly_fill_rectangle(gc, fill_rects)
        if outline_rects:
            pixmap.poly_rectangle(gc, outline_rects)

        # Update the window
        window.clear_area(0, 0, width, height)
        display.flush()

    # Helper function to poll pointer position and update cell highlighting
    def update_cell_highlighting():
        nonlocal start_cell, current_cell, last_highlighted_rect, pending_snap_geometry

        try:
            pointer_data = root.query_pointer()
            mouse_x = pointer_data.root_x
            mouse_y = pointer_data.root_y

            cell = get_cell_at_position(mouse_x, mouse_y)

            if cell:
                current_cell = cell

                if start_cell is None:
                    start_cell = cell
                    print(f"  Selection started at cell {start_cell}")

                # Redraw if the selection rectangle changed
                new_rect = (start_cell, current_cell)
                if new_rect != last_highlighted_rect:
                    redraw_overlay_with_highlight(start_cell, current_cell)
                    last_highlighted_rect = new_rect

                # Continuously update the pending snap geometry so it's always
                # ready to fire when the mouse is released, no matter the timing
                pending_snap_geometry = calculate_zone_geometry(start_cell, current_cell)

        except Exception as e:
            print(f"  ⚠ Could not update cell highlighting: {e}")

    # Helper function to show/hide overlay based on state
    def update_overlay_visibility():
        nonlocal overlay_visible, start_cell, current_cell, last_highlighted_rect
        nonlocal snap_session_active, pending_snap_window_id, pending_snap_geometry
        nonlocal snap_grace_until, drag_window_id
        nonlocal active_monitor, cell_width, cell_height
        mods_ok = check_required_modifiers()
        should_be_visible = mods_ok and mouse_button_pressed

        if should_be_visible and not overlay_visible:
            # Determine which monitor the cursor is on — this locks the grid
            # to one monitor for the entire drag session
            pointer_data = root.query_pointer()
            active_monitor = get_monitor_at(pointer_data.root_x, pointer_data.root_y)

            if not active_monitor:
                # Cursor is in dead space between monitors — don't show overlay
                return

            # Calculate cell dimensions from the usable work area (excludes panels)
            cell_width = active_monitor['work_width'] // GRID_COLS
            cell_height = active_monitor['work_height'] // GRID_ROWS

            # Show overlay
            window.map()
            display.flush()
            overlay_visible = True

            # Reset cell highlighting for this session
            start_cell = None
            current_cell = None
            last_highlighted_rect = None
            pending_snap_geometry = None
            snap_grace_until = None  # No grace period while overlay is visible

            # Start the snap session — save the window now so it's ready for snap
            snap_session_active = True
            pending_snap_window_id = drag_window_id

            active_mods = [k.capitalize() for k, v in modifiers_pressed.items() if v]
            mod_string = '+'.join(active_mods) if active_mods else "None"
            print(f"▶ OVERLAY SHOWN on {active_monitor['name']} (Dragging with {mod_string})")

            # Draw the grid for this monitor and immediately update highlighting
            redraw_overlay_with_highlight(None, None)
            update_cell_highlighting()

        elif not should_be_visible and overlay_visible:
            # Hide overlay
            window.unmap()
            display.flush()
            overlay_visible = False
            print("◼ Overlay hidden")

            # If modifier was released while mouse still held, enter grace period
            # instead of cancelling immediately — mouse release within 330ms still snaps
            if mouse_button_pressed and not mods_ok:
                snap_grace_until = time.time() + 0.33
                snap_session_active = False  # Session "ended" but grace period is active
                print("  → Hotkey released (330ms grace period for mouse release)")

    # Build a readable hotkey string for the welcome message
    active_mods = [k.capitalize() for k, v in REQUIRED_MODIFIERS.items() if v]
    hotkey_string = '+'.join(active_mods)

    print("\n╔═══════════════════════════════════════════════════════════╗")
    print("║  Gridlet — FancyZones-style snapping for KDE Plasma X11  ║")
    print("╚═══════════════════════════════════════════════════════════╝\n")
    print(f"  Config:    {cfg.CONFIG_FILE}")
    print(f"  Grid:      {GRID_COLS} cols × {GRID_ROWS} rows, {GRID_GAP}px gap")
    print(f"  Monitors:  {len(monitors)}")
    print("How to use:\n")
    print("  1. Start dragging a window (click and hold titlebar)")
    print(f"  2. While dragging, press {hotkey_string} → grid appears!")
    print("  3. Continue dragging → cells highlight to show selected zone 🎨")
    print("  4. Release mouse → window snaps to zone! ✨")
    print(f"  5. Release {hotkey_string} first → cancel (no snap)\n")
    print("Ready.\n")
    print("Press Escape to exit.\n")
    print(f"Configured modifiers: {REQUIRED_MODIFIERS}")
    print("Listening for events...")

    # Event loop
    #
    # Two modes depending on whether the overlay is currently visible:
    #
    # OVERLAY HIDDEN — poll every 50ms:
    #   Read modifier + pointer state. If the hotkey is now held while dragging,
    #   show the overlay. 50ms feels instant to humans and uses negligible CPU.
    #
    # OVERLAY VISIBLE — poll every 16ms (≈60fps):
    #   Keep cell highlighting smooth. Read pointer for button-release detection.
    #
    # In both modes, any X events that arrive (only Escape is grabbed) are
    # processed immediately via select + next_event().
    try:
        while not stop_event.is_set():
            event = None

            if overlay_visible:
                readable, _, _ = select.select([display.fileno()], [], [], 0.016)
                if readable:
                    event = display.next_event()

                poll_modifier_state()       # Read current modifier keys
                check_pointer_state()       # Detect mouse button release → snap
                update_overlay_visibility() # Hide overlay if modifiers/button released
                update_cell_highlighting()  # Redraw highlighted cells

                if not event:
                    continue
            else:
                readable, _, _ = select.select([display.fileno()], [], [], 0.05)
                if not readable:
                    # No X event — poll state and show overlay if hotkey+drag active
                    if poll_modifier_state():
                        check_pointer_state()
                        update_overlay_visibility()
                    continue
                event = display.next_event()
                poll_modifier_state()  # Sync modifier state on any event

    except KeyboardInterrupt:
        print("\n✓ Ctrl+C — exiting")

    # Clean up (like removeEventListener and removing the element from DOM)
    # Release each key grab
    for keycode in grabbed_keycodes:
        root.ungrab_key(keycode, Xlib.X.AnyModifier)

    # Stop listening to root window events
    root.change_attributes(event_mask=Xlib.X.NoEventMask)

    # Clean up resources
    gc.free()  # Free graphics context
    pixmap.free()  # Free pixmap

    # Destroy our overlay window
    window.destroy()
    display.flush()
    print("✓ Gridlet closed cleanly")

if __name__ == "__main__":
    main()
