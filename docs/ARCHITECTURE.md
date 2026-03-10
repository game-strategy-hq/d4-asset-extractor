# Architecture

Technical overview of the D4 Asset Extractor.

## Overview

This tool extracts textures from Diablo IV's CASC storage system. The pipeline:

1. **CASC Reader** - Reads Blizzard's content-addressed archive format
2. **TVFS Parser** - Navigates the virtual filesystem to find texture files
3. **Texture Extractor** - Coordinates metadata parsing and payload reading
4. **texconv** - Decodes GPU-compressed textures to standard images

## Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI (cli.py)                            │
│              extract / list / info / icons                      │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│               TextureExtractor (texture_extractor.py)           │
│  • Loads Texture-Base-Global.dat (116K+ texture definitions)    │
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
│  • Maps paths like base/payload/Texture/123.tex to content keys │
│  • Parses CoreTOC.dat for SNO ID → human name mapping           │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                  TexconvWrapper (texconv.py)                    │
│  • Wraps texconv.exe for DDS → PNG conversion                   │
│  • Auto-discovers Whisky on macOS for Wine execution            │
│  • Handles all BC1-BC7 and uncompressed formats                 │
└─────────────────────────────────────────────────────────────────┘
```

## Modules

| Module | Lines | Purpose |
|--------|-------|---------|
| `cli.py` | ~410 | Typer CLI with `extract`, `list`, `info`, `icons` commands |
| `texture_extractor.py` | ~700 | High-level extraction API, coordinates all components |
| `casc_reader.py` | ~350 | Pure Python CASC reader with BLTE decompression |
| `tvfs_parser.py` | ~350 | Virtual filesystem and CoreTOC parsing |
| `tex_converter.py` | ~350 | DDS header construction, format mapping |
| `texconv.py` | ~320 | texconv.exe wrapper with Whisky/Wine support |
| `texture_definition.py` | ~240 | Texture metadata struct parsing (d4data offsets) |

## Key Concepts

### CASC Storage

Diablo IV uses Blizzard's **CASC** (Content Addressable Storage Container) format:

```
Diablo IV/Data/
├── .build.info          # Build metadata, points to config files
├── config/              # Build configs with encoding keys
├── data/
│   ├── data.000-0XX     # Archive files containing actual data
│   └── *.idx            # Index files mapping keys to archive locations
└── indices/             # Additional index journals
```

| Term | Description |
|------|-------------|
| **Content Key (ckey)** | Hash of file contents |
| **Encoded Key (ekey)** | Hash of encoded/compressed data |
| **Encoding file** | Maps ckeys to ekeys |
| **BLTE** | Blizzard's container format with zlib compression |
| **TVFS** | Virtual filesystem mapping paths to content keys |

### Texture Storage

Textures are stored as two components:

```
TVFS Virtual Paths:
├── base/Texture-Base-Global.dat       # Combined metadata (116K+ definitions)
└── base/payload/Texture/<sno_id>.tex  # Raw pixel data (BC-compressed)
```

### Texture Formats

| Format ID | DXGI Format | Description |
|-----------|-------------|-------------|
| 0, 45 | B8G8R8A8_UNORM | Uncompressed RGBA |
| 9, 10, 46, 47 | BC1_UNORM | DXT1 (4:1 compression) |
| 48 | BC2_UNORM | DXT3 |
| 12, 49 | BC3_UNORM | DXT5 |
| 41 | BC4_UNORM | Single channel |
| 42 | BC5_UNORM | Two channel (normal maps) |
| 43, 51 | BC6H | HDR compression |
| 44, 50 | BC7_UNORM | High quality |
| 7, 23 | A8_UNORM | Alpha only |
| 25 | R16G16B16A16_FLOAT | HDR float |

## CASC Format Coverage

### Supported

| Feature | Coverage | Notes |
|---------|----------|-------|
| `.build.info` parsing | 100% | Build configuration keys |
| Build config files | 100% | encoding, vfs-* keys |
| `.idx` file parsing | 100% | 780K+ file entries |
| Encoding file | 100% | 1.3M ckey→ekey mappings |
| BLTE `N` (plain) | 7.5% | Uncompressed data |
| BLTE `Z` (zlib) | 90.9% | Compressed data |
| VFS-2 manifest | 100% | 846K files |
| CoreTOC.dat | 100% | SNO ID→name mapping |

### Not Supported

| Feature | Coverage | Reason |
|---------|----------|--------|
| BLTE `E` (encrypted) | 0.8% | Requires Blizzard's keys. Only `EncryptedNameDict-*.dat` files. |

## Dependencies

| Package | Purpose |
|---------|---------|
| `numpy` | Array operations for image data |
| `pillow` | PNG output |
| `pydds` | DDS format utilities |
| `rich` | CLI progress bars |
| `typer` | CLI framework |

### External Tools

| Tool | Platform | Purpose |
|------|----------|---------|
| `texconv.exe` | Windows / Wine | BC texture decoding (required) |
| Whisky | macOS | Wine wrapper for texconv |

## Testing

```bash
# Run all tests
uv run pytest

# Tests verify:
# - Texture definition parsing against d4data reference (100 textures)
# - Format coverage across all supported DXGI formats
```

Test fixtures in `tests/fixtures/textures/` contain sample metadata and payloads for each format type.
