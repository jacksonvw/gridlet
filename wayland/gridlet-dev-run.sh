#!/usr/bin/env bash
# Gridlet (Wayland) — dev runner.
#
# Loads the KWin overlay/snap script and starts the Ctrl+Meta keyboard helper,
# streaming live logs from BOTH so you can watch it work and see any errors.
# While it runs it stands in for an installed Gridlet (both use the script id
# "gridlet"). Press Ctrl+C to stop, clean up and hand back to the installed one.
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
  # Loading this copy unloaded any installed Gridlet (same script id).
  # Reconfiguring makes KWin load enabled scripts again, which brings it back.
  "$HERE/gridlet-qdbus" org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1
  if [ "$(kreadconfig6 --file kwinrc --group Plugins --key gridletEnabled 2>/dev/null)" = "true" ]; then
    echo "[gridlet] stopped; the installed Gridlet is loaded again."
  else
    echo "[gridlet] stopped and unloaded."
  fi
}
trap cleanup EXIT
trap exit INT TERM      # Ctrl+C exits, and the EXIT trap cleans up once

command -v qdbus6 >/dev/null 2>&1 || command -v gdbus >/dev/null 2>&1 \
  || { echo "neither qdbus6 nor gdbus found — is this a KDE session?"; exit 1; }

# Stream the KWin-side logs (engine loaded, overlay shown, snaps, errors).
# Started before the script loads, so load-time errors show up too.
( journalctl --user _COMM=kwin_wayland -f -n0 2>/dev/null \
    | grep --line-buffered -aiE "gridlet|qml:.*error" \
    | grep --line-buffered -aivE "onMove|connectWindow" \
    | sed -u 's/.*qml: /[kwin] /; s/^[^[].*/[kwin] &/' ) &
JPID=$!
sleep 0.5

echo "[gridlet] loading KWin script…"
mkdir -p "$QML_DIR"
cp "$QML_SRC" "$QML_RUN"
python3 "$HERE/gen-config.py" "$QML_DIR/config.js" >/dev/null 2>&1
"$HERE/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$SCRIPT_ID" >/dev/null 2>&1
sleep 0.3
LOAD_T="$(date +%s.%3N)"
"$HERE/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.loadDeclarativeScript "$QML_RUN" "$SCRIPT_ID" >/dev/null
"$HERE/gridlet-qdbus" org.kde.KWin /Scripting org.kde.kwin.Scripting.start >/dev/null
# isScriptLoaded says "true" even when the QML failed to compile, so wait for
# the engine's own start-up line instead.
loaded=""
for _ in $(seq 10); do
  journalctl --user _COMM=kwin_wayland --since "@$LOAD_T" -o cat 2>/dev/null \
    | grep -q "Gridlet: engine loaded" && { loaded=1; break; }
  sleep 0.2
done
if [ -n "$loaded" ]; then
  echo "[gridlet] KWin script loaded ✓"
else
  echo "[gridlet] WARNING: KWin script failed to load (look for [kwin] errors)"
fi

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
