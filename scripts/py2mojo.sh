#!/usr/bin/env bash
# py2mojo.sh — transpile a .py file to .mojo via apex py2mojo
# Usage: scripts/py2mojo.sh <file.py>
# Output: mojo/<basename>.mojo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(dirname "$SCRIPT_DIR")"
APEX_DIR="$(dirname "$PROJ_DIR")/apex"
WORKSPACE="$APEX_DIR/workspace"
MOJO_OUT="$PROJ_DIR/mojo"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <file.py>" >&2
    exit 1
fi

# Resolve full path of source file
SRC="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
BASENAME="$(basename "$SRC")"
STEM="${BASENAME%.py}"

# Copy source into apex workspace
cp "$SRC" "$WORKSPACE/$BASENAME"

# Run apex from its own directory so skills/ and venv resolve correctly
# Pipe: reload solver_py2mojo (in case stale), then py2mojo, then quit
(cd "$APEX_DIR" && printf 'reload solver_py2mojo\npy2mojo %s\nquit\n' "$BASENAME" \
    | ./apex.py 2>/dev/null)

# Retrieve the output
OUT_MOJO="$WORKSPACE/${STEM}.mojo"
if [[ ! -f "$OUT_MOJO" ]]; then
    echo "py2mojo.sh: no output produced for $BASENAME (expected $OUT_MOJO)" >&2
    exit 1
fi

mkdir -p "$MOJO_OUT"
cp "$OUT_MOJO" "$MOJO_OUT/${STEM}.mojo"
echo "  transpiled: mojo/${STEM}.mojo"
