# Diablo IV Asset Extractor

Extract icons and textures from Diablo IV game files. This tool reads the game's CASC archives and exports individual PNG files.

## What This Does

- Extracts UI icons, skill icons, item icons from the Windows version of Diablo IV
- Outputs individual PNG files with transparency
- Handles texture decompression (BC1, BC3, BC7, etc.)
- Parses StringList files for game text

## Quick Start (Windows)

### 1. Install Git

Download and install Git from: https://git-scm.com/download/win

Click "Next" through all the options (defaults are fine).

**Close and reopen PowerShell after installing Git.**

### 2. Install uv

uv is a fast Python package manager that automatically handles Python for you.

Open **PowerShell** and run:
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Close and reopen PowerShell after installing.**

### 3. Install the extractor and download tools

```powershell
uv tool install git+https://github.com/game-strategy-hq/d4-asset-extractor
d4-extract setup
```

### 4. Run the extraction

```powershell
d4-extract textures "C:\Program Files\Diablo IV" .\icons --filter "2DUI*"
```

This creates an `icons` folder with extracted UI icons.

## Finding Your Game Files

The tool needs your Diablo IV installation directory.

**Typical Windows path:**
```
C:\Program Files\Diablo IV
```

This folder should contain:
- `Data\` folder with `data.000`, `data.001`, etc.
- `Data\` folder with `.idx` files
- `.build.info` file

## Usage

### Extracting Textures

```
d4-extract textures <GAME_DIR> [OUTPUT_DIR] [OPTIONS]

Arguments:
  GAME_DIR    Path to Diablo IV installation
  OUTPUT_DIR  Directory to save extracted PNGs (default: ./textures)

Options:
  --filter, -f   Filter pattern (e.g., "2DUI*", "Items*", "Skill*")
  --format, -o   Output format: png, jpg, webp (default: png)
  --no-crop      Disable transparent border cropping
  --no-slice     Disable atlas slicing
  --help         Show help message
```

### Extracting Strings

```
d4-extract strings <GAME_DIR> [OUTPUT_DIR] [OPTIONS]

Arguments:
  GAME_DIR    Path to Diablo IV installation
  OUTPUT_DIR  Directory to save JSON files (default: ./strings)

Options:
  --language, -l  Language code: enUS, deDE, frFR, etc. (default: enUS)
  --help          Show help message
```

## Examples

```powershell
# Extract UI icons
d4-extract textures "C:\Program Files\Diablo IV" .\icons --filter "2DUI*"

# Extract item icons
d4-extract textures "C:\Program Files\Diablo IV" .\items --filter "*Item*"

# Extract skill icons
d4-extract textures "C:\Program Files\Diablo IV" .\skills --filter "*Skill*"

# Extract all English strings
d4-extract strings "C:\Program Files\Diablo IV" .\strings

# Extract German strings
d4-extract strings "C:\Program Files\Diablo IV" .\strings --language deDE

# Check game installation info
d4-extract info "C:\Program Files\Diablo IV"
```

## Output

The tool creates a flat directory of PNG files:
```
icons/
  2DUI_Icons_Item_Helm_001.png
  2DUI_Icons_Item_Weapon_Sword.png
  2DUI_Icons_Skill_Barbarian_Bash.png
  ...
```

## Troubleshooting

**"CASCConsole.exe not found" / "texconv.exe not found"**
- Run: `d4-extract setup`
- Or download manually from [CASCExplorer](https://github.com/WoW-Tools/CASCExplorer/releases) and [DirectXTex](https://github.com/microsoft/DirectXTex/releases)

**"Game directory not found"**
- Verify the path contains a `Data\` folder with `.idx` files
- Try running: `d4-extract info "C:\Program Files\Diablo IV"`

## Development

```powershell
# Clone the repo
git clone https://github.com/game-strategy-hq/d4-asset-extractor
cd d4-asset-extractor

# Run locally
uv run d4-extract --help

# Install locally for testing
uv tool install .
```

## License

MIT

**Note:** Game assets remain property of Blizzard Entertainment. Do not redistribute extracted assets.
