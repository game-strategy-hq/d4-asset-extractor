#!/usr/bin/env python3
"""
Debug script to verify texture extraction pipeline.

Dumps DDS files and metadata to verify each step of extraction.
"""

import struct
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from d4_asset_extractor.texture_extractor import (
    TextureExtractor,
    parse_texture_definition,
    TEXTURE_FORMATS,
    calculate_mip0_size,
)
from d4_asset_extractor.tex_converter import create_dds_header


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_extraction.py /path/to/diablo/iv [sno_id]")
        print("\nWithout sno_id, shows first 10 textures.")
        print("With sno_id, dumps detailed info and DDS file for that texture.")
        sys.exit(1)

    game_dir = Path(sys.argv[1])
    sno_id = int(sys.argv[2]) if len(sys.argv) > 2 else None

    print(f"Opening game at: {game_dir}")
    extractor = TextureExtractor(game_dir)
    print(f"Game version: {extractor.version}")
    print(f"Textures indexed: {len(extractor.texture_index):,}")
    print(f"Texconv available: {extractor.texconv_available}")
    print()

    if sno_id is None:
        # List first 10 textures
        textures = extractor.list_textures()[:10]
        print("First 10 textures:")
        for sno, name in textures:
            info = extractor.get_texture_info(sno)
            if info:
                fmt = TEXTURE_FORMATS.get(info.format_id, {})
                dxgi = fmt.get("dxgi", "UNKNOWN")
                print(f"  {sno:>10}: {name}")
                print(f"             {info.width}x{info.height} format={info.format_id} ({dxgi})")
        return

    # Detailed dump for specific SNO
    print(f"=== SNO {sno_id} ===")

    name = extractor.get_texture_name(sno_id)
    print(f"Name: {name}")

    if sno_id not in extractor.texture_index:
        print("ERROR: SNO not found in texture index")
        return

    # Get raw definition data
    def_offset, def_size = extractor.texture_index[sno_id]
    print(f"Definition offset: {def_offset}, size: {def_size}")

    definition_data = extractor._tex_base_data[def_offset : def_offset + def_size]
    print(f"Definition data bytes: {len(definition_data)}")
    print(f"First 64 bytes (hex):")
    for i in range(0, min(64, len(definition_data)), 16):
        hex_str = ' '.join(f'{b:02x}' for b in definition_data[i:i+16])
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in definition_data[i:i+16])
        print(f"  {i:04x}: {hex_str}  {ascii_str}")

    # Parse definition
    info = parse_texture_definition(definition_data, sno_id)
    if not info:
        print("ERROR: Failed to parse texture definition")
        return

    print()
    print(f"Parsed info:")
    print(f"  format_id: {info.format_id}")
    print(f"  width: {info.width}")
    print(f"  height: {info.height}")
    print(f"  depth: {info.depth}")
    print(f"  face_count: {info.face_count}")
    print(f"  mipmap_min: {info.mipmap_min}")
    print(f"  mipmap_max: {info.mipmap_max}")
    print(f"  avg_color: {info.avg_color}")

    fmt = TEXTURE_FORMATS.get(info.format_id, {})
    print(f"  DXGI format: {fmt.get('dxgi', 'UNKNOWN')}")
    print(f"  DXGI index: {fmt.get('dxgi_index', '?')}")
    print(f"  Alignment: {fmt.get('alignment', '?')}")

    # Calculate expected size
    mip0_size = calculate_mip0_size(info.width, info.height, info.format_id)
    print(f"  Expected mip0 size: {mip0_size:,} bytes")

    # Get payload
    payload_sno_id = extractor.get_payload_sno_id(sno_id)
    print()
    print(f"Payload SNO ID: {payload_sno_id}" + (" (redirected)" if payload_sno_id != sno_id else ""))

    if payload_sno_id not in extractor._payload_ekeys:
        print("ERROR: Payload not found in VFS")
        return

    entry = extractor._payload_ekeys[payload_sno_id]
    print(f"Payload VFS entry: ekey={entry.ekey.hex()}")

    payload_data = extractor._read_vfs_entry(entry)
    if not payload_data:
        print("ERROR: Failed to read payload data")
        return

    print(f"Payload data size: {len(payload_data):,} bytes")
    print(f"Size ratio (actual/expected): {len(payload_data) / mip0_size:.2f}x" if mip0_size > 0 else "N/A")

    print(f"\nFirst 64 bytes of payload (hex):")
    for i in range(0, min(64, len(payload_data)), 16):
        hex_str = ' '.join(f'{b:02x}' for b in payload_data[i:i+16])
        print(f"  {i:04x}: {hex_str}")

    # Check for common patterns
    if len(payload_data) >= 4:
        first_4 = struct.unpack("<I", payload_data[:4])[0]
        if first_4 == 0x20534444:  # "DDS "
            print("\n*** WARNING: Payload already has DDS header! ***")

    # Create DDS header
    dds_header = create_dds_header(info.width, info.height, info.format_id, len(payload_data))
    print(f"\nDDS header size: {len(dds_header)} bytes")

    # Check header structure
    print(f"DDS header dump:")
    for i in range(0, len(dds_header), 16):
        hex_str = ' '.join(f'{b:02x}' for b in dds_header[i:i+16])
        print(f"  {i:04x}: {hex_str}")

    # Write DDS file
    dds_data = dds_header + payload_data
    output_path = Path(f"/tmp/debug_{sno_id}.dds")
    output_path.write_bytes(dds_data)
    print(f"\nWrote DDS to: {output_path}")
    print(f"Total DDS size: {len(dds_data):,} bytes")

    # Try to extract image
    print("\nAttempting image extraction...")
    try:
        img = extractor.extract_texture(sno_id)
        if img:
            png_path = Path(f"/tmp/debug_{sno_id}.png")
            img.save(png_path)
            print(f"SUCCESS: Saved to {png_path}")
            print(f"Image size: {img.width}x{img.height}")
            print(f"Image mode: {img.mode}")
        else:
            print("FAILED: extract_texture returned None")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
