#!/usr/bin/env python3
"""
Build test fixtures by finding one texture per format type.

This script scans the game files and extracts one representative texture
for each eTexFormat value, creating a minimal test set for fast iteration.

Usage:
    python scripts/build_test_fixtures.py /path/to/diablo/iv

Output:
    tests/fixtures/textures/<format_id>_<name>.tex.meta
    tests/fixtures/textures/<format_id>_<name>.tex.payload
    tests/fixtures/manifest.json
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from d4_asset_extractor.texture_extractor import TextureExtractor
from d4_asset_extractor.texture_definition import TEX_DEF, read_texture_definition
from d4_asset_extractor.tex_converter import TEXTURE_FORMATS


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/build_test_fixtures.py /path/to/diablo/iv")
        sys.exit(1)

    game_dir = Path(sys.argv[1])
    if not game_dir.exists():
        print(f"Error: Game directory not found: {game_dir}")
        sys.exit(1)

    fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures" / "textures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    print(f"Game directory: {game_dir}")
    print(f"Fixtures directory: {fixtures_dir}")
    print()

    # Load extractor
    print("Loading game data...")
    extractor = TextureExtractor(game_dir)
    print(f"  Found {len(extractor.list_textures('*')):,} textures")
    print()

    # Track textures by format - only those with actual payload data
    formats_found: dict[int, list[tuple[int, str, int, int]]] = defaultdict(list)
    formats_needed = set(TEXTURE_FORMATS.keys())

    print("Scanning textures by format (checking for payload availability)...")
    all_textures = extractor.list_textures("*")

    for sno_id, name in all_textures:
        try:
            # Get texture info
            info = extractor.get_texture_info(sno_id)
            if not info:
                continue

            format_id = info.format_id
            if format_id not in formats_needed:
                continue

            # Check if payload actually exists
            payload_sno_id = extractor.get_payload_sno_id(sno_id)
            if payload_sno_id not in extractor._payload_ekeys:
                continue

            formats_found[format_id].append((sno_id, name, info.width, info.height))

        except Exception:
            continue

    print(f"  Found textures with payloads for {len(formats_found)}/{len(formats_needed)} formats")

    # Report missing formats
    missing = formats_needed - set(formats_found.keys())
    if missing:
        print(f"  Missing formats (no payloads found): {sorted(missing)}")
    print()

    # Select best candidate per format
    # Prefer: 1) 2DUI textures (most reliable), 2) smaller size (faster tests)
    manifest = {
        "description": "Test fixtures - one texture per eTexFormat",
        "source": str(game_dir),
        "version": extractor.version,
        "textures": []
    }

    print("Extracting fixtures...")
    for format_id in sorted(formats_needed):
        if format_id not in formats_found:
            print(f"  [MISSING] Format {format_id}: {TEXTURE_FORMATS[format_id]['dxgi']}")
            continue

        # Pick best texture:
        # 1. Prefer 2DUI* textures (most reliable, always have valid data)
        # 2. Then by size (smaller = faster tests)
        candidates = formats_found[format_id]
        ui_candidates = [c for c in candidates if c[1].startswith("2DUI")]
        if ui_candidates:
            candidates = ui_candidates

        candidates.sort(key=lambda x: x[2] * x[3])  # Sort by pixel count
        sno_id, name, width, height = candidates[0]

        # Extract raw data
        try:
            # Read definition (meta) data
            if sno_id not in extractor.texture_index:
                print(f"  [SKIP] Format {format_id}: {name} (no index)")
                continue

            def_offset, def_size = extractor.texture_index[sno_id]
            meta_data = extractor._tex_base_data[def_offset:def_offset + def_size]

            # Read payload data
            payload_sno_id = extractor.get_payload_sno_id(sno_id)
            if payload_sno_id not in extractor._payload_ekeys:
                print(f"  [SKIP] Format {format_id}: {name} (no payload)")
                continue

            payload_data = extractor._read_vfs_entry(extractor._payload_ekeys[payload_sno_id])

            if not meta_data or not payload_data:
                print(f"  [SKIP] Format {format_id}: {name} (no data)")
                continue

            # Save fixture
            safe_name = name.replace("/", "_").replace("\\", "_")
            meta_path = fixtures_dir / f"{format_id:02d}_{safe_name}.meta"
            payload_path = fixtures_dir / f"{format_id:02d}_{safe_name}.payload"

            meta_path.write_bytes(meta_data)
            payload_path.write_bytes(payload_data)

            format_info = TEXTURE_FORMATS[format_id]
            manifest["textures"].append({
                "format_id": format_id,
                "dxgi": format_info["dxgi"],
                "dxgi_index": format_info["dxgi_index"],
                "name": name,
                "sno_id": sno_id,
                "width": width,
                "height": height,
                "meta_file": meta_path.name,
                "payload_file": payload_path.name,
                "meta_size": len(meta_data),
                "payload_size": len(payload_data),
            })

            print(f"  [OK] Format {format_id:2d}: {name} ({width}x{height}) - {format_info['dxgi']}")

        except Exception as e:
            print(f"  [ERROR] Format {format_id}: {name} - {e}")

    # Save manifest
    manifest_path = fixtures_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print()
    print(f"Saved {len(manifest['textures'])} fixtures to {fixtures_dir}")
    print(f"Manifest: {manifest_path}")

    # Summary
    print()
    print("Coverage summary:")
    print(f"  Formats with fixtures: {len(manifest['textures'])}/{len(formats_needed)}")
    missing = formats_needed - set(t["format_id"] for t in manifest["textures"])
    if missing:
        print(f"  Missing formats: {sorted(missing)}")


if __name__ == "__main__":
    main()
