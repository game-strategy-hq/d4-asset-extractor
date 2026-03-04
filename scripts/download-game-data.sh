#!/bin/bash
#
# Download Diablo IV game data from Blizzard CDN
#
# NOTE: This script is for reference/documentation only.
# CASCConsole.exe is Windows-only, so this must be run via:
#   - Windows directly
#   - Wine on Linux/macOS
#   - Windows VM
#
# Usage:
#   ./download-game-data.sh [preset] [output_dir]
#
# Presets:
#   minimal      - Small test set (~50MB)
#   ui-icons     - All UI icons (~500MB)
#   item-icons   - Item icons only (~200MB)
#   skill-icons  - Skill icons only (~100MB)
#   strings      - All language strings (~50MB)
#   strings-en   - English strings only (~5MB)

set -e

PRESET="${1:-minimal}"
OUTPUT_DIR="${2:-./game-data}"
CASC_CONSOLE="./tools/CASCConsole.exe"
D4_PRODUCT="fenris"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Diablo IV Online Data Downloader${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Preset:     ${PRESET}"
echo -e "  Output:     ${OUTPUT_DIR}"
echo ""

# Check for Wine if on non-Windows
if [[ "$OSTYPE" != "msys" && "$OSTYPE" != "win32" ]]; then
    if ! command -v wine &> /dev/null; then
        echo -e "${RED}Error: Wine is required to run CASCConsole.exe on this platform${NC}"
        echo ""
        echo "Install Wine:"
        echo "  macOS: brew install --cask wine-stable"
        echo "  Linux: sudo apt install wine"
        echo ""
        echo "Alternatively, run the PowerShell script on Windows:"
        echo "  .\\scripts\\download-game-data.ps1 -Preset ${PRESET}"
        exit 1
    fi
    WINE_PREFIX="wine"
else
    WINE_PREFIX=""
fi

# Check for CASCConsole
if [[ ! -f "$CASC_CONSOLE" ]]; then
    echo -e "${RED}Error: CASCConsole.exe not found${NC}"
    echo ""
    echo "Download from:"
    echo "  https://github.com/WoW-Tools/CASCExplorer/releases"
    echo ""
    echo "Place CASCConsole.exe in: ${CASC_CONSOLE}"
    exit 1
fi

echo -e "${GREEN}[✓] CASCConsole.exe found${NC}"

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Define patterns based on preset
case "$PRESET" in
    minimal)
        PATTERNS=(
            "2DUI_Icons_Item_Helm_*.tex"
            "2DUI_Icons_Item_Weapon_*.tex"
            "*enUS*.stl"
        )
        ;;
    ui-icons)
        PATTERNS=(
            "2DUI_Icons_Item_*.tex"
            "2DUI_Icons_Skill_*.tex"
            "2DUI_Icons_Buff_*.tex"
            "2DUI_Icons_Achievement_*.tex"
        )
        ;;
    item-icons)
        PATTERNS=("2DUI_Icons_Item_*.tex")
        ;;
    skill-icons)
        PATTERNS=("2DUI_Icons_Skill_*.tex")
        ;;
    strings)
        PATTERNS=("*.stl")
        ;;
    strings-en)
        PATTERNS=("*enUS*.stl")
        ;;
    *)
        echo -e "${RED}Unknown preset: ${PRESET}${NC}"
        exit 1
        ;;
esac

echo -e "${YELLOW}[*] Downloading patterns:${NC}"
for pattern in "${PATTERNS[@]}"; do
    echo "    - $pattern"
done
echo ""

# Download each pattern
for pattern in "${PATTERNS[@]}"; do
    echo -e "${YELLOW}[*] Downloading: ${pattern}${NC}"

    if [[ -n "$WINE_PREFIX" ]]; then
        $WINE_PREFIX "$CASC_CONSOLE" "online:${D4_PRODUCT}" -o "$OUTPUT_DIR" -f "$pattern" -e || true
    else
        "$CASC_CONSOLE" "online:${D4_PRODUCT}" -o "$OUTPUT_DIR" -f "$pattern" -e || true
    fi

    echo -e "${GREEN}[✓] Completed: ${pattern}${NC}"
done

# Create manifest
MANIFEST_FILE="${OUTPUT_DIR}/manifest.json"
FILE_COUNT=$(find "$OUTPUT_DIR" -type f \( -name "*.tex" -o -name "*.stl" \) | wc -l)
TOTAL_SIZE=$(du -sm "$OUTPUT_DIR" | cut -f1)

cat > "$MANIFEST_FILE" << EOF
{
  "download_date": "$(date -Iseconds)",
  "build_version": "latest",
  "product": "${D4_PRODUCT}",
  "preset": "${PRESET}",
  "patterns": $(printf '%s\n' "${PATTERNS[@]}" | jq -R . | jq -s .),
  "file_count": ${FILE_COUNT},
  "total_size_mb": ${TOTAL_SIZE}
}
EOF

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Download Complete${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Files downloaded: ${GREEN}${FILE_COUNT}${NC}"
echo -e "  Total size:       ${GREEN}${TOTAL_SIZE} MB${NC}"
echo -e "  Location:         ${GREEN}$(realpath "$OUTPUT_DIR")${NC}"
echo ""
echo -e "  .tex files: $(find "$OUTPUT_DIR" -name "*.tex" | wc -l)"
echo -e "  .stl files: $(find "$OUTPUT_DIR" -name "*.stl" | wc -l)"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Convert textures:  d4-extract textures ${OUTPUT_DIR} ./output"
echo "  2. Parse strings:     d4-extract strings ${OUTPUT_DIR} ./strings"
echo ""
