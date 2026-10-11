#!/usr/bin/env bash
# ============================================================
# Split & Stitch for QuickMagicMotion — Launcher (Linux / macOS)
# ============================================================

set -e

# Ensure ~/.local/bin and ~/.cargo/bin are in PATH
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# Move to the script's directory
cd "$(dirname "$0")"

echo ""
echo "============================================================"
echo "  Split & Stitch for QuickMagicMotion - Launcher"
echo "============================================================"
echo ""

# [1/4] Check uv installation
echo "[1/4] Checking uv installation..."
if ! command -v uv >/dev/null 2>&1; then
    echo "  uv is not installed. Installing uv via curl..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        echo "  [ERROR] uv could not be found after installation."
        echo "  Please install uv manually: https://docs.astral.sh/uv/"
        exit 1
    fi
fi
echo "  uv is installed: $(uv --version)"

# [2/4] Check FFmpeg
echo ""
echo "[2/4] Checking FFmpeg installation..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "  [NOTICE] FFmpeg was not found in PATH."
    echo "  Note: FFmpeg is required for video probing and splitting."
    echo "  If you only need motion stitching, you can proceed without it."
else
    echo "  FFmpeg is installed: $(ffmpeg -version | head -n 1)"
fi

# [3/4] uv sync
echo ""
echo "[3/4] Synchronizing dependencies with uv sync..."
uv sync

# [4/4] Launch GUI
echo ""
echo "[4/4] Starting Split & Stitch GUI..."
echo ""
uv run splitstitch gui

echo ""
echo "Application closed."
