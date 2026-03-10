"""
D4 Texture (.tex) converter.

Converts Diablo IV .tex files to standard image formats.
Based on analysis of d4-texture-extractor by adainrivers.

References:
    - https://github.com/adainrivers/d4-texture-extractor
"""

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from .texconv import (
    TexconvConfig,
    TexconvWrapper,
    TexconvError,
    is_available as texconv_is_available,
)

# Import centralized TextureDefinition structure and parser
# This is the SINGLE SOURCE OF TRUTH for field offsets
from .texture_definition import (
    TEX_DEF,
    Field,
    TextureDefinitionFields,
    resolve_vararray,
    TexFrame,
    TextureDefinition,
    read_texture_definition,
)

# Texture format lookup table
# Maps D4 format ID to DXGI format index and alignment
# Alignment values from d4-texture-extractor reference implementation
TEXTURE_FORMATS = {
    0:  {"dxgi": "DXGI_FORMAT_B8G8R8A8_UNORM", "dxgi_index": 87, "alignment": 64},
    7:  {"dxgi": "DXGI_FORMAT_A8_UNORM", "dxgi_index": 65, "alignment": 64},
    9:  {"dxgi": "DXGI_FORMAT_BC1_UNORM", "dxgi_index": 71, "alignment": 128},
    10: {"dxgi": "DXGI_FORMAT_BC1_UNORM", "dxgi_index": 71, "alignment": 128},
    12: {"dxgi": "DXGI_FORMAT_BC3_UNORM", "dxgi_index": 77, "alignment": 64},
    23: {"dxgi": "DXGI_FORMAT_A8_UNORM", "dxgi_index": 65, "alignment": 128},
    25: {"dxgi": "DXGI_FORMAT_R16G16B16A16_FLOAT", "dxgi_index": 10, "alignment": 32},
    41: {"dxgi": "DXGI_FORMAT_BC4_UNORM", "dxgi_index": 80, "alignment": 64},
    42: {"dxgi": "DXGI_FORMAT_BC5_UNORM", "dxgi_index": 83, "alignment": 64},
    43: {"dxgi": "DXGI_FORMAT_BC6H_SF16", "dxgi_index": 96, "alignment": 64},
    44: {"dxgi": "DXGI_FORMAT_BC7_UNORM", "dxgi_index": 98, "alignment": 64},
    45: {"dxgi": "DXGI_FORMAT_B8G8R8A8_UNORM", "dxgi_index": 87, "alignment": 64},
    46: {"dxgi": "DXGI_FORMAT_BC1_UNORM", "dxgi_index": 71, "alignment": 128},
    47: {"dxgi": "DXGI_FORMAT_BC1_UNORM", "dxgi_index": 71, "alignment": 128},
    48: {"dxgi": "DXGI_FORMAT_BC2_UNORM", "dxgi_index": 74, "alignment": 64},
    49: {"dxgi": "DXGI_FORMAT_BC3_UNORM", "dxgi_index": 77, "alignment": 64},
    50: {"dxgi": "DXGI_FORMAT_BC7_UNORM", "dxgi_index": 98, "alignment": 64},
    51: {"dxgi": "DXGI_FORMAT_BC6H_UF16", "dxgi_index": 95, "alignment": 64},
}

# Bits per pixel for DXGI formats (indexed by DXGI format index)
# Per spec Section 5.3: A8_UNORM (DXGI 65) = 8 bpp
BPP = [
    0, 128, 128, 128, 128, 96, 96, 96, 96, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64,
    64, 64, 64, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32,
    32, 32, 32, 32, 32, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 8, 8, 8, 8, 8, 8, 8,
    32, 32, 32, 4, 4, 4, 8, 8, 8, 8, 8, 8, 4, 4, 4, 8, 8, 8, 16, 16, 32, 32, 32, 32, 32, 32,
    32, 8, 8, 8, 8, 8, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 16
]

# FourCC codes
FOURCC_DX10 = 808540228
FOURCC_DXT1 = 827611204
FOURCC_DXT3 = 861165636
FOURCC_DXT5 = 894720068
FOURCC_ATI1 = 826889281
FOURCC_ATI2 = 843666497


# Note: TexFrame, TextureDefinition, and read_texture_definition are imported
# from .texture_definition (the single source of truth for field offsets)


def align_up(value: int, alignment: int) -> int:
    """Align value up to the nearest multiple of alignment."""
    remainder = value % alignment
    if remainder == 0:
        return value
    return value + (alignment - remainder)


def calculate_mip0_size(width: int, height: int, format_id: int) -> int:
    """
    Calculate the expected size in bytes for mip level 0 of a texture.

    Uses the aligned width based on the format's alignment requirement,
    matching what the DDS header will declare.

    Args:
        width: Texture width in pixels
        height: Texture height in pixels
        format_id: D4 texture format ID

    Returns:
        Expected byte size for mip level 0 (with alignment)
    """
    if format_id not in TEXTURE_FORMATS:
        return 0

    fmt = TEXTURE_FORMATS[format_id]
    dxgi_index = fmt["dxgi_index"]
    alignment = fmt["alignment"]

    # Apply alignment to width
    aligned_width = align_up(width, alignment)

    # Block compressed formats (BC1-BC7)
    bc_formats = {
        71: 8,   # BC1 - 8 bytes per 4x4 block
        74: 16,  # BC2 - 16 bytes per 4x4 block
        77: 16,  # BC3 - 16 bytes per 4x4 block
        80: 8,   # BC4 - 8 bytes per 4x4 block
        83: 16,  # BC5 - 16 bytes per 4x4 block
        95: 16,  # BC6H - 16 bytes per 4x4 block
        96: 16,  # BC6H - 16 bytes per 4x4 block
        98: 16,  # BC7 - 16 bytes per 4x4 block
    }

    if dxgi_index in bc_formats:
        block_size = bc_formats[dxgi_index]
        blocks_x = (aligned_width + 3) // 4
        blocks_y = (height + 3) // 4
        return blocks_x * blocks_y * block_size

    # Uncompressed formats - use bits per pixel
    bpp = BPP[dxgi_index] if dxgi_index < len(BPP) else 32
    return (aligned_width * height * bpp) // 8


def create_dds_header(
    width: int,
    height: int,
    format_id: int,
    raw_data_length: int,
) -> bytes:
    """
    Create a DDS header for the given texture format.

    Args:
        width: Texture width in pixels
        height: Texture height in pixels
        format_id: D4 texture format ID
        raw_data_length: Size of raw payload data

    Returns the complete DDS file header (128 or 148 bytes for DX10).
    """
    if format_id not in TEXTURE_FORMATS:
        raise ValueError(f"Unknown texture format: {format_id}")

    fmt = TEXTURE_FORMATS[format_id]
    dxgi_index = fmt["dxgi_index"]
    alignment = fmt["alignment"]

    # Align width to format's alignment (matches JS d4-texture-extractor)
    aligned_width = align_up(width, alignment)

    # Determine FourCC code
    fourcc = FOURCC_DX10  # Default to DX10 extended header
    if dxgi_index == 71:  # BC1/DXT1
        fourcc = FOURCC_DXT1
    elif dxgi_index == 74:  # BC2/DXT3
        fourcc = FOURCC_DXT3
    elif dxgi_index == 77:  # BC3/DXT5
        fourcc = FOURCC_DXT5
    elif dxgi_index == 80:  # BC4/ATI1
        fourcc = FOURCC_ATI1
    elif dxgi_index == 83:  # BC5/ATI2
        fourcc = FOURCC_ATI2

    # Calculate pitch/linear size using JS formula:
    # count = (aligned_width * height * bpp[index]) / 8
    # This matches the d4-texture-extractor exactly
    bits_per_pixel = BPP[dxgi_index] if dxgi_index < len(BPP) else 32
    pitch = (aligned_width * height * bits_per_pixel) // 8

    # Header size depends on whether we use DX10 extension
    use_dx10 = (fourcc == FOURCC_DX10)
    header_size = 148 if use_dx10 else 128
    header = bytearray(header_size)

    # Magic number "DDS "
    header[0:4] = b"DDS "

    # Header size (always 124 for the base header)
    struct.pack_into("<I", header, 4, 124)

    # Flags: CAPS | HEIGHT | WIDTH | PIXELFORMAT (matching JS code exactly)
    flags = 0x1 | 0x2 | 0x4 | 0x1000
    struct.pack_into("<I", header, 8, flags)

    # Height
    struct.pack_into("<I", header, 12, height)

    # Width
    struct.pack_into("<I", header, 16, aligned_width)

    # Pitch or linear size
    struct.pack_into("<I", header, 20, pitch)

    # Depth
    struct.pack_into("<I", header, 24, 0)

    # Mipmap count
    struct.pack_into("<I", header, 28, 1)

    # Reserved (44 bytes at offset 32-75)

    # Pixel format structure (at offset 76)
    # Size of pixel format structure
    struct.pack_into("<I", header, 76, 32)

    # Pixel format flags (FOURCC)
    struct.pack_into("<I", header, 80, 4)

    # FourCC
    struct.pack_into("<I", header, 84, fourcc)

    # Caps (left as 0 to match JS implementation)

    # DX10 extended header
    if use_dx10:
        # DXGI format
        struct.pack_into("<I", header, 128, dxgi_index)
        # Resource dimension (3 = 2D)
        struct.pack_into("<I", header, 132, 3)
        # Misc flag
        struct.pack_into("<I", header, 136, 0)
        # Array size
        struct.pack_into("<I", header, 140, 1)
        # Misc flag 2
        struct.pack_into("<I", header, 144, 0)

    return bytes(header)


def convert_raw_to_dds(
    raw_data: bytes,
    definition: TextureDefinition,
) -> bytes:
    """
    Convert raw texture payload to DDS format.

    Args:
        raw_data: Raw pixel data from payload .tex file
        definition: Parsed texture definition

    Returns:
        Complete DDS file as bytes
    """
    header = create_dds_header(
        width=definition.width,
        height=definition.height,
        format_id=definition.format_id,
        raw_data_length=len(raw_data),
    )
    return header + raw_data


def dds_to_image(
    dds_data: bytes,
    texconv_config: Optional[TexconvConfig] = None,
) -> Image.Image:
    """
    Convert DDS data to a PIL Image using texconv.

    D4 textures are stored in GPU-tiled format, requiring texconv for ALL formats.
    This matches the reference d4-texture-extractor which always uses texconv.

    Args:
        dds_data: Raw DDS file bytes
        texconv_config: Optional texconv configuration

    Raises:
        RuntimeError: If texconv is not available
        TexconvError: If conversion fails
    """
    wrapper = TexconvWrapper(texconv_config) if texconv_config else None

    if wrapper is None:
        # Use module-level check
        if texconv_is_available():
            from .texconv import convert_dds
            return convert_dds(dds_data)
    elif wrapper.is_available():
        return wrapper.convert_dds_to_image(dds_data)

    raise RuntimeError(
        "texconv is required for D4 texture decoding. "
        "On Windows: Install texconv.exe from https://github.com/Microsoft/DirectXTex/releases "
        "On macOS: Install Whisky (https://getwhisky.app) and place texconv.exe in ./tools/"
    )


def convert_tex_to_png(
    definition_path: Path,
    payload_path: Path,
    output_path: Path,
    crop: bool = True,
    texconv_config: Optional[TexconvConfig] = None,
) -> bool:
    """
    Convert a D4 texture to PNG.

    Args:
        definition_path: Path to meta .tex file (contains format info)
        payload_path: Path to payload .tex file (contains pixel data)
        output_path: Output PNG path
        crop: Whether to crop transparent borders
        texconv_config: Optional texconv configuration

    Returns:
        True if successful
    """
    try:
        # Read files
        definition_data = definition_path.read_bytes()
        payload_data = payload_path.read_bytes()

        # Parse definition
        definition = read_texture_definition(definition_data)

        # Convert to DDS
        dds_data = convert_raw_to_dds(payload_data, definition)

        # Convert to image using texconv for BC7/BC6H support
        image = dds_to_image(dds_data, texconv_config=texconv_config)

        # Crop to actual texture dimensions (aligned width may be larger)
        if image.width > definition.width or image.height > definition.height:
            image = image.crop((0, 0, definition.width, definition.height))

        # Crop transparent borders if requested
        if crop:
            bbox = image.getbbox()
            if bbox:
                image = image.crop(bbox)

        # Save
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, "PNG", optimize=True)

        return True

    except Exception as e:
        print(f"Error converting {definition_path}: {e}")
        return False


def slice_texture(
    image: Image.Image,
    frames: list[TexFrame],
    output_dir: Path,
) -> dict[int, Path]:
    """
    Slice a texture atlas into individual frames.

    Args:
        image: The full texture image
        frames: Frame definitions with UV coordinates
        output_dir: Directory to save slices

    Returns:
        Dict mapping image handle to output path
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    width, height = image.size

    for frame in frames:
        # Convert UV coordinates to pixels
        # Use floor for top-left, ceil for bottom-right (matches JS d4-texture-extractor)
        x0 = math.floor(frame.u0 * width)
        y0 = math.floor(frame.v0 * height)
        x1 = math.ceil(frame.u1 * width)
        y1 = math.ceil(frame.v1 * height)

        # Ensure valid bounds
        x0 = max(0, min(x0, width))
        y0 = max(0, min(y0, height))
        x1 = max(0, min(x1, width))
        y1 = max(0, min(y1, height))

        if x1 <= x0 or y1 <= y0:
            continue

        # Crop frame
        frame_image = image.crop((x0, y0, x1, y1))

        # Skip fully transparent
        if frame_image.mode == "RGBA":
            bbox = frame_image.getbbox()
            if not bbox:
                continue

        # Save
        output_path = output_dir / f"{frame.image_handle}.png"
        frame_image.save(output_path, "PNG", optimize=True)
        results[frame.image_handle] = output_path

    return results
