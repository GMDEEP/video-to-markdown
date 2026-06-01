#!/usr/bin/env bash
# video-to-markdown setup script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== video-to-markdown setup ==="
echo ""

# Python check
python3 --version >/dev/null 2>&1 || { echo "ERROR: Python 3 not found."; exit 1; }
echo "✓ Python: $(python3 --version)"

# ffmpeg check
if command -v ffmpeg &>/dev/null; then
    echo "✓ ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    echo ""
    echo "WARNING: ffmpeg not found. Install it before using this skill:"
    echo "  macOS:          brew install ffmpeg"
    echo "  Ubuntu/Debian:  sudo apt install ffmpeg"
    echo "  Windows:        https://ffmpeg.org/download.html"
    echo ""
fi

# yt-dlp check
if command -v yt-dlp &>/dev/null; then
    echo "✓ yt-dlp: $(yt-dlp --version)"
else
    echo "Installing yt-dlp..."
    pip install yt-dlp
fi

# Python packages
echo ""
echo "Installing Python packages..."

# For Facebook impersonation support, install yt-dlp with curl-cffi
pip install "yt-dlp[default,curl-cffi]" 2>/dev/null || pip install yt-dlp

pip install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next step — set your Anthropic API key:"
echo "  export ANTHROPIC_API_KEY=sk-ant-..."
echo ""
echo "Test run (YouTube):"
echo "  python $SCRIPT_DIR/video_analyzer.py \"https://youtu.be/dQw4w9WgXcQ\" --max-frames 10"
echo ""
