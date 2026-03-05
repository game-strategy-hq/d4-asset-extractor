# D4 Asset Extractor - CASC Rewrite Progress

## Goal
Rewrite the extractor to read D4 CASC files directly in Python, eliminating the dependency on CASCConsole.exe (Windows-only, legacy release, unreliable).

## Current Status: Research Complete, Implementation In Progress

---

## What We Learned

### D4 CASC Structure

The D4 installation has this structure:
```
Diablo IV/
├── .build.info          # Build metadata (version, keys)
├── Data/
│   ├── config/
│   │   ├── 23/b9/23b9...  # Build config (encoding, vfs-root, etc.)
│   │   └── 2e/29/2e29...  # CDN config (archive list)
│   ├── data/
│   │   ├── *.idx          # Index files (780k+ file entries)
│   │   └── data.000-049   # Data files (~72GB total)
│   ├── fenris/            # Product-specific indices
│   ├── indices/           # Archive indices (221MB)
│   └── ecache/            # Empty cache
```

### Key Discovery: D4 Uses TVFS, Not Traditional Root

Unlike older Blizzard games, D4 uses:
- `root = 00000000...` (empty/unused)
- `vfs-root` and `vfs-2` through `vfs-38` for Virtual File System

The VFS contains 846,014 files with paths like:
- `meta/{sno_id}` - Texture metadata (format, dimensions)
- `payload/{sno_id}` - Texture pixel data
- `CoreTOC.dat` - SNO ID to name mappings

### SNO (Scene Node Object) System

D4 uses numeric SNO IDs instead of file paths:
- **SNO Group 44** = Textures
- CoreTOC.dat contains 684,497 SNO entries
- 118,938 are texture SNOs
- 4,119 are 2DUI textures (icons, UI elements)

Example mapping:
- SNO ID 2926 → "2DUIBreathMeter"
- Files: `meta/2926` + `payload/2926`

---

## Working Code

### PyCASC Integration (Partially Working)

We can read CASC data using PyCASC's low-level functions:
```python
from PyCASC import r_idx
from PyCASC.utils.CASCUtils import parse_encoding_file, r_cascfile

# Build file table from .idx files
file_table = {}
for idx_file in data_path.glob("*.idx"):
    ents = r_idx(str(idx_file))
    for e in ents:
        file_table[e.ekey] = e

# Read encoding file
enc_file = r_cascfile(data_path, enc_info.data_file, enc_info.offset)
ckey_map = parse_encoding_file(enc_file)  # 1.3M entries
```

### TVFS Parser (Working)

Our `tvfs_parser.py` successfully parses TVFS manifests:
```python
from d4_asset_extractor.tvfs_parser import parse_tvfs_files, parse_core_toc

# Parse VFS-2 (main content, 53MB)
files = parse_tvfs_files(vfs2_data)  # Returns 846,014 files

# Parse CoreTOC.dat for SNO names
sno_dict = parse_core_toc(coretoc_data)  # Returns 684,497 entries
textures = [(k, v) for k, v in sno_dict.items() if v.group_id == 44]
```

### Texture Converter (Working)

Our `tex_converter.py` handles D4 texture format:
```python
from d4_asset_extractor.tex_converter import (
    read_texture_definition,  # Parse meta file
    convert_raw_to_dds,       # Create DDS from payload
    dds_to_image,             # DDS to PIL (uses texconv for BC7)
)
```

---

## Remaining Work

### 1. Fix SNO ID Lookup in VFS

Current issue: SNO IDs from CoreTOC don't directly match VFS paths.
- CoreTOC says SNO 2926 = "2DUIBreathMeter"
- VFS has `meta/1000006`, `meta/1000009`, etc. (not `meta/2926`)

**Theory**: The VFS paths may use a different numbering scheme or the texture SNOs are in a different VFS manifest (vfs-33 is labeled for textures in the build config).

### 2. Implement Full Extraction Pipeline

```python
def extract_texture(sno_id: int, output_dir: Path):
    # 1. Look up SNO name from CoreTOC
    name = sno_dict[sno_id].name

    # 2. Find meta and payload in VFS
    meta_entry = vfs_files[f"meta/{sno_id}"]
    payload_entry = vfs_files[f"payload/{sno_id}"]

    # 3. Read from CASC data files
    meta_data = read_casc_file(meta_entry.ekey)
    payload_data = read_casc_file(payload_entry.ekey)

    # 4. Convert to image
    definition = read_texture_definition(meta_data)
    dds_data = convert_raw_to_dds(payload_data, definition)
    image = dds_to_image(dds_data)

    # 5. Save
    image.save(output_dir / f"{name}.png")
```

### 3. Handle Different VFS Manifests

The build config has multiple VFS files:
- `vfs-root` (12KB) - Root manifest
- `vfs-2` (53MB) - Main content (CoreTOC, StringLists, etc.)
- `vfs-33` (4MB) - Possibly textures?

Need to investigate which VFS contains the actual texture SNO references.

### 4. Remove texconv.exe Dependency (Optional)

Currently using texconv.exe for BC7/BC6H formats. Could implement pure Python BC7 decoder, but this is lower priority.

---

## File Reference

### Key Files in Project

| File | Purpose |
|------|---------|
| `src/d4_asset_extractor/tvfs_parser.py` | TVFS manifest parser |
| `src/d4_asset_extractor/tex_converter.py` | Texture format converter |
| `src/d4_asset_extractor/casc.py` | CASC extractor (currently uses CASCConsole) |

### External Dependencies Used for Research

| Dependency | Purpose |
|------------|---------|
| PyCASC (`/tmp/PyCASC`) | Low-level CASC reading functions |
| D4 Install (`D4-install/`) | Local copy of game files for testing |

---

## Test Commands

```bash
# Test TVFS parsing
uv run python -c "
from d4_asset_extractor.tvfs_parser import parse_tvfs_files
# ... (see examples above)
"

# Test texture conversion (once extraction works)
uv run d4-extract textures ./D4-install/Diablo\ IV ./icons --filter '2DUI*'
```

---

## References

- [CASC Format (wowdev.wiki)](https://wowdev.wiki/CASC)
- [TVFS Format (wowdev.wiki)](https://wowdev.wiki/TVFS)
- [PyCASC (GitHub)](https://github.com/RaidAndFade/PyCASC)
- [CascLib (GitHub)](https://github.com/ladislav-zezula/CascLib)
- [d4-texture-extractor (Reference)](https://github.com/adainrivers/d4-texture-extractor)

---

## Next Steps

1. **Investigate VFS-33** - Check if texture SNOs are stored there
2. **Map SNO IDs to VFS paths** - Figure out the numbering scheme
3. **Create unified CASC reader** - Combine PyCASC functions into our own module
4. **End-to-end test** - Extract one texture completely without CASCConsole
