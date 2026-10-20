#!/usr/bin/env bash
# Apply ~/.config/gridlet/config.json changes live (called by the Grid Editor's
# "Save & Apply"):
#   1. regenerate config.js (grid size)
#   2. reload the KWin script from a fresh path (KWin caches compiled QML by path,
#      so an in-place reload would keep the old grid)
#   3. restart the helper (so a changed hotkey takes effect)
set -u
LIB="$HOME/.local/share/gridlet"
KWIN_DST="$HOME/.local/share/kwin/scripts/gridlet"

# 1. Regenerate the installed config.js (this is what loads on next login too).
python3 "$LIB/gen-config.py" "$KWIN_DST/contents/ui/config.js" >/dev/null 2>&1 || true

# 2. Live reload via a unique /tmp dir to defeat KWin's in-session QML cache.
D="$(mktemp -d /tmp/gridlet-apply.XXXXXX)"
cp "$KWIN_DST/contents/ui/main.qml"  "$D/main.qml"
cp "$KWIN_DST/contents/ui/config.js" "$D/config.js"
"$LIB/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript gridlet >/dev/null 2>&1
sleep 0.3
"$LIB/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.loadDeclarativeScript "$D/main.qml" gridlet >/dev/null 2>&1
"$LIB/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.start >/dev/null 2>&1

# 3. Restart the helper (safe pkill: this script's process cmdline is just its
#    own path, so it never matches the helper pattern).
pkill -f 'gridlet-hotkey-helper[.]py' 2>/dev/null || true
sleep 0.3
setsid python3 "$LIB/gridlet-hotkey-helper.py" >/dev/null 2>&1 </dev/null &

echo "Gridlet: applied."
