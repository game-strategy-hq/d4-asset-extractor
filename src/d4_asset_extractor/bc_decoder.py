"""
Pure Python BC1 (DXT1) texture decoder.

Based on DirectXTex's BC1 decompression algorithm.
Handles D4's non-standard row padding/interleaving that PIL can't decode.

References:
    - https://github.com/microsoft/DirectXTex
    - https://docs.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-block-compression
"""

import struct
from typing import Optional

import numpy as np
from PIL import Image


def decode_rgb565(value: int) -> tuple[int, int, int]:
    """Decode a 16-bit RGB565 color to RGB888."""
    r = ((value >> 11) & 0x1F) * 255 // 31
    g = ((value >> 5) & 0x3F) * 255 // 63
    b = (value & 0x1F) * 255 // 31
    return (r, g, b)


def decode_bc1_block(block: bytes) -> np.ndarray:
    """
    Decode an 8-byte BC1 block to a 4x4 RGBA pixel array.

    BC1 block structure:
        - Bytes 0-1: First endpoint color (RGB565)
        - Bytes 2-3: Second endpoint color (RGB565)
        - Bytes 4-7: 32-bit bitmap with 2 bits per pixel

    Args:
        block: 8-byte BC1 compressed block

    Returns:
        4x4x4 numpy array (RGBA)
    """
    if len(block) != 8:
        # Return transparent black for invalid blocks
        return np.zeros((4, 4, 4), dtype=np.uint8)

    # Unpack colors and indices
    color0, color1, indices = struct.unpack("<HHI", block)

    # Decode endpoint colors
    r0, g0, b0 = decode_rgb565(color0)
    r1, g1, b1 = decode_rgb565(color1)

    # Build color palette
    # BC1 has two modes based on color0 vs color1 comparison
    if color0 > color1:
        # 4-color mode (opaque)
        colors = [
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255),
            ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255),
        ]
    else:
        # 3-color + transparent mode
        colors = [
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255),
            (0, 0, 0, 0),  # Transparent
        ]

    # Decode 4x4 pixels using 2-bit indices
    pixels = np.zeros((4, 4, 4), dtype=np.uint8)
    for y in range(4):
        for x in range(4):
            idx = (indices >> (2 * (y * 4 + x))) & 0x3
            pixels[y, x] = colors[idx]

    return pixels


def decode_bc1_texture(
    data: bytes,
    width: int,
    height: int,
    stored_row_pitch: Optional[int] = None,
) -> Image.Image:
    """
    Decode BC1 compressed texture data to an RGBA image.

    Handles D4's non-standard row padding by using stored_row_pitch
    to correctly extract block data.

    Args:
        data: Raw BC1 compressed data
        width: Texture width in pixels
        height: Texture height in pixels
        stored_row_pitch: Actual bytes per block-row in the data.
                         If None, calculated from width.

    Returns:
        PIL Image in RGBA mode
    """
    # Calculate block dimensions
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4

    # Calculate expected row pitch (bytes per row of blocks)
    expected_row_pitch = blocks_x * 8  # 8 bytes per BC1 block

    # Use stored pitch if provided, otherwise use expected
    if stored_row_pitch is None:
        stored_row_pitch = expected_row_pitch

    # Create output image
    output = np.zeros((height, width, 4), dtype=np.uint8)

    # Decode each block
    for by in range(blocks_y):
        row_offset = by * stored_row_pitch

        for bx in range(blocks_x):
            block_offset = row_offset + bx * 8

            # Check if we have enough data
            if block_offset + 8 > len(data):
                continue

            block = data[block_offset:block_offset + 8]
            pixels = decode_bc1_block(block)

            # Copy decoded block to output
            py = by * 4
            px = bx * 4

            # Handle edge cases where block extends beyond image
            copy_h = min(4, height - py)
            copy_w = min(4, width - px)

            output[py:py + copy_h, px:px + copy_w] = pixels[:copy_h, :copy_w]

    return Image.fromarray(output, mode="RGBA")


def decode_bc1_with_detection(
    data: bytes,
    width: int,
    height: int,
) -> Image.Image:
    """
    Decode BC1 texture with automatic row pitch detection.

    For D4 textures with non-standard padding, this function
    calculates the stored row pitch from the data size.

    Args:
        data: Raw BC1 compressed data
        width: Texture width in pixels
        height: Texture height in pixels

    Returns:
        PIL Image in RGBA mode
    """
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4

    expected_size = blocks_x * blocks_y * 8

    if len(data) == expected_size:
        # Standard layout - use normal decoding
        return decode_bc1_texture(data, width, height)

    # Calculate stored row pitch from data size
    if blocks_y > 0:
        stored_row_pitch = len(data) // blocks_y
    else:
        stored_row_pitch = blocks_x * 8

    return decode_bc1_texture(data, width, height, stored_row_pitch)
