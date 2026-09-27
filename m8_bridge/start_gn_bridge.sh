#!/usr/bin/env bash
# Blender GN bridge launcher (macOS / Linux) - keep this terminal open while using blender-gn MCP
# Cross-device: export BLENDER_EXE if Blender is not auto-detected, e.g.
#   export BLENDER_EXE=/opt/blender/blender
set -e
GN_ALLOW_BACKGROUND=1
export GN_ALLOW_BACKGROUND
BRIDGE="$(cd "$(dirname "$0")" && pwd)"

find_blender() {
    if [ -n "$BLENDER_EXE" ] && [ -x "$BLENDER_EXE" ]; then echo "$BLENDER_EXE"; return 0; fi
    if command -v blender >/dev/null 2>&1; then command -v blender; return 0; fi
    for p in \
        "/Applications/Blender.app/Contents/MacOS/Blender" \
        "$HOME/Applications/Blender.app/Contents/MacOS/Blender" \
        "/Applications/Blender 5.2.app/Contents/MacOS/Blender" \
        "/opt/blender/blender" \
        "/usr/local/bin/blender" \
        "/snap/bin/blender"; do
        if [ -x "$p" ]; then echo "$p"; return 0; fi
    done
    return 1
}

if ! BLENDER_BIN="$(find_blender)"; then
    echo "[ERROR] Blender executable not found. Install Blender 5.x or set the environment variable:"
    echo "    export BLENDER_EXE=/path/to/blender"
    exit 1
fi

echo "Starting Blender GN bridge (TCP 9876) using: $BLENDER_BIN"
echo "Keep this terminal OPEN while using the blender-gn MCP server."
"$BLENDER_BIN" -b -P "$BRIDGE/bootstrap_blender.py"
echo
echo "Blender bridge exited."
