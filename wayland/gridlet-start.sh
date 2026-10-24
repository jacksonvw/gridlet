#!/usr/bin/env bash
# Start / re-open Gridlet (Wayland). Idempotent — safe to run anytime, e.g. from
# the "Gridlet" app-menu entry after you've Quit it from the tray.
LIB="$HOME/.local/share/gridlet"

# Enable + load the KWin overlay script if it isn't loaded (gridlet-apply.sh
# loads it from a fresh path and also (re)starts the helper).
kwriteconfig6 --file kwinrc --group Plugins --key gridletEnabled true 2>/dev/null
if [ "$("$LIB/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded gridlet 2>/dev/null)" != "true" ]; then
    bash "$LIB/gridlet-apply.sh" >/dev/null 2>&1
fi

# Make sure the helper + tray are running (don't double-start).
pgrep -f '^[^ ]*python3 [^ ]*gridlet-hotkey-helper[.]py' >/dev/null 2>&1 || setsid python3 "$LIB/gridlet-hotkey-helper.py" >/dev/null 2>&1 </dev/null &
pgrep -f '^[^ ]*python3 [^ ]*gridlet-tray[.]py'          >/dev/null 2>&1 || setsid python3 "$LIB/gridlet-tray.py"          >/dev/null 2>&1 </dev/null &

echo "Gridlet started."
