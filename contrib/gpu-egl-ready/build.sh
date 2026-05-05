#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="/usr/local/bin/gpu-egl-ready"

gcc -O2 -o "$BINARY" "$SCRIPT_DIR/gpu-egl-ready.c" -lEGL
chmod 755 "$BINARY"
echo "Installed: $BINARY"
