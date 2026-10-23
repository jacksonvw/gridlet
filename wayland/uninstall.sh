#!/usr/bin/env bash
# Remove Gridlet (Wayland) — undoes install.sh.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
QDBUS="$HERE/gridlet-qdbus"   # from the repo, since we're deleting the installed copy

echo "→ Disabling + unloading the KWin script"
kwriteconfig6 --file kwinrc --group Plugins --key gridletEnabled false
"$QDBUS" org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript gridlet >/dev/null 2>&1 || true
"$QDBUS" org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true

echo "→ Stopping the helper + tray"
pkill -f "[g]ridlet-hotkey-helper" 2>/dev/null || true
pkill -f "[g]ridlet-tray"          2>/dev/null || true

echo "→ Unregistering global shortcuts"
for s in GridletActivate GridletDeactivate; do
    "$QDBUS" org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.unregister kwin "$s" >/dev/null 2>&1 || true
done

echo "→ Removing files"
rm -rf "$HOME/.local/share/kwin/scripts/gridlet"
rm -f  "$HOME/.config/autostart/gridlet-helper.desktop"
rm -f  "$HOME/.config/autostart/gridlet-tray.desktop"
rm -f  "$HOME/.local/share/applications/gridlet-editor.desktop"
rm -f  "$HOME/.local/share/applications/gridlet.desktop"
rm -rf "$HOME/.local/share/gridlet"
rm -f  "$HOME"/.local/share/icons/hicolor/*/apps/gridlet.png \
       "$HOME/.local/share/icons/hicolor/scalable/apps/gridlet.svg"
command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" || true

echo "✓ Gridlet removed. Log out/in once to fully clear it from KWin's memory."
