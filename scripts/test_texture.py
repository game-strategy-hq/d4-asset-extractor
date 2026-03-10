#!/usr/bin/env python3
"""
Test script for debugging individual texture extraction.

Usage:
    uv run scripts/test_texture.py "2DUI_Bundle_HArmor_bar_stor162_WebImage"
    uv run scripts/test_texture.py "2DUI_Bundle_Companion_stor002_background"
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from d4_asset_extractor.texture_extractor import TextureExtractor, InterleavedBC1Error
from d4_asset_extractor.tex_converter import TEXTURE_FORMATS, calculate_mip0_size


def analyze_texture(extractor: TextureExtractor, name: str) -> None:
    """Analyze a single texture and print diagnostic info."""

    # Find the texture
    textures = extractor.list_textures(f"{name}*")
    if not textures:
        textures = extractor.list_textures(f"*{name}*")

    if not textures:
        print(f"No texture found matching: {name}")
        return

    sno_id, full_name = textures[0]
    print(f"Found: {full_name} (SNO ID: {sno_id})")
    print("-" * 60)

    # Get texture info
    info = extractor.get_texture_info(sno_id)
    if not info:
        print("ERROR: Could not parse texture definition")
        return

    print(f"Dimensions: {info.width} x {info.height}")
    print(f"Depth: {info.depth}, Faces: {info.face_count}")
    print(f"Format ID: {info.format_id}")

    fmt = TEXTURE_FORMATS.get(info.format_id)
    if fmt:
        print(f"Format: {fmt['dxgi']}")
        print(f"DXGI index: {fmt['dxgi_index']}, Alignment: {fmt['alignment']}")
    else:
        print(f"Format: UNKNOWN (ID {info.format_id})")

    print(f"Mip range: {info.mipmap_min}-{info.mipmap_max}")
    print(f"Avg color: {info.avg_color}")
    print()

    # Try to read the payload via the extractor
    if sno_id not in extractor._payload_ekeys:
        print("ERROR: No payload ekey found for this texture")
        return

    payload = extractor._read_vfs_entry(extractor._payload_ekeys[sno_id])
    if payload is None:
        print("ERROR: Could not read payload data")
        return

    print(f"Payload size: {len(payload):,} bytes")

    # Calculate expected size
    mip0_size = calculate_mip0_size(info.width, info.height, info.format_id)
    print(f"Expected mip0 size: {mip0_size:,} bytes")
    print(f"Payload ratio: {len(payload) / mip0_size:.2f}x")

    # Analyze payload content
    zero_blocks = 0
    total_blocks = len(payload) // 8
    for i in range(0, len(payload) - 7, 8):
        if payload[i:i+8] == b'\x00' * 8:
            zero_blocks += 1

    zero_ratio = zero_blocks / total_blocks if total_blocks > 0 else 0
    print(f"Zero blocks: {zero_blocks}/{total_blocks} ({zero_ratio:.1%})")

    # Check for interleaving pattern
    if total_blocks >= 10:
        interleaved = True
        for i in range(0, min(20, total_blocks), 2):
            block_offset = i * 8
            if i % 2 == 1:  # Odd blocks should be zero if interleaved
                if payload[block_offset:block_offset+8] != b'\x00' * 8:
                    interleaved = False
                    break
        if interleaved and zero_ratio > 0.3:
            print("Pattern: INTERLEAVED (alternating data/zero blocks)")
        else:
            print("Pattern: Normal")

    # Show first few bytes
    print(f"\nFirst 64 bytes (hex):")
    for i in range(0, min(64, len(payload)), 16):
        hex_str = ' '.join(f'{b:02x}' for b in payload[i:i+16])
        print(f"  {i:04x}: {hex_str}")

    print()

    # Try extraction
    print("Attempting extraction...")
    output_path = Path(f"/tmp/test_{full_name}.png")

    try:
        result = extractor.extract_texture_to_file(sno_id, output_path)
        if result:
            print(f"SUCCESS: {output_path}")
            print(f"File size: {output_path.stat().st_size:,} bytes")
        else:
            print("FAILED: extract_texture_to_file returned False")
    except InterleavedBC1Error as e:
        print(f"FAILED (InterleavedBC1Error): {e}")
    except Exception as e:
        print(f"FAILED ({type(e).__name__}): {e}")
        import traceback
        traceback.print_exc()


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run scripts/test_texture.py <texture_name>")
        print("\nExamples:")
        print('  uv run scripts/test_texture.py "2DUI_Bundle_HArmor_bar_stor162_WebImage"')
        print('  uv run scripts/test_texture.py "2DUI_Bundle_Companion_stor002_background"')
        sys.exit(1)

    name = sys.argv[1]
    game_dir = Path("./D4-install/Diablo IV")

    if not game_dir.exists():
        print(f"Game directory not found: {game_dir}")
        sys.exit(1)

    print(f"Loading CASC from: {game_dir}")
    print()

    extractor = TextureExtractor(game_dir)
    analyze_texture(extractor, name)


if __name__ == "__main__":
    main()
