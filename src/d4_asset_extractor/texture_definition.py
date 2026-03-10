"""
TextureDefinition structure offsets and field definitions.

This is the SINGLE SOURCE OF TRUTH for all TextureDefinition field offsets.
Verified against d4data/definitions.json hash 3631735738.

Usage:
    from d4_asset_extractor.texture_definition import TEX_DEF, read_texture_definition

    # Access individual field offsets
    format_offset = TEX_DEF.eTexFormat.file_offset
    width_offset = TEX_DEF.dwWidth.file_offset

    # Or use the read function
    definition = read_texture_definition(data)
"""

import struct
from dataclasses import dataclass
from typing import NamedTuple


# =============================================================================
# Field Definition
# =============================================================================

class Field(NamedTuple):
    """A field in the TextureDefinition structure.

    Attributes:
        name: Field name from definitions.json
        struct_offset: Offset relative to struct start (from definitions.json "offset" field)
        size: Field size in bytes (derived from serializedBitCount / 8)
        format: struct format character for unpacking
        file_offset: Absolute file offset (0x10 + struct_offset)
    """
    name: str
    struct_offset: int
    size: int
    format: str

    @property
    def file_offset(self) -> int:
        """Absolute file offset (struct starts at 0x10 after SNO header)."""
        return 0x10 + self.struct_offset


# =============================================================================
# TextureDefinition Structure
# =============================================================================

# SNO header is 16 bytes (0x00-0x0F), struct starts at 0x10
# Struct has 8-byte implicit header (offsets 0-7), then named fields

@dataclass(frozen=True)
class TextureDefinitionFields:
    """All fields in the TextureDefinition structure.

    Source: d4data/definitions.json hash 3631735738

    File Layout:
        0x00-0x0F: SNO header (16 bytes)
        0x10-0x17: Implicit struct header (8 bytes, not in definitions.json)
        0x18+:     Named fields per definitions.json
    """

    # Implicit header (not in definitions.json, inferred from first field at offset 8)
    implicit_header: Field = Field("(implicit_header)", 0, 8, "8s")

    # Named fields from definitions.json (struct_offset = definitions.json "offset" value)
    sUIStylePreset: Field = Field("sUIStylePreset", 8, 4, "<I")      # SNO reference
    eTexFormat: Field = Field("eTexFormat", 12, 4, "<I")             # Format enum (0-51)
    dwVolumeXSlices: Field = Field("dwVolumeXSlices", 16, 2, "<H")   # Usually 1
    dwVolumeYSlices: Field = Field("dwVolumeYSlices", 18, 2, "<H")   # Usually 1
    dwWidth: Field = Field("dwWidth", 20, 2, "<H")                   # Texture width
    dwHeight: Field = Field("dwHeight", 22, 2, "<H")                 # Texture height
    dwDepth: Field = Field("dwDepth", 24, 4, "<I")                   # 1 for 2D textures
    dwFaceCount: Field = Field("dwFaceCount", 28, 1, "<B")           # 1 for 2D, 6 for cubemap
    dwMipMapLevelMin: Field = Field("dwMipMapLevelMin", 29, 1, "<B") # Min stored mip
    dwMipMapLevelMax: Field = Field("dwMipMapLevelMax", 30, 1, "<B") # Max stored mip
    # padding at offset 31 (1 byte)
    dwImportFlags: Field = Field("dwImportFlags", 32, 4, "<I")       # Import flags
    eTextureResourceType: Field = Field("eTextureResourceType", 36, 4, "<I")
    rgbavalAvgColor: Field = Field("rgbavalAvgColor", 40, 16, "<4f") # 4x Float32 RGBA
    pHotspot: Field = Field("pHotspot", 56, 8, "<2i")                # 2x Int32 X,Y
    serTex: Field = Field("serTex", 64, 16, None)                    # VarArray
    ptFrame: Field = Field("ptFrame", 80, 16, None)                  # VarArray
    ptGCoeffs: Field = Field("ptGCoeffs", 96, 16, None)              # VarArray
    ptPostprocessed: Field = Field("ptPostprocessed", 112, 4, "<I")  # External data flag


# Singleton instance for easy access
TEX_DEF = TextureDefinitionFields()


# =============================================================================
# VarArray Resolution
# =============================================================================

def resolve_vararray(data: bytes, header_file_offset: int) -> tuple[int, int]:
    """Resolve a VarArray header to actual data offset and count.

    VarArray headers are 16 bytes:
        [0-7]   padding (8 bytes)
        [8-11]  dataOffset (relative pointer)
        [12-15] dataSize (element count or byte size)

    Args:
        data: Raw file bytes
        header_file_offset: Absolute file offset of VarArray header

    Returns:
        (actual_data_offset, count) tuple
    """
    data_offset_field = header_file_offset + 8
    data_size_field = header_file_offset + 12

    rel_offset = struct.unpack_from("<I", data, data_offset_field)[0]
    count = struct.unpack_from("<I", data, data_size_field)[0]

    # Actual offset = relative offset + 0x10
    actual_offset = rel_offset + 0x10

    return actual_offset, count


# =============================================================================
# Parsed Data Structures
# =============================================================================

@dataclass
class TexFrame:
    """A single frame within a texture atlas."""
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


# =============================================================================
# Parser
# =============================================================================

def read_texture_definition(data: bytes) -> TextureDefinition:
    """Parse a D4 texture definition file.

    Uses offsets from TEX_DEF (verified against definitions.json hash 3631735738).

    Args:
        data: Raw .tex file bytes

    Returns:
        Parsed TextureDefinition
    """
    # Read fixed fields using centralized offsets
    format_id = struct.unpack_from(TEX_DEF.eTexFormat.format, data, TEX_DEF.eTexFormat.file_offset)[0]
    width = struct.unpack_from(TEX_DEF.dwWidth.format, data, TEX_DEF.dwWidth.file_offset)[0]
    height = struct.unpack_from(TEX_DEF.dwHeight.format, data, TEX_DEF.dwHeight.file_offset)[0]
    depth = struct.unpack_from(TEX_DEF.dwDepth.format, data, TEX_DEF.dwDepth.file_offset)[0]
    face_count = struct.unpack_from(TEX_DEF.dwFaceCount.format, data, TEX_DEF.dwFaceCount.file_offset)[0]
    mipmap_min = struct.unpack_from(TEX_DEF.dwMipMapLevelMin.format, data, TEX_DEF.dwMipMapLevelMin.file_offset)[0]
    mipmap_max = struct.unpack_from(TEX_DEF.dwMipMapLevelMax.format, data, TEX_DEF.dwMipMapLevelMax.file_offset)[0]

    # Average color (4 floats)
    avg_color = struct.unpack_from(TEX_DEF.rgbavalAvgColor.format, data, TEX_DEF.rgbavalAvgColor.file_offset)

    # Hotspot (2 ints)
    hotspot = struct.unpack_from(TEX_DEF.pHotspot.format, data, TEX_DEF.pHotspot.file_offset)

    # Parse frames via VarArray
    frame_offset, frame_byte_count = resolve_vararray(data, TEX_DEF.ptFrame.file_offset)

    frames = []
    frame_size = 0x24  # 36 bytes per frame
    num_frames = frame_byte_count // frame_size

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
        avg_color=avg_color,
        hotspot=hotspot,
        frames=frames,
    )


# =============================================================================
# Reference Table (for documentation/debugging)
# =============================================================================

def print_offset_table() -> None:
    """Print a formatted table of all field offsets."""
    print("TextureDefinition Offsets (d4data/definitions.json hash 3631735738)")
    print("=" * 72)
    print(f"{'Field':<24} {'Struct Offset':>14} {'File Offset':>12} {'Size':>6}")
    print("-" * 72)

    for field in [
        TEX_DEF.implicit_header,
        TEX_DEF.sUIStylePreset,
        TEX_DEF.eTexFormat,
        TEX_DEF.dwVolumeXSlices,
        TEX_DEF.dwVolumeYSlices,
        TEX_DEF.dwWidth,
        TEX_DEF.dwHeight,
        TEX_DEF.dwDepth,
        TEX_DEF.dwFaceCount,
        TEX_DEF.dwMipMapLevelMin,
        TEX_DEF.dwMipMapLevelMax,
        TEX_DEF.dwImportFlags,
        TEX_DEF.eTextureResourceType,
        TEX_DEF.rgbavalAvgColor,
        TEX_DEF.pHotspot,
        TEX_DEF.serTex,
        TEX_DEF.ptFrame,
        TEX_DEF.ptGCoeffs,
        TEX_DEF.ptPostprocessed,
    ]:
        print(f"{field.name:<24} {field.struct_offset:>14} {field.file_offset:#14x} {field.size:>6}")


if __name__ == "__main__":
    print_offset_table()
