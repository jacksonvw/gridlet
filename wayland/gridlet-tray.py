#!/usr/bin/env python3
"""
Gridlet — system tray control (StatusNotifierItem)

A small KDE-native tray icon so Gridlet can be enabled/disabled/quit by hand —
importantly, a kill-switch that stays reachable even if the overlay ever
misbehaves (the panel sits above everything).

Implemented as a StatusNotifierItem + DBusMenu over D-Bus using dbus-python,
because that's the only tray mechanism KDE Plasma on Wayland honours (Gtk
StatusIcon/XEmbed is dead on Wayland, and pystray/AppIndicator aren't installed).
No third-party dependencies.

Menu:
  • Snapping enabled   (checkbox — the on/off kill-switch)
  • Grid Editor…       (launch the editor)
  • Quit Gridlet       (disable everything + quit the tray)

"Enable"  = load the KWin script (via gridlet-apply.sh) + start the helper.
"Disable" = unload the KWin script + stop the helper.
"""

import os
import subprocess
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

LIB = os.path.expanduser("~/.local/share/gridlet")
# qdbus6 exists on SteamOS but not on Fedora; the shim falls back to gdbus.
QDBUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gridlet-qdbus")
SNI_IFACE = "org.kde.StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

ICON_ON = "gridlet"                  # Gridlet's own icon, installed into the theme
ICON_OFF = "window-close-symbolic"   # a stock Plasma icon


# ---------------------------------------------------------------------------
#  Talking to KWin / the helper
# ---------------------------------------------------------------------------
def _kwin(method, *args):
    subprocess.run([QDBUS, "org.kde.KWin", "/Scripting",
                    "org.kde.kwin.Scripting." + method, *args],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def is_script_loaded():
    try:
        out = subprocess.run(
            [QDBUS, "org.kde.KWin", "/Scripting",
             "org.kde.kwin.Scripting.isScriptLoaded", "gridlet"],
            capture_output=True, text=True, timeout=4).stdout.strip()
        return out == "true"
    except Exception:
        return False


# Matches the helper process only (python3 running the script), not an
# editor or a shell that happens to mention the file.
HELPER_PATTERN = r"^[^ ]*python3 [^ ]*gridlet-hotkey-helper[.]py"


def do_enable():
    subprocess.run(["kwriteconfig6", "--file", "kwinrc", "--group", "Plugins",
                    "--key", "gridletEnabled", "true"])
    # gridlet-apply.sh (re)loads the script from a fresh path and (re)starts the helper.
    subprocess.run(["bash", os.path.join(LIB, "gridlet-apply.sh")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def do_disable():
    _kwin("unloadScript", "gridlet")
    subprocess.run(["kwriteconfig6", "--file", "kwinrc", "--group", "Plugins",
                    "--key", "gridletEnabled", "false"])
    subprocess.run(["pkill", "-f", HELPER_PATTERN],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch_editor():
    subprocess.Popen(["bash", os.path.join(LIB, "gridlet-edit.sh")],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
#  DBusMenu (com.canonical.dbusmenu) — the right-click / click menu
# ---------------------------------------------------------------------------
# Menu item ids
ID_ROOT, ID_TITLE, ID_SEP1, ID_TOGGLE, ID_EDIT, ID_SEP2, ID_QUIT = 0, 1, 2, 3, 4, 5, 6


class DbusMenu(dbus.service.Object):
    def __init__(self, bus, path, app):
        super().__init__(bus, path)
        self.app = app
        self.revision = 1

    # -- item property helpers --
    def _item(self, item_id):
        a = self.app
        if item_id == ID_TITLE:
            return {"label": "Gridlet", "enabled": False}
        if item_id == ID_SEP1 or item_id == ID_SEP2:
            return {"type": "separator"}
        if item_id == ID_TOGGLE:
            return {"label": "Snapping enabled", "toggle-type": "checkmark",
                    "toggle-state": 1 if a.enabled else 0}
        if item_id == ID_EDIT:
            return {"label": "Grid Editor…"}
        if item_id == ID_QUIT:
            return {"label": "Quit Gridlet"}
        return {}

    def _node(self, item_id):
        # (id, properties, children)
        children = []
        if item_id == ID_ROOT:
            for cid in (ID_TITLE, ID_SEP1, ID_TOGGLE, ID_EDIT, ID_SEP2, ID_QUIT):
                children.append(dbus.Struct(
                    (cid, dbus.Dictionary(self._item(cid), signature="sv"),
                     dbus.Array([], signature="v")), signature="ia{sv}av"))
        props = {} if item_id == ID_ROOT else self._item(item_id)
        return dbus.Struct(
            (item_id, dbus.Dictionary(props, signature="sv"),
             dbus.Array(children, signature="v")), signature="ia{sv}av")

    @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, parentId, recursionDepth, propertyNames):
        return dbus.UInt32(self.revision), self._node(parentId if parentId else ID_ROOT)

    @dbus.service.method(MENU_IFACE, in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(self, ids, propertyNames):
        out = []
        for i in ids:
            out.append(dbus.Struct((i, dbus.Dictionary(self._item(i), signature="sv")),
                                   signature="ia{sv}"))
        return dbus.Array(out, signature="(ia{sv})")

    @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
    def GetProperty(self, id, name):
        return self._item(id).get(name, "")

    @dbus.service.method(MENU_IFACE, in_signature="isvu", out_signature="")
    def Event(self, id, eventId, data, timestamp):
        if eventId != "clicked":
            return
        if id == ID_TOGGLE:
            self.app.set_enabled(not self.app.enabled)
        elif id == ID_EDIT:
            launch_editor()
        elif id == ID_QUIT:
            self.app.quit()

    @dbus.service.method(MENU_IFACE, in_signature="i", out_signature="b")
    def AboutToShow(self, id):
        return False

    @dbus.service.signal(MENU_IFACE, signature="ui")
    def LayoutUpdated(self, revision, parent):
        pass

    def refresh(self):
        self.revision += 1
        self.LayoutUpdated(dbus.UInt32(self.revision), ID_ROOT)

    # DBusMenu also exposes properties (Version, Status, …)
    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, prop):
        return {"Version": dbus.UInt32(3), "Status": "normal",
                "TextDirection": "ltr"}.get(prop, "")

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary({"Version": dbus.UInt32(3), "Status": "normal",
                                "TextDirection": "ltr"}, signature="sv")


# ---------------------------------------------------------------------------
#  StatusNotifierItem (org.kde.StatusNotifierItem)
# ---------------------------------------------------------------------------
class StatusNotifierItem(dbus.service.Object):
    def __init__(self, bus, app):
        super().__init__(bus, "/StatusNotifierItem")
        self.app = app

    def _props(self):
        a = self.app
        return {
            "Category": "ApplicationStatus",
            "Id": "gridlet",
            "Title": "Gridlet",
            "Status": "Active",
            "WindowId": dbus.UInt32(0),
            "IconName": ICON_ON if a.enabled else ICON_OFF,
            "IconThemePath": "",
            "OverlayIconName": "",
            "AttentionIconName": "",
            "AttentionMovieName": "",
            "ToolTip": dbus.Struct(
                ("", dbus.Array([], signature="(iiay)"),
                 "Gridlet", "Grid snapping is " + ("ON" if a.enabled else "OFF")),
                signature="sa(iiay)ss"),
            "ItemIsMenu": True,
            "Menu": dbus.ObjectPath("/MenuBar"),
        }

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, prop):
        return self._props().get(prop, "")

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary(self._props(), signature="sv")

    @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
    def Activate(self, x, y):
        # Left-click when ItemIsMenu is true normally shows the menu, but some
        # hosts still call Activate — toggle as a convenience.
        self.app.set_enabled(not self.app.enabled)

    @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
    def SecondaryActivate(self, x, y):
        pass

    @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
    def ContextMenu(self, x, y):
        pass

    @dbus.service.method(SNI_IFACE, in_signature="is", out_signature="")
    def Scroll(self, delta, orientation):
        pass

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewIcon(self):
        pass

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewToolTip(self):
        pass

    @dbus.service.signal(SNI_IFACE, signature="s")
    def NewStatus(self, status):
        pass


# ---------------------------------------------------------------------------
#  App
# ---------------------------------------------------------------------------
class TrayApp:
    def __init__(self):
        self.bus = dbus.SessionBus()
        # The KWin script does the snapping, so it alone decides on/off. The
        # helper autostarts even when the script is disabled, so it says nothing.
        self.enabled = is_script_loaded()
        self.bus_name = dbus.service.BusName(
            "org.kde.StatusNotifierItem-%d-1" % os.getpid(), self.bus)
        self.menu = DbusMenu(self.bus, "/MenuBar", self)
        self.item = StatusNotifierItem(self.bus, self)
        self._register()
        self.loop = GLib.MainLoop()

    def _register(self):
        try:
            watcher = self.bus.get_object("org.kde.StatusNotifierWatcher",
                                          "/StatusNotifierWatcher")
            watcher.RegisterStatusNotifierItem(
                self.bus_name.get_name(),
                dbus_interface="org.kde.StatusNotifierWatcher")
        except Exception as e:
            print("gridlet-tray: could not register with the tray:", e, flush=True)

    def set_enabled(self, on):
        if on == self.enabled:
            return
        self.enabled = on
        if on:
            do_enable()
        else:
            do_disable()
        self.menu.refresh()
        self.item.NewIcon()
        self.item.NewToolTip()

    def quit(self):
        do_disable()
        self.loop.quit()

    def run(self):
        self.loop.run()


if __name__ == "__main__":
    DBusGMainLoop(set_as_default=True)
    TrayApp().run()
