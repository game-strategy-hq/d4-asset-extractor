# Diablo IV Asset Extractor

Pure Python tool for extracting textures from Diablo IV game files. No external tools required.

## Quick Start

```bash
# Install
uv tool install git+https://github.com/game-strategy-hq/d4-asset-extractor

# Extract UI textures
d4-extract extract "/path/to/Diablo IV"

# Extract with different filter
d4-extract extract "/path/to/Diablo IV" --filter "Items*"

# Slice texture atlases into individual icons
d4-extract icons "/path/to/Diablo IV"

# List available textures
d4-extract list "/path/to/Diablo IV" --filter "*"

# Show game version info
d4-extract info "/path/to/Diablo IV"
```

**Output:**
```
d4-data/
├── textures/     # Full texture sheets as PNG
├── icons/        # Individual icons sliced from atlases
└── version.txt   # Game version extracted from
```

**Game paths:**
- Windows: `C:\Program Files (x86)\Diablo IV`
- macOS: `/Applications/Diablo IV`

---

## How It Works

Understanding the extraction pipeline helps contributors navigate the codebase and avoid past pitfalls.

### The CASC Storage System

Diablo IV uses Blizzard's **CASC** (Content Addressable Storage Container) system. Unlike traditional file systems, CASC is content-addressed: files are identified by cryptographic hashes of their contents, not by paths.

```
Diablo IV/Data/
├── .build.info          # Build metadata, points to config files
├── config/              # Build configs with encoding keys
├── data/
│   ├── data.000-0XX     # Archive files containing actual data
│   └── *.idx            # Index files mapping keys to archive locations
└── indices/             # Additional index journals
```

**Key concepts:**

| Term | Description |
|------|-------------|
| **Content Key (ckey)** | Hash of file contents. Same content = same ckey, even across versions. |
| **Encoded Key (ekey)** | Hash of the encoded/compressed data. Used to locate data in archives. |
| **Encoding file** | Maps ckeys to ekeys. "I have content X, where's the compressed version?" |
| **BLTE** | Blizzard's container format. Handles compression (zlib) and chunking. |
| **TVFS** | Virtual file system. Maps human paths (`base/payload/123456.tex`) to ckeys. |

**Our pipeline:**

```
.build.info → config files → encoding file → .idx files → data.XXX archives
                                   ↓
                            TVFS manifest
                                   ↓
                         path → ckey → ekey → archive location → BLTE decompress
```

### Texture Storage

D4 textures are split across two systems:

1. **Texture definitions** (`Texture-Base-Global.dat`) - Metadata: dimensions, format, mip count
2. **Texture payloads** (`base/payload/<sno_id>.tex`) - Raw pixel data in DDS-compatible formats

The definition contains a `0xFFFFFFFF` marker followed by structured metadata. The payload is raw BC1/BC3/BC7/etc compressed blocks that can be wrapped in a DDS header and decoded.

**Texture formats we handle:**

| Format | DXGI Name | Description |
|--------|-----------|-------------|
| BC1 | DXT1 | 4:1 compression, 1-bit alpha |
| BC3 | DXT5 | 4:1 compression, smooth alpha |
| BC4 | ATI1 | Single channel (grayscale) |
| BC5 | ATI2 | Two channel (normal maps) |
| BC6H | - | HDR compression |
| BC7 | - | High quality, variable compression |
| RGBA | B8G8R8A8 | Uncompressed 32-bit |

---

## Known Limitations

### BC1 Interleaved Textures

**Problem:** Some BC1 textures use a proprietary interleaved format that no public tool can decode.

These textures store data with alternating 8-byte blocks:
```
Block 0: DATA (actual BC1 block)
Block 1: ZERO (8 null bytes)
Block 2: DATA
Block 3: ZERO
...
```

When a decoder reads expected size based on dimensions, it gets ~50% zero blocks mixed in, producing corrupted rainbow-stripe output.

**What we do:** Detect >30% zero blocks and raise `InterleavedBC1Error` with a clear message instead of producing garbage.

**Affected textures:** Primarily `2DInventory_Bundle_*` textures. Most `2DUI*` textures extract fine.

**We investigated every public D4 project:**
- `d4-texture-extractor` - Fails (README acknowledges "some DDS files might not be valid")
- `d4Tex` (Noesis plugin) - Uses standard decoder, no special handling
- `d4parse` - Uploads raw data to GPU, no preprocessing

**Conclusion:** This appears to be a proprietary D4 format with no public solution. If you solve this, please contribute!

### Texture Definition Variants

Not all entries in `Texture-Base-Global.dat` are actual textures:
- **62%** have the `0xFFFFFFFF` marker with full metadata (these work)
- **22%** are metadata-only entries (atlas UV coordinates, no pixels)
- **16%** have the marker at unusual offsets or are truncated

Current extraction rate for `2DUI*` textures is ~68%.

### Encrypted Files

~0.8% of CASC files use `E` (encrypted) BLTE encoding. These are exclusively `EncryptedNameDict-*.dat` files used for path obfuscation. No actual game content is affected. We return `None` for these files.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI (cli.py)                            │
│              extract / list / info / icons                      │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│               TextureExtractor (texture_extractor.py)           │
│  • Loads Texture-Base-Global.dat definitions                    │
│  • Maps SNO IDs to texture metadata                             │
│  • Coordinates payload reading + image conversion               │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                 D4CASCReader (casc_reader.py)                   │
│  • Parses .build.info and config files                          │
│  • Reads .idx files (780K+ entries)                             │
│  • Parses encoding file (1.3M ckey→ekey mappings)               │
│  • Reads data.XXX with BLTE decompression                       │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                  TVFSParser (tvfs_parser.py)                    │
│  • Parses VFS-2 manifest (846K virtual files)                   │
│  • Maps paths like base/payload/123.tex to content keys         │
│  • Parses CoreTOC.dat for SNO ID → human name mapping           │
└─────────────────────────────────────────────────────────────────┘
```

**Supporting modules:**

| File | Purpose |
|------|---------|
| `tex_converter.py` | DDS header creation, format mapping, PIL conversion |
| `bc_decoder.py` | Pure Python BC1 decoder (based on DirectXTex) |

### Why Pure Python?

Previous approaches used external tools:
- `CASCConsole.exe` - Windows-only, requires .NET
- `texconv.exe` - Windows-only, can't handle D4's BC1 interleaving anyway

Pure Python means:
- Cross-platform (Windows, macOS, Linux)
- Single `uv tool install` with no system dependencies
- Full control over edge case handling

---

## Development

```bash
git clone https://github.com/game-strategy-hq/d4-asset-extractor
cd d4-asset-extractor
uv sync
uv run d4-extract info "/path/to/Diablo IV"
```

### Project Structure

```
src/d4_asset_extractor/
├── cli.py                # Typer CLI commands
├── texture_extractor.py  # High-level extraction API
├── casc_reader.py        # CASC archive reading
├── tvfs_parser.py        # Virtual filesystem parsing
├── tex_converter.py      # DDS/texture format handling
└── bc_decoder.py         # BC1 block decompression
```

### Key Files in D4 Install

```
Data/
├── .build.info                    # Start here: build config pointers
├── config/<hash>                  # Build config with encoding/vfs keys
├── data/
│   ├── 0000000000000000.idx      # File index (ekey → archive location)
│   └── data.000-0XX              # Data archives
└── Texture-Base-Global.dat        # Texture definitions (via TVFS)
```

---

## Resources

For deeper understanding, see [RESOURCES.md](RESOURCES.md) which catalogs all reference materials:

- [CASC Format Spec](https://wowdev.wiki/CASC) - Authoritative format documentation
- [TVFS Documentation](https://wowdev.wiki/TVFS) - Virtual filesystem layer
- [d4-texture-extractor](https://github.com/adainrivers/d4-texture-extractor) - Reference implementation (Node.js)
- [DirectXTex](https://github.com/microsoft/DirectXTex) - BC decoder reference

---

## License

MIT. Game assets remain property of Blizzard Entertainment.
