#!/bin/bash
# Cleanup script for d4-asset-extractor output
# Removes files without using recursive flags

set -e

cleanup_dir() {
    local dir="$1"
    if [ -d "$dir" ]; then
        # Remove all png files in immediate subdirectories
        find "$dir" -maxdepth 2 -name "*.png" -type f -delete
        # Remove empty directories
        find "$dir" -maxdepth 2 -type d -empty -delete
        echo "Cleaned: $dir"
    fi
}

case "$1" in
    icons)
        cleanup_dir "d4-data/icons"
        cleanup_dir "d4-data/icons-fixed"
        ;;
    textures)
        find "d4-data/textures" -maxdepth 1 -name "*.png" -type f -delete 2>/dev/null || true
        echo "Cleaned: d4-data/textures"
        ;;
    all)
        cleanup_dir "d4-data/icons"
        cleanup_dir "d4-data/icons-fixed"
        find "d4-data/textures" -maxdepth 1 -name "*.png" -type f -delete 2>/dev/null || true
        echo "Cleaned all output directories"
        ;;
    *)
        echo "Usage: $0 {icons|textures|all}"
        exit 1
        ;;
esac
