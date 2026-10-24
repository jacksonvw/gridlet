#!/usr/bin/env python3
"""
Gridlet — Wayland hotkey helper

Why this exists
---------------
On X11, Gridlet read the held modifier keys by polling `query_pointer().mask`.
Wayland deliberately forbids any app from reading global keyboard state (it's
exactly what a keylogger does), and KWin's scripting layer doesn't expose it
either. So the KWin script cannot tell when Ctrl+Meta is held.

This tiny helper fills that one gap. It reads the keyboard device directly,
tracks whether the configured modifier combo (default Ctrl+Meta) is currently held,
and on each press/release edge it pokes the KWin script via kglobalaccel's
`invokeShortcut` — GridletActivate when the combo goes down, GridletDeactivate
when it comes back up.

Reading /dev/input/event* requires permission that is NOT granted by default on
every distro. SteamOS gives the session user access; Fedora does not (the nodes
are root:input 0660 and the user isn't in `input`). Fedora needs a udev rule
tagging keyboards for uaccess — see wayland/70-gridlet-input.rules.

It uses only the Python standard library — no pip installs, which matters on
SteamOS's immutable root filesystem.

The gesture logic (grid overlay, zone painting, snapping) all lives in the
KWin script. This helper only answers one question: "is Ctrl+Meta held?"
"""

import glob
import json
import os
import select
import struct
import subprocess
import sys
import time

# struct input_event on 64-bit Linux:
#   struct timeval time;  (two longs = 16 bytes)
#   __u16 type; __u16 code; __s32 value;   (8 bytes)  → 24 bytes total
EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
EV_KEY = 0x01

# Linux input-event-codes.h keycodes, grouped by the modifier we care about.
# Either the left or right variant counts as "that modifier is held".
MOD_KEYS = {
    "ctrl":  {29, 97},    # KEY_LEFTCTRL, KEY_RIGHTCTRL
    "shift": {42, 54},    # KEY_LEFTSHIFT, KEY_RIGHTSHIFT
    "alt":   {56, 100},   # KEY_LEFTALT, KEY_RIGHTALT
    "meta":  {125, 126},  # KEY_LEFTMETA, KEY_RIGHTMETA
}

CONFIG_FILE = os.path.expanduser("~/.config/gridlet/config.json")

# qdbus6 exists on SteamOS but not on Fedora, so we go through the shim that
# falls back to gdbus. It sits beside this file both in the repo and once
# installed, so resolve it relative to us.
QDBUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gridlet-qdbus")

# Same defaults as config.py so the two never disagree.
DEFAULT_HOTKEY = {"ctrl": True, "shift": False, "alt": False, "meta": True}

DEBUG = "--debug" in sys.argv


def log(*args):
    if DEBUG:
        print("gridlet-helper:", *args, flush=True)


def load_required_mods():
    """Read which modifiers are required from config.json (default Ctrl+Meta)."""
    hotkey = dict(DEFAULT_HOTKEY)
    try:
        with open(CONFIG_FILE) as f:
            user = json.load(f).get("hotkey", {})
        for k in hotkey:
            hotkey[k] = bool(user.get(k, hotkey[k]))
    except Exception:
        pass  # missing/broken config → defaults
    return [k for k, v in hotkey.items() if v]


def find_keyboard_devices():
    """
    Return /dev/input/eventN paths for every device with a keyboard handler.
    Parsing /proc/bus/input/devices avoids any external dependency.
    """
    paths = []
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except Exception:
        # Fallback: try all event nodes.
        return sorted(glob.glob("/dev/input/event*"))
    for block in blocks:
        for line in block.splitlines():
            if line.startswith("H: Handlers=") and "kbd" in line:
                for tok in line.split():
                    if tok.startswith("event"):
                        paths.append("/dev/input/" + tok)
    return paths


def invoke_shortcut(name):
    """
    Fire a kglobalaccel action registered by the KWin script, and wait for it.

    Each call runs in its own process, so without the wait a release could
    reach kglobalaccel before the press it follows, and the script would then
    think the hotkey was still held.
    """
    try:
        subprocess.run(
            [QDBUS, "org.kde.kglobalaccel", "/component/kwin",
             "org.kde.kglobalaccel.Component.invokeShortcut", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
    except Exception as e:
        log("invoke failed:", e)


def open_devices(paths):
    fds = {}
    for p in paths:
        try:
            fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
        except Exception as e:
            log("could not open", p, e)
    return fds


def main():
    required = load_required_mods()
    log("required modifiers:", required)
    if not required:
        log("no modifiers configured; nothing to watch")

    paths = find_keyboard_devices()
    fds = open_devices(paths)
    if not fds:
        print("gridlet-helper: no readable keyboard devices found.\n"
              "  Found %d keyboard node(s), none readable — this is a permissions\n"
              "  problem, not a missing keyboard. Install the udev rule from the\n"
              "  Gridlet repo, then reboot:\n"
              "    sudo cp wayland/70-gridlet-input.rules /etc/udev/rules.d/\n"
              "  then check (expect 1 or more):\n"
              "    getfacl -p /dev/input/event* | grep -c \"user:$USER:rw\"" % len(paths),
              file=sys.stderr)
        sys.exit(1)
    log("watching:", ", ".join(fds.values()))

    keys_down = set()                       # currently-held modifier keycodes
    mod_down = {m: False for m in MOD_KEYS}  # per-modifier held state
    combo_active = False                     # is the required combo satisfied?
    last_rescan = time.time()

    def recompute():
        nonlocal combo_active
        held = bool(required) and all(mod_down[m] for m in required)
        if held != combo_active:
            combo_active = held
            invoke_shortcut("GridletActivate" if held else "GridletDeactivate")
            log("combo", "DOWN -> activate" if held else "UP -> deactivate")

    while True:
        # Wake every 2s even with no input so we can rescan for hotplugged
        # keyboards (e.g. the wireless dongle reconnecting).
        readable, _, _ = select.select(list(fds), [], [], 2.0)

        for fd in readable:
            try:
                data = os.read(fd, EVENT_SIZE * 64)
            except OSError:
                # Device vanished (unplugged) — drop it.
                os.close(fd)
                del fds[fd]
                continue
            for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                _, _, etype, code, value = struct.unpack(
                    EVENT_FORMAT, data[off:off + EVENT_SIZE])
                if etype != EV_KEY:
                    continue
                for mod, codes in MOD_KEYS.items():
                    if code in codes:
                        if value == 1:
                            keys_down.add(code)
                        elif value == 0:
                            keys_down.discard(code)
                        mod_down[mod] = any(c in keys_down for c in codes)
                        break
            recompute()

        # Periodic rescan for new keyboard devices.
        now = time.time()
        if now - last_rescan > 2.0:
            last_rescan = now
            for p in find_keyboard_devices():
                if p not in fds.values():
                    try:
                        fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
                        log("added device", p)
                    except Exception:
                        pass


if __name__ == "__main__":
    main()
