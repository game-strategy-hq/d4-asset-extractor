"""
D4 Texture (.tex) converter.

Converts Diablo IV .tex files to standard image formats.
Based on analysis of d4-texture-extractor by adainrivers.

References:
    - https://github.com/adainrivers/d4-texture-extractor
"""

import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

# Texture format lookup table
# Maps D4 format ID to DXGI format index and alignment
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
BPP = [
    0, 128, 128, 128, 128, 96, 96, 96, 96, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64,
    64, 64, 64, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32,
    32, 32, 32, 32, 32, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 8, 8, 8, 8, 8, 8, 1,
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


@dataclass
class TexFrame:
    """A frame/slice within a texture atlas."""
    image_handle: int
    u0: float
    v0: float
    u1: float
    v1: float


@dataclass
class TextureDefinition:
    """Parsed texture definition from .tex file."""
    format_id: int
    width: int
    height: int
    depth: int
    face_count: int
    mipmap_min: int
    mipmap_max: int
    avg_color: tuple[float, float, float, float]
    hotspot: tuple[int, int]
    frames: list[TexFrame]


def read_texture_definition(data: bytes) -> TextureDefinition:
    """
    Parse a D4 texture definition file.

    The definition contains metadata about the texture (dimensions, format)
    and frame information for atlases.
    """
    # Header starts at offset 0x10 (16 bytes after SNO header)
    base = 0x10

    format_id = struct.unpack_from("<I", data, 0x8 + base)[0]
    volume_x = struct.unpack_from("<H", data, 0xc + base)[0]
    volume_y = struct.unpack_from("<H", data, 0xe + base)[0]
    width = struct.unpack_from("<H", data, 0x10 + base)[0]
    height = struct.unpack_from("<H", data, 0x12 + base)[0]
    depth = struct.unpack_from("<I", data, 0x14 + base)[0]
    face_count = struct.unpack_from("<B", data, 0x18 + base)[0]
    mipmap_min = struct.unpack_from("<B", data, 0x19 + base)[0]
    mipmap_max = struct.unpack_from("<B", data, 0x1a + base)[0]

    # Average color (RGBA floats)
    avg_r = struct.unpack_from("<f", data, 0x24 + base)[0]
    avg_g = struct.unpack_from("<f", data, 0x28 + base)[0]
    avg_b = struct.unpack_from("<f", data, 0x2c + base)[0]
    avg_a = struct.unpack_from("<f", data, 0x30 + base)[0]

    # Hotspot
    hotspot_x = struct.unpack_from("<h", data, 0x34 + base)[0]
    hotspot_y = struct.unpack_from("<h", data, 0x36 + base)[0]

    # Frame data pointer
    frame_offset = struct.unpack_from("<I", data, 0x60 + 0x08)[0] + 0x10
    frame_length = struct.unpack_from("<I", data, 0x60 + 0x0c)[0]

    # Parse frames
    frames = []
    frame_size = 0x24  # 36 bytes per frame
    num_frames = frame_length // frame_size

    for i in range(num_frames):
        offset = frame_offset + (i * frame_size)
        if offset + frame_size > len(data):
            break

        image_handle = struct.unpack_from("<I", data, offset)[0]
        u0 = struct.unpack_from("<f", data, offset + 0x4)[0]
        v0 = struct.unpack_from("<f", data, offset + 0x8)[0]
        u1 = struct.unpack_from("<f", data, offset + 0xc)[0]
        v1 = struct.unpack_from("<f", data, offset + 0x10)[0]

        frames.append(TexFrame(
            image_handle=image_handle,
            u0=u0, v0=v0, u1=u1, v1=v1
        ))

    return TextureDefinition(
        format_id=format_id,
        width=width,
        height=height,
        depth=depth,
        face_count=face_count,
        mipmap_min=mipmap_min,
        mipmap_max=mipmap_max,
        avg_color=(avg_r, avg_g, avg_b, avg_a),
        hotspot=(hotspot_x, hotspot_y),
        frames=frames,
    )


def align_up(value: int, alignment: int) -> int:
    """Align value up to the nearest multiple of alignment."""
    remainder = value % alignment
    if remainder == 0:
        return value
    return value + (alignment - remainder)


def create_dds_header(
    width: int,
    height: int,
    format_id: int,
    raw_data_length: int,
) -> bytes:
    """
    Create a DDS header for the given texture format.

    Returns the complete DDS file header (128 or 148 bytes for DX10).
    """
    if format_id not in TEXTURE_FORMATS:
        raise ValueError(f"Unknown texture format: {format_id}")

    fmt = TEXTURE_FORMATS[format_id]
    dxgi_index = fmt["dxgi_index"]
    alignment = fmt["alignment"]

    # Align width
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

    # Calculate pitch/linear size
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

    # Flags: CAPS | HEIGHT | WIDTH | PIXELFORMAT | LINEARSIZE
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
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

    # Caps
    struct.pack_into("<I", header, 108, 0x1000)  # TEXTURE

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


def dds_to_image(dds_data: bytes) -> Image.Image:
    """
    Convert DDS data to a PIL Image.

    Uses Pillow's built-in DDS support.
    """
    return Image.open(BytesIO(dds_data))


def convert_tex_to_png(
    definition_path: Path,
    payload_path: Path,
    output_path: Path,
    crop: bool = True,
) -> bool:
    """
    Convert a D4 texture to PNG.

    Args:
        definition_path: Path to meta .tex file (contains format info)
        payload_path: Path to payload .tex file (contains pixel data)
        output_path: Output PNG path
        crop: Whether to crop transparent borders

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

        # Convert to image
        image = dds_to_image(dds_data)

        # Crop if requested
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
        x0 = int(frame.u0 * width)
        y0 = int(frame.v0 * height)
        x1 = int(frame.u1 * width)
        y1 = int(frame.v1 * height)

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
