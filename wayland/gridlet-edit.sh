#!/usr/bin/env bash
# Launch the Gridlet Grid Editor, then apply changes if the user hit "Save & Apply".
# The editor (../editor.py) exits 0 when saved, 1 when cancelled — unchanged from
# the X11 version. Installed to ~/.local/share/gridlet alongside config.py.
LIB="$HOME/.local/share/gridlet"
python3 "$LIB/editor.py"
if [ $? -eq 0 ]; then
    "$LIB/gridlet-apply.sh"
fi
