# Architecture

Pure Python implementation for reading Diablo IV CASC files and extracting textures.
No external tools required.

## CASC Format Support

### Fully Supported

| Feature | Coverage | Notes |
|---------|----------|-------|
| `.build.info` parsing | 100% | Build configuration keys |
| Build config files | 100% | encoding, vfs-* keys |
| `.idx` file parsing | 100% | 780K+ file entries |
| Encoding file | 100% | 1.3M ckey→ekey mappings |
| BLTE `N` (plain) | 7.5% of files | Uncompressed data |
| BLTE `Z` (zlib) | 90.9% of files | Compressed data |
| VFS-2 manifest | 100% | 846K files (textures, payloads) |
| CoreTOC.dat | 100% | SNO ID→name mapping |

### Not Supported (Gracefully Handled)

| Feature | Coverage | Reason |
|---------|----------|--------|
| BLTE `E` (encrypted) | 0.8% of files | Requires Blizzard's encryption keys. Only affects `EncryptedNameDict-*.dat` files (name obfuscation), not actual game content. Returns `None` instead of crashing. |
| VFS 1, 3-38 | N/A | Language packs and regional content. VFS-2 contains all textures. |

### Not Used in D4

| Feature | Notes |
|---------|-------|
| BLTE `F` (frame) | Frame-based chunking for large files |
| BLTE `S` (ZSTD) | ZSTD compression (newer games) |
| CDN/Download manifests | Local install only |

## Texture Extraction Pipeline

### Success Rates

| Texture Category | Extraction Rate | Notes |
|------------------|-----------------|-------|
| 2DUI textures | ~68% | Primary extraction target |
| All textures | ~60-70% | Varies by category |

### Pipeline Breakdown (2DUI textures)

| Stage | Pass | Fail | Root Cause |
|-------|------|------|------------|
| Definition parsing | 62.4% | 37.6% | |
| ├─ No marker | | 22.0% | Different structure (metadata-only entries) |
| └─ Marker edge cases | | 15.6% | Marker at offset 0-4 or truncated |
| Format support | 100% | 0% | All 2DUI use supported formats |
| Payload availability | 99.9% | 0.1% | Very few missing payloads |
| PIL conversion | ~95% | ~5% | Partial/streaming data |

### Texture Definition Formats

The texture definition parser looks for a `0xFFFFFFFF` marker and parses relative to that position. Some textures use alternative structures:

1. **Standard format (62%)**: Has `0xFFFFFFFF` marker at offset 8+ with full metadata
2. **Metadata-only (22%)**: No marker, contains UV coords/colors for atlas references
3. **Edge cases (16%)**: Marker at unusual positions or truncated definitions

### Supported Texture Formats

| Format ID | DXGI Format | Notes |
|-----------|-------------|-------|
| 0, 45 | B8G8R8A8_UNORM | Uncompressed RGBA |
| 9, 10, 46, 47 | BC1_UNORM | DXT1 compression |
| 48 | BC2_UNORM | DXT3 compression |
| 12, 49 | BC3_UNORM | DXT5 compression |
| 41 | BC4_UNORM | Single channel |
| 42 | BC5_UNORM | Two channel (normal maps) |
| 43 | BC6H_SF16 | HDR compression |
| 44, 50 | BC7_UNORM | High quality compression |

### Unsupported Formats

| Format ID | DXGI Format | Reason |
|-----------|-------------|--------|
| 7, 23 | A8_UNORM | PIL doesn't support single-channel alpha |
| 25 | R16G16B16A16_FLOAT | 64-bit HDR (rare in 2DUI) |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI (cli.py)                         │
│         extract / list / info commands                      │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│              TextureExtractor (texture_extractor.py)        │
│  - Parses Texture-Base-Global.dat                           │
│  - Maps SNO IDs to texture definitions                      │
│  - Coordinates payload reading and conversion               │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                D4CASCReader (casc_reader.py)                │
│  - Reads .idx files (file table)                            │
│  - Parses encoding file (ckey→ekey mapping)                 │
│  - Reads data.XXX files with BLTE decompression             │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                 TVFSParser (tvfs_parser.py)                 │
│  - Parses VFS manifests (virtual file system)               │
│  - Maps file paths to encoded keys                          │
│  - Parses CoreTOC.dat for SNO names                         │
└─────────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `cli.py` | Command-line interface |
| `texture_extractor.py` | Texture extraction pipeline |
| `casc_reader.py` | Pure Python CASC reader |
| `tvfs_parser.py` | TVFS manifest parser |
| `tex_converter.py` | DDS/texture format handling |
| `bc_decoder.py` | BC1 (DXT1) block decoder |

## References

- [CASC Format (wowdev.wiki)](https://wowdev.wiki/CASC)
- [TVFS Format (wowdev.wiki)](https://wowdev.wiki/TVFS)
- [PyCASC (GitHub)](https://github.com/RaidAndFade/PyCASC)
- [CascLib (GitHub)](https://github.com/ladislav-zezula/CascLib)
