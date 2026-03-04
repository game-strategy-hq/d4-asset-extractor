# Diablo IV Asset Extractor

Extract and convert Diablo IV game assets (textures, strings, game data) from CASC storage.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

Diablo IV uses Blizzard's **CASC** (Content Addressable Storage Container) system for game files. This tool provides a Python-based pipeline to:

1. **Extract** raw files from CASC storage
2. **Convert** `.tex` textures to PNG/JPG/WebP
3. **Parse** `.stl` (StringList) files to JSON
4. **Search** extracted sprites using perceptual hashing

> **Note:** This project is part of the [Game Strategy HQ](https://github.com/game-strategy-hq) organization, designed to power game database websites similar to our Diablo Immortal tools.

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/game-strategy-hq/d4-asset-extractor.git
cd d4-asset-extractor

# Install with uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

### Basic Usage

```bash
# Extract UI icons to PNG
d4-extract textures "C:\Program Files\Diablo IV" ./icons --filter "2DUI*"

# Parse string files to JSON
d4-extract strings "C:\Program Files\Diablo IV" ./strings

# Search for similar sprites
d4-search screenshot.png ./icons --top 20

# View installation info
d4-extract info
```

## Commands

### `d4-extract textures`

Extract and convert `.tex` texture files to standard image formats.

```bash
d4-extract textures <GAME_DIR> [OUTPUT_DIR] [OPTIONS]

Options:
  --filter, -f    Filter pattern (e.g., "2DUI*", "Items*")
  --format, -o    Output format: png, jpg, webp (default: png)
  --no-crop, -nc  Disable transparent border cropping
  --no-slice, -ns Disable atlas slicing
  --concurrency, -c  Parallel tasks (default: 4)
```

**Examples:**
```bash
# Extract all UI icons
d4-extract textures "C:\Program Files\Diablo IV" ./ui-icons --filter "2DUI*"

# Extract item icons as WebP
d4-extract textures /path/to/d4 ./items --filter "Items*" --format webp

# Extract without post-processing
d4-extract textures "C:\Program Files\Diablo IV" ./raw --no-crop --no-slice
```

### `d4-extract strings`

Parse `.stl` (StringList) files containing game text.

```bash
d4-extract strings <GAME_DIR> [OUTPUT_DIR] [OPTIONS]

Options:
  --language, -l  Language code (default: enUS)
```

**Examples:**
```bash
# Extract English strings
d4-extract strings "C:\Program Files\Diablo IV" ./strings

# Extract German strings
d4-extract strings "C:\Program Files\Diablo IV" ./strings-de --language deDE
```

### `d4-extract casc`

Extract raw files from CASC storage (requires CASCConsole.exe).

```bash
d4-extract casc <GAME_DIR> [OUTPUT_DIR] [OPTIONS]

Options:
  --filter, -f  Filter pattern for files to extract
```

### `d4-search`

Find visually similar sprites using perceptual hashing.

```bash
d4-search <QUERY_IMAGE> [SPRITES_DIR] [OPTIONS]

Options:
  --top, -n     Number of results (default: 10)
  --rebuild, -r Force rebuild sprite index
  --no-copy     Don't copy results to search-results/
```

**Examples:**
```bash
# Search from a screenshot
d4-search screenshot.png ./icons --top 30

# Force index rebuild
d4-search item.png ./textures --rebuild
```

## Prerequisites

### Required Tools

#### CASCConsole (for CASC extraction)

Download from [WoW-Tools/CASCExplorer](https://github.com/WoW-Tools/CASCExplorer/releases):

1. Download the latest release
2. Extract `CASCConsole.exe` to `tools/` directory
3. The tool will auto-detect it

#### texconv (for texture conversion)

Optional but recommended for full `.tex` format support. Download from [Microsoft DirectXTex](https://github.com/microsoft/DirectXTex/releases).

### Directory Structure

```
d4-asset-extractor/
├── tools/
│   ├── CASCConsole.exe    # Required for CASC extraction
│   └── texconv.exe        # Optional, for .tex conversion
├── src/d4_asset_extractor/
│   ├── cli.py             # Main CLI
│   ├── casc.py            # CASC extraction
│   ├── texture.py         # Texture conversion
│   ├── strings.py         # String parsing
│   └── search.py          # Sprite search
└── output/                # Your extracted files
```

---

# Technical Documentation

## Diablo IV vs Diablo Immortal: Architecture Comparison

| Aspect | Diablo Immortal | Diablo 4 |
|--------|-----------------|----------|
| **Developer** | Netease / Blizzard | Blizzard |
| **Storage** | MPK archives | CASC containers |
| **Texture Format** | MESSIAH (.png in atlas) | `.tex` files |
| **Compression** | LZ4 + BC7/ASTC | CASC internal |
| **Sprites** | Cocos2d plist atlases | Individual textures |
| **Metadata** | resource.repository | SNO files, TOC files |
| **Strings** | Embedded | `.stl` StringList files |
| **Index** | MPKInfo binary | CASC .idx journals |

**Key Insight:** Diablo Immortal uses Netease's mobile engine (Cocos2d-based) with sprite atlases, while Diablo 4 uses Blizzard's proprietary engine with individual texture files. This makes D4 extraction conceptually simpler once you get past the CASC layer.

---

## CASC Storage System

### What is CASC?

**CASC** (Content Addressable Storage Container) is Blizzard's file storage system introduced in 2014 to replace the older MPQ format. It's used by:

- World of Warcraft (since Warlords of Draenor)
- Diablo III (Reaper of Souls)
- Diablo IV
- StarCraft II
- Heroes of the Storm
- Overwatch

### How CASC Works

```
Diablo IV Installation
├── Data/
│   ├── data.000          # Archive files (~256MB each)
│   ├── data.001
│   ├── data.002
│   ├── ...
│   ├── 0a/               # Index directories
│   │   └── 0a1b2c3d...idx
│   └── ...
└── .build.info           # Build metadata
```

**Key Concepts:**

1. **Content Addressable**: Files are identified by their content hash (MD5), not paths
2. **Encoding Keys**: Truncated MD5 hashes that uniquely identify each file
3. **Index Journals**: `.idx` files map key prefixes to archive offsets
4. **TVFS Layer**: Virtual file system providing path-based access

### CASC Documentation

| Resource | URL | Description |
|----------|-----|-------------|
| CASC Format Spec | https://wowdev.wiki/CASC | Complete technical specification |
| TACT Protocol | https://wowdev.wiki/TACT | Content transfer protocol |
| TVFS | https://wowdev.wiki/TVFS | Virtual file system layer |
| General Info | http://www.zezula.net/en/casc/main.html | Overview and tools |

---

## File Formats

### Texture Files (.tex)

Diablo IV textures are stored in a proprietary `.tex` format:

```
.tex file structure (simplified):
┌────────────────────────┐
│ Header (variable)      │ ← Format metadata, dimensions
├────────────────────────┤
│ Mipmap levels          │ ← Multiple resolution versions
├────────────────────────┤
│ Compressed pixel data  │ ← BC7, DXT, or raw RGBA
└────────────────────────┘
```

**Conversion Pipeline:**
```
.tex → .dds (via texconv) → .png/.jpg/.webp (via Pillow)
```

**Common Texture Patterns:**

| Pattern | Content |
|---------|---------|
| `2DUI*` | UI elements, item icons |
| `Items*` | Item textures |
| `Skills*` | Skill icons |
| `Monsters*` | Enemy textures |
| `Effects*` | Visual effects |

### StringList Files (.stl)

Binary format containing all game text:

```
.stl file structure:
┌────────────────────────┐
│ Header (8 bytes)       │ ← Game ID, format version
├────────────────────────┤
│ Entry count (4 bytes)  │
├────────────────────────┤
│ Entry table            │ ← [hash_id, offset] pairs
├────────────────────────┤
│ String data pool       │ ← Null-terminated UTF-8 strings
└────────────────────────┘
```

**Language Codes:**
- `enUS` - English (US)
- `deDE` - German
- `esES` - Spanish (Spain)
- `esMX` - Spanish (Mexico)
- `frFR` - French
- `itIT` - Italian
- `jaJP` - Japanese
- `koKR` - Korean
- `plPL` - Polish
- `ptBR` - Portuguese (Brazil)
- `ruRU` - Russian
- `zhCN` - Chinese (Simplified)
- `zhTW` - Chinese (Traditional)

### SNO Files (Binary Metadata)

SNO (presumably "Scene Node Object") files contain structured game data:

- Item definitions
- Skill data
- Quest information
- World/map data

Parsed using tools like [d4parse](https://github.com/Dakota628/d4parse).

### TOC Files (Table of Contents)

Index files that catalog game assets. Can be converted to YAML for inspection.

---

## Essential Tools & Resources

### CASC Extraction Tools

| Tool | URL | Description |
|------|-----|-------------|
| **CASCExplorer** | https://github.com/WoW-Tools/CASCExplorer | GUI + CLI for CASC extraction |
| **CASCExplorer Releases** | https://github.com/WoW-Tools/CASCExplorer/releases | Download page |
| Ladik's CASC Viewer | https://www.hiveworkshop.com/threads/ladiks-casc-viewer.331540/ | Alternative GUI |
| jybp/casc | https://github.com/jybp/casc | Rust CASC library |
| CascLib | https://github.com/heksesang/CascLib | C++ CASC library |
| cascette-rs | https://github.com/wowemulation-dev/cascette-rs | Rust NGDP tools |

### Texture Extraction

| Tool | URL | Description |
|------|-----|-------------|
| **d4-texture-extractor** | https://github.com/adainrivers/d4-texture-extractor | Node.js texture converter |
| DirectXTex (texconv) | https://github.com/microsoft/DirectXTex | Microsoft DDS tools |

**d4-texture-extractor CLI Options:**
```bash
npx d4-texture-extractor [options]

Options:
  -e              Auto-extract via CASCConsole
  -g <path>       D4 installation directory
  -f <filter>     Texture name filter (e.g., "2DUI*")
  -o <format>     Output: png, jpg, webp
  -c <num>        Concurrency (parallel tasks)
  -p <path>       Output destination
  -nc             Disable cropping
  -ns             Disable slicing
  -nsf            No separate slice folders
```

### Data Parsing Tools

| Tool | URL | Language | Parses |
|------|-----|----------|--------|
| **d4parse** | https://github.com/Dakota628/d4parse | Go | SNO, TOC, Quest files |
| **diablo4-data-harvest** | https://github.com/mfloob/diablo4-data-harvest | Rust | .stl, .aff, .skl |
| **diablo-4-string-parser** | https://github.com/alkhdaniel/diablo-4-string-parser | Python | .stl → JSON |

**d4parse Commands:**
```bash
dumpsnometa    # Convert SNO metadata to spew format
dumptoc        # Convert TOC files to YAML
structgen      # Generate Go code for SNO structures
```

### Pre-Parsed Data Sources

| Resource | URL | Description |
|----------|-----|-------------|
| **DiabloTools/d4data** | https://github.com/DiabloTools/d4data | Comprehensive parsed JSON data |
| d4parse Docs | https://docs.diablo.farm/ | Data documentation |
| Maxroll D4 Scraper | https://github.com/danparizher/maxroll-d4-scraper | Web scraper for build data |

**d4data Repository Structure:**
```
d4data/
├── definitions/    # Game attribute definitions
├── json/           # Parsed game data (items, skills, etc.)
├── names/          # Hash mappings, dictionaries
├── texture/        # Asset references
├── svg/            # Vector graphics
└── tools/          # JavaScript processing scripts
```

### 3D Model Extraction

| Tool | URL | Description |
|------|-----|-------------|
| **DiabloTools Releases** | https://github.com/DiabloTools/Diablo4Tools-Releases | D4Analyzer for models |
| Blender Template | https://www.deviantart.com/trappissy/art/Extract-Diablo-4-Blender-Template-Diablo4-1146664821 | Extraction workflow |
| Sketchfab D4 | https://sketchfab.com/tags/diablo4 | Community 3D models |
| ResHax D4 | https://reshax.com/topic/14-diablo-iv-app/ | Model resources |

---

## Community Databases

### Item/Skill Databases

| Site | URL | Features |
|------|-----|----------|
| **Diablo4.gg** | https://diablo4.gg/database/ | Items, skills, builds, aspects |
| **Maxroll D4** | https://maxroll.gg/d4/ | Build planner, guides |
| **Wowhead D4** | https://www.wowhead.com/diablo-4/database | Traditional wiki format |
| Diablo4.cc | https://diablo4.cc/ | Items, recipes, aspects |
| D4Builds.gg | https://d4builds.gg/ | Unique items, builds |
| Lothrik Calculator | https://lothrik.github.io/diablo4-build-calc/database/ | Build calculator, history |
| TeamBRG D4DB | https://teambrg.com/diablo-4/db | Skills, aspects |
| Fextralife Wiki | https://diablo4.wiki.fextralife.com/ | Comprehensive guides |
| DaOpa D4 | https://gamingwithdaopa.ellatha.com/diablo4/database-lists/ | Guides, database |

### Community Hubs

| Resource | URL | Description |
|----------|-----|-------------|
| **DiabloTools Org** | https://github.com/DiabloTools | Central extraction tools hub |
| **Awesome-D4** | https://github.com/cagartner/awesome-d4 | Curated resource list |
| GitHub Topic: diablo4 | https://github.com/topics/diablo4 | Related projects |
| GitHub Topic: diablo-4 | https://github.com/topics/diablo-4 | More projects |

### Discord Integration

| Tool | URL | Description |
|------|-----|-------------|
| **Inarius Bot** | https://github.com/ALCHElVlY/Inarius | Discord D4 companion |

---

## Extraction Workflows

### Workflow 1: Quick Texture Extraction

For just getting UI icons quickly:

```bash
# 1. Install Node.js tool
npm install -g d4-texture-extractor

# 2. Extract UI textures
npx d4-texture-extractor -g "C:\Program Files\Diablo IV" -e -f "2DUI*" -o png
```

### Workflow 2: Full Data Pipeline

For comprehensive data extraction:

```bash
# 1. Extract CASC files
./tools/CASCConsole.exe "C:\Program Files\Diablo IV" -o ./extracted -e

# 2. Convert textures
d4-extract textures ./extracted ./textures --filter "*"

# 3. Parse strings
d4-extract strings ./extracted ./strings

# 4. Get game data from d4data
git clone https://github.com/DiabloTools/d4data.git
# JSON data available in d4data/json/
```

### Workflow 3: Using Pre-Parsed Data

If you just need game data without extraction:

```bash
# Clone the d4data repository
git clone https://github.com/DiabloTools/d4data.git

# Data is ready to use in:
# - d4data/json/         (structured game data)
# - d4data/definitions/  (game definitions)
# - d4data/names/        (hash lookups)
```

---

## API Reference

### Python API

```python
from d4_asset_extractor.casc import CASCExtractor, find_game_directory
from d4_asset_extractor.texture import TextureConverter
from d4_asset_extractor.strings import StringListParser
from d4_asset_extractor.search import SpriteIndex, search_sprites

# Auto-detect game installation
game_dir = find_game_directory()

# Extract textures
casc = CASCExtractor(game_dir)
if casc.is_valid():
    info = casc.get_info()
    print(f"Build: {info['build']}")

    tex_files = casc.extract_textures(filter_pattern="2DUI*")

# Convert textures
converter = TextureConverter(output_format="png", crop=True)
for tex in tex_files:
    converter.convert(tex, Path("./output"))

# Parse strings
parser = StringListParser()
result = parser.parse(Path("strings_enUS.stl"))
parser.save_json(result, Path("strings.json"))

# Search sprites
results = search_sprites(
    query_image=Path("screenshot.png"),
    sprites_dir=Path("./textures"),
    top_n=10
)
for r in results:
    print(f"{r.similarity_percent:.1f}% - {r.path.name}")
```

---

## Troubleshooting

### "CASCConsole.exe not found"

Download CASCExplorer from https://github.com/WoW-Tools/CASCExplorer/releases and place `CASCConsole.exe` in the `tools/` directory.

### "Could not find valid Diablo IV CASC data"

- Ensure Diablo IV is installed via Battle.net
- Check that the `Data/` directory exists with `data.*` files
- Try specifying the full path: `d4-extract info "C:\Program Files\Diablo IV"`

### "No texture files found"

- CASC extraction may be required first: `d4-extract casc <game_dir> ./extracted`
- Check your filter pattern matches actual texture names
- Try a broader filter: `--filter "*"`

### Texture conversion fails

- Some `.tex` files may use unsupported formats
- Install texconv for better format support
- Check if the `.tex` file is valid by opening in a hex editor (look for `DDS ` header)

### String parsing returns empty results

- The `.stl` format may have variations between game versions
- Try extracting fresh files from CASC
- Check file isn't corrupted (non-zero size)

---

## Contributing

Contributions welcome! Areas that need work:

1. **Better .tex format support** - Reverse engineering the full format
2. **More file format parsers** - .aff, .skl, SNO files
3. **Cross-platform CASC** - Pure Python CASC reading
4. **Test coverage** - Unit tests for parsers

---

## License

MIT License - see [LICENSE](LICENSE) for details.

**Disclaimer:** This tool is for educational and personal use. Game assets remain property of Blizzard Entertainment. Do not redistribute extracted assets.

---

## Credits

- [WoW-Tools/CASCExplorer](https://github.com/WoW-Tools/CASCExplorer) - CASC extraction
- [adainrivers/d4-texture-extractor](https://github.com/adainrivers/d4-texture-extractor) - Texture conversion reference
- [DiabloTools/d4data](https://github.com/DiabloTools/d4data) - Pre-parsed game data
- [Dakota628/d4parse](https://github.com/Dakota628/d4parse) - Data parsing tools
- [wowdev.wiki](https://wowdev.wiki/) - CASC documentation
- The Diablo modding community

---

## Quick Reference: All URLs

### Core Tools
- CASCExplorer: https://github.com/WoW-Tools/CASCExplorer
- CASCExplorer Releases: https://github.com/WoW-Tools/CASCExplorer/releases
- d4-texture-extractor: https://github.com/adainrivers/d4-texture-extractor
- d4data: https://github.com/DiabloTools/d4data
- d4parse: https://github.com/Dakota628/d4parse
- diablo4-data-harvest: https://github.com/mfloob/diablo4-data-harvest
- diablo-4-string-parser: https://github.com/alkhdaniel/diablo-4-string-parser

### Documentation
- CASC Format: https://wowdev.wiki/CASC
- TACT Protocol: https://wowdev.wiki/TACT
- TVFS: https://wowdev.wiki/TVFS
- d4parse Docs: https://docs.diablo.farm/
- Data Extraction Cheat Sheet: https://thunderysteak.github.io/wow-data-extract-cheat-sheet

### Community Databases
- Diablo4.gg: https://diablo4.gg/database/
- Maxroll D4: https://maxroll.gg/d4/
- Wowhead D4: https://www.wowhead.com/diablo-4/database
- Diablo4.cc: https://diablo4.cc/
- Lothrik Calculator: https://lothrik.github.io/diablo4-build-calc/database/
- Fextralife Wiki: https://diablo4.wiki.fextralife.com/

### GitHub Collections
- DiabloTools Organization: https://github.com/DiabloTools
- Awesome-D4: https://github.com/cagartner/awesome-d4
- GitHub Topic diablo4: https://github.com/topics/diablo4
- DiabloTools Releases: https://github.com/DiabloTools/Diablo4Tools-Releases

### Other Tools
- Maxroll Scraper: https://github.com/danparizher/maxroll-d4-scraper
- Inarius Discord Bot: https://github.com/ALCHElVlY/Inarius
- Ladik's CASC Viewer: https://www.hiveworkshop.com/threads/ladiks-casc-viewer.331540/
- cascette-rs: https://github.com/wowemulation-dev/cascette-rs
