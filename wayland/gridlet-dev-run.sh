#!/usr/bin/env bash
# Gridlet (Wayland) — dev runner.
#
# Loads the KWin overlay/snap script and starts the Ctrl+Meta keyboard helper,
# streaming live logs from BOTH so you can watch it work and see any errors.
# Press Ctrl+C to stop and clean everything up.
#
# Run from anywhere:   bash wayland/gridlet-dev-run.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
QML_SRC="$HERE/kwin-script/contents/ui/main.qml"
HELPER="$HERE/gridlet-hotkey-helper.py"
SCRIPT_ID="gridlet"
# Unique temp DIR each run — KWin caches compiled QML by path, and main.qml
# imports config.js from the same directory, so we stage both together.
QML_DIR="/tmp/gridlet-run-$$"
QML_RUN="$QML_DIR/main.qml"
JPID=""

cleanup() {
  echo
  echo "[gridlet] stopping…"
  "$HERE/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$SCRIPT_ID" >/dev/null 2>&1
  [ -n "$JPID" ] && kill "$JPID" 2>/dev/null
  rm -rf "$QML_DIR"
  echo "[gridlet] stopped and unloaded."
}
trap cleanup EXIT INT TERM

command -v qdbus6 >/dev/null 2>&1 || command -v gdbus >/dev/null 2>&1 \
  || { echo "neither qdbus6 nor gdbus found — is this a KDE session?"; exit 1; }

echo "[gridlet] loading KWin script…"
mkdir -p "$QML_DIR"
cp "$QML_SRC" "$QML_RUN"
python3 "$HERE/gen-config.py" "$QML_DIR/config.js" >/dev/null 2>&1
"$HERE/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$SCRIPT_ID" >/dev/null 2>&1
sleep 0.3
"$HERE/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.loadDeclarativeScript "$QML_RUN" "$SCRIPT_ID" >/dev/null
"$HERE/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.start
sleep 0.5
if [ "$("$HERE/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded "$SCRIPT_ID" 2>/dev/null)" = "true" ]; then
  echo "[gridlet] KWin script loaded ✓"
else
  echo "[gridlet] WARNING: KWin script failed to load (watch for errors below)"
fi

# Stream the KWin-side logs (engine loaded, overlay shown, snaps, errors).
( journalctl --user _COMM=kwin_wayland -f -n0 2>/dev/null \
    | grep --line-buffered -aiE "gridlet|qml:.*error" \
    | grep --line-buffered -aivE "onMove|connectWindow" \
    | sed -u 's/.*qml: /[kwin] /; s/^[^[].*/[kwin] &/' ) &
JPID=$!

echo "------------------------------------------------------------"
echo "  Gridlet is running."
echo "  1) Start dragging a window by its titlebar"
echo "  2) Hold Ctrl+Meta  → grid appears"
echo "  3) Move across cells → paint a zone"
echo "  4) Release the mouse → it snaps"
echo "  Press Ctrl+C here to stop."
echo "------------------------------------------------------------"

# Keyboard helper in the foreground — its lines start with 'gridlet-helper:'.
python3 "$HELPER" --debug
