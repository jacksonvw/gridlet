#!/usr/bin/env bash
# Gridlet (Wayland / SteamOS) installer.
#
# Installs:
#   • KWin overlay+snap script     → ~/.local/share/kwin/scripts/gridlet  (auto-loads with KWin)
#   • helper, tray, editor tooling → ~/.local/share/gridlet
#   • autostart entries (helper + tray)   → ~/.config/autostart
#   • app-menu entries (Gridlet + Editor) → ~/.local/share/applications
#
# Enables and starts everything now, so you don't have to reboot to try it.
# Re-run any time to update. Run uninstall.sh to remove it all cleanly.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

KWIN_DST="$HOME/.local/share/kwin/scripts/gridlet"
LIB_DST="$HOME/.local/share/gridlet"
AUTOSTART="$HOME/.config/autostart"

echo "→ Installing KWin script to $KWIN_DST"
mkdir -p "$KWIN_DST/contents/ui"
cp "$HERE/kwin-script/metadata.json"            "$KWIN_DST/metadata.json"
cp "$HERE/kwin-script/contents/ui/main.qml"     "$KWIN_DST/contents/ui/main.qml"
# Translate ~/.config/gridlet/config.json → config.js (the QML can't read JSON).
python3 "$HERE/gen-config.py" "$KWIN_DST/contents/ui/config.js"

echo "→ Installing keyboard helper + editor tooling to $LIB_DST"
mkdir -p "$LIB_DST"
cp "$HERE/gridlet-hotkey-helper.py" "$LIB_DST/gridlet-hotkey-helper.py"
cp "$HERE/gridlet-qdbus"            "$LIB_DST/gridlet-qdbus"
cp "$HERE/gen-config.py"            "$LIB_DST/gen-config.py"
cp "$HERE/gridlet-apply.sh"         "$LIB_DST/gridlet-apply.sh"
cp "$HERE/gridlet-edit.sh"          "$LIB_DST/gridlet-edit.sh"
cp "$HERE/gridlet-start.sh"         "$LIB_DST/gridlet-start.sh"
cp "$HERE/gridlet-tray.py"          "$LIB_DST/gridlet-tray.py"
cp "$HERE/editor.py"                "$LIB_DST/editor.py"
cp "$HERE/config.py"                "$LIB_DST/config.py"
chmod +x "$LIB_DST/gridlet-hotkey-helper.py" "$LIB_DST/gridlet-apply.sh" \
         "$LIB_DST/gridlet-edit.sh" "$LIB_DST/gridlet-start.sh" \
         "$LIB_DST/gridlet-qdbus"

echo "→ Enabling the KWin script"
kwriteconfig6 --file kwinrc --group Plugins --key gridletEnabled true
"$HERE/gridlet-qdbus" org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true

echo "→ Installing autostart entries (helper + tray)"
mkdir -p "$AUTOSTART"
cat > "$AUTOSTART/gridlet-helper.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Gridlet Hotkey Helper
Comment=Watches Ctrl+Meta so the Gridlet KWin script can raise the grid
Exec=python3 $LIB_DST/gridlet-hotkey-helper.py
Terminal=false
NoDisplay=true
X-KDE-autostart-phase=2
EOF
cat > "$AUTOSTART/gridlet-tray.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Gridlet Tray
Comment=Gridlet system-tray control (enable / disable / quit)
Exec=python3 $LIB_DST/gridlet-tray.py
Terminal=false
NoDisplay=true
X-KDE-autostart-phase=2
EOF

echo "→ Adding Gridlet + Grid Editor to the app menu"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
cat > "$APPS/gridlet.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Gridlet
GenericName=Window Snapping
Comment=FancyZones-style window snapping — hold Ctrl+Meta while dragging
Exec=$LIB_DST/gridlet-start.sh
Icon=preferences-system-windows
Terminal=false
Categories=Utility;
Keywords=snap;tile;zones;window;grid;fancyzones;
EOF
cat > "$APPS/gridlet-editor.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Gridlet Grid Editor
Comment=Edit the Gridlet snapping grid (rows, columns, gap)
Exec=$LIB_DST/gridlet-edit.sh
Icon=preferences-system-windows
Terminal=false
Categories=Utility;Settings;
EOF

echo "→ Starting the helper + tray now"
pkill -f "[g]ridlet-hotkey-helper" 2>/dev/null || true
pkill -f "[g]ridlet-tray"          2>/dev/null || true
sleep 0.3
setsid python3 "$LIB_DST/gridlet-hotkey-helper.py" >/dev/null 2>&1 </dev/null &
setsid python3 "$LIB_DST/gridlet-tray.py"          >/dev/null 2>&1 </dev/null &

echo
echo "✓ Gridlet installed and running. Hold Ctrl+Meta while dragging a window."
echo "  It will start automatically on every login."
