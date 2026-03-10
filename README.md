# Diablo IV Asset Extractor

Extract textures from Diablo IV game files. Cross-platform (Windows, macOS, Linux).

## Requirements

- Python 3.11+
- **texconv.exe** - Microsoft's DirectX texture converter
  - Windows: Download from [DirectXTex releases](https://github.com/Microsoft/DirectXTex/releases), place in `./tools/`
  - macOS: Install [Whisky](https://getwhisky.app), place `texconv.exe` in `./tools/`

## Installation

```bash
# Install with uv
uv tool install git+https://github.com/game-strategy-hq/d4-asset-extractor

# Or clone and install locally
git clone https://github.com/game-strategy-hq/d4-asset-extractor
cd d4-asset-extractor
uv sync
```

## Usage

```bash
# Extract UI textures (default filter: 2DUI*)
d4-extract extract "/path/to/Diablo IV"

# Extract with different filter
d4-extract extract "/path/to/Diablo IV" --filter "Items*"

# Extract all textures (slow, 116K+ textures)
d4-extract extract "/path/to/Diablo IV" --filter "*"

# Slice texture atlases into individual icons
d4-extract icons "/path/to/Diablo IV"

# List available textures
d4-extract list "/path/to/Diablo IV" --filter "*" --limit 100

# Show game version info
d4-extract info "/path/to/Diablo IV"
```

### Game Paths

| Platform | Default Path |
|----------|--------------|
| Windows | `C:\Program Files (x86)\Diablo IV` |
| macOS | `/Applications/Diablo IV` |

### Output

```
output/
├── textures/     # Full texture sheets (PNG)
├── icons/        # Individual icons sliced from atlases
└── version.txt   # Game version info
```

## CLI Options

```bash
d4-extract extract <game_dir> [OPTIONS]
  --filter, -f    Filter pattern (default: "2DUI*")
  --limit, -l     Limit textures to extract
  --verbose, -V   Show detailed output
  --no-texconv    Disable texconv (not recommended)

d4-extract icons <game_dir> [OPTIONS]
  --filter, -f    Filter pattern for atlases
  --min-size      Minimum icon dimension (default: 16)
  --max-size      Maximum icon dimension (default: 256)
  --limit, -l     Limit atlases to process
  --verbose, -V   Show detailed output

d4-extract list <game_dir> [OPTIONS]
  --filter, -f    Filter pattern
  --limit, -l     Max textures to show (default: 50)

d4-extract info <game_dir>
  # Shows game version, build ID, file counts
```

## Development

```bash
git clone https://github.com/game-strategy-hq/d4-asset-extractor
cd d4-asset-extractor
uv sync
uv run d4-extract info "/path/to/Diablo IV"

# Run tests
uv run pytest
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - Technical overview and module descriptions
- [CASC Pipeline](docs/CASC-PIPELINE.md) - Deep dive into CASC extraction process
- [Resources](docs/RESOURCES.md) - Reference links and external resources

## Known Limitations

- **Encrypted files (~0.8%)**: `EncryptedNameDict-*.dat` files cannot be read. These are path obfuscation files, not actual game content.
- **texconv required**: All texture formats require texconv for correct decoding.

## License

MIT. Game assets remain property of Blizzard Entertainment.
