#!/usr/bin/env bash
# build.sh — Build and install the custom RTAB-Map SLAM node binary.
#
# Prerequisites: RTAB-Map and depthai-core must already be installed
#   (e.g. via jetson-harden.sh steps 13-14).
#
# Usage:
#   sudo bash build.sh          # build + install to /usr/local/bin
#   sudo bash build.sh clean    # remove build directory and rebuild
#
# Idempotent: re-running without "clean" reuses the existing build dir.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"
INSTALL_PREFIX="/usr/local"
BINARY="${INSTALL_PREFIX}/bin/rtabmap_slam_node"

if [[ "${1:-}" == "clean" ]]; then
    echo "Cleaning build directory..."
    rm -rf "$BUILD_DIR"
fi

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

echo "Configuring RTAB-Map SLAM node..."
cmake "$SCRIPT_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX"

echo "Building..."
make -j"$(nproc)"

echo "Installing..."
make install

if [[ ! -f "$BINARY" ]]; then
    echo "ERROR: Build did not produce $BINARY" >&2
    exit 1
fi

echo "RTAB-Map SLAM node installed: $BINARY"
