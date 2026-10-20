#!/usr/bin/env python3
"""
Gridlet — Config File

Loads settings from ~/.config/gridlet/config.json.
If the file doesn't exist (first run), it's created with sensible defaults.
If the file is missing any keys, those keys fall back to defaults too — so
the app never crashes if you partially edit the config.

Config file location: ~/.config/gridlet/config.json

Example config.json:
    {
        "grid": {
            "rows": 4,
            "cols": 6,
            "gap": 4
        },
        "hotkey": {
            "ctrl": true,
            "shift": false,
            "alt": false,
            "meta": true
        }
    }

The "gap" setting is the number of pixels of space between each zone,
and between each zone and the edge of the screen. For example, with gap=4:
  - Adjacent zones have 8px between them (4px from each side)
  - Zones at the screen edge have 4px of space before the edge
  - Windows snap to exactly the highlighted area in the grid
"""

import json
import os

# Where the config lives (~ expands to the user's home directory)
CONFIG_DIR = os.path.expanduser("~/.config/gridlet")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Default values — used if the config file is missing or incomplete
DEFAULTS = {
    "grid": {
        "rows": 4,
        "cols": 6,
        "gap": 4           # pixels of space between zones (and from screen edges)
    },
    "hotkey": {
        "ctrl": True,      # Ctrl key must be held
        "shift": False,    # Shift NOT required (KDE Plasma intercepts Shift+drag)
        "alt": False,      # Alt not required
        "meta": True       # Meta/Super (Windows key) must be held
    }
}


def deep_merge(defaults, user):
    """
    Recursively merge user settings into defaults.
    Any key missing from user's config falls back to the default.

    This is like Object.assign({}, defaults, user) in JavaScript,
    but it goes deep — nested objects are also merged, not replaced wholesale.
    """
    result = dict(defaults)
    for key, value in user.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Both are dicts — recurse
            result[key] = deep_merge(result[key], value)
        else:
            # User value wins
            result[key] = value
    return result


def load_config():
    """
    Load config from disk. Creates the file with defaults if it doesn't exist.

    Returns:
        dict with all config values (always complete — missing keys filled from defaults)
    """
    # Create config directory if it doesn't exist
    # (like mkdir -p ~/.config/gridlet)
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
        print(f"  Created config directory: {CONFIG_DIR}")

    # If config file doesn't exist, create it with defaults
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULTS)
        print(f"  Created default config: {CONFIG_FILE}")
        return dict(DEFAULTS)

    # Load user's config file
    try:
        with open(CONFIG_FILE, "r") as f:
            user_config = json.load(f)

        # Merge with defaults so missing keys fall back gracefully
        merged = deep_merge(DEFAULTS, user_config)
        print(f"  Loaded config from: {CONFIG_FILE}")
        return merged

    except json.JSONDecodeError as e:
        print(f"  ⚠ Config file has invalid JSON: {e}")
        print(f"  ⚠ Using default settings (fix {CONFIG_FILE} to customize)")
        return dict(DEFAULTS)

    except Exception as e:
        print(f"  ⚠ Could not read config file: {e}")
        print(f"  ⚠ Using default settings")
        return dict(DEFAULTS)


def save_config(config):
    """
    Write config to disk as formatted JSON.

    Args:
        config: dict of settings to save
    """
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"  ⚠ Could not save config file: {e}")
