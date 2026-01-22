#!/bin/bash

# Setup script for FFmpeg Lambda Layer
# This script downloads a pre-built FFmpeg static binary for AWS Lambda

set -e

echo "=========================================="
echo "FFmpeg Layer Setup for AWS Lambda"
echo "=========================================="
echo ""

LAYER_DIR="layers/ffmpeg"
BIN_DIR="${LAYER_DIR}/bin"

# Create directories
mkdir -p "${BIN_DIR}"

echo "Downloading FFmpeg static binary for Lambda..."
echo ""

# Option 1: Download from johnvansickle.com (static builds)
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"

cd /tmp
echo "Downloading from ${FFMPEG_URL}..."
curl -L -o ffmpeg-static.tar.xz "${FFMPEG_URL}"

echo "Extracting FFmpeg..."
tar -xf ffmpeg-static.tar.xz

# Find the extracted directory (name varies by version)
FFMPEG_DIR=$(find . -maxdepth 1 -type d -name "ffmpeg-*-amd64-static" | head -n 1)

if [ -z "$FFMPEG_DIR" ]; then
    echo "Error: Could not find extracted FFmpeg directory"
    exit 1
fi

echo "Found FFmpeg in: $FFMPEG_DIR"

# Go back to project directory
cd -

# Copy binaries
echo "Copying ffmpeg and ffprobe binaries..."
cp "/tmp/${FFMPEG_DIR}/ffmpeg" "${BIN_DIR}/"
cp "/tmp/${FFMPEG_DIR}/ffprobe" "${BIN_DIR}/"

# Make binaries executable
chmod +x "${BIN_DIR}/ffmpeg"
chmod +x "${BIN_DIR}/ffprobe"

# Verify
echo ""
echo "Verifying FFmpeg installation..."
"${BIN_DIR}/ffmpeg" -version | head -n 1
"${BIN_DIR}/ffprobe" -version | head -n 1

# Get sizes
FFMPEG_SIZE=$(du -h "${BIN_DIR}/ffmpeg" | cut -f1)
FFPROBE_SIZE=$(du -h "${BIN_DIR}/ffprobe" | cut -f1)

echo ""
echo "=========================================="
echo "✓ FFmpeg layer setup complete!"
echo "=========================================="
echo ""
echo "Binaries installed:"
echo "  - ${BIN_DIR}/ffmpeg (${FFMPEG_SIZE})"
echo "  - ${BIN_DIR}/ffprobe (${FFPROBE_SIZE})"
echo ""
echo "The FFmpeg layer will be packaged and deployed with SAM."
echo ""
echo "Next step: Run './config/setup-secrets.sh' to configure your secrets"
