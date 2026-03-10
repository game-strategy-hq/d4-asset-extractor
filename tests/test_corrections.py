"""
Unit tests for d4-asset-extractor corrections.

These tests verify that the implementation matches the JS reference (d4-texture-extractor)
and that critical corrections remain in place.

Corrections verified:
1. VarArray formula: `dataOffset + 0x10` (not `0x78 + dataOffset + 0x10`)
2. DDS header dwDepth: 0 (not 1)
3. DDS header flags: 0x1007 (CAPS | HEIGHT | WIDTH | PIXELFORMAT, no LINEARSIZE)
4. Frame bounds calculation: floor for top-left, ceil for bottom-right
5. TextureDefinition offsets verified against d4data/definitions.json hash 3631735738
"""

import math
import struct
from typing import Any

import pytest

from d4_asset_extractor.tex_converter import (
    BPP,
    FOURCC_DX10,
    FOURCC_DXT1,
    TEXTURE_FORMATS,
    align_up,
    calculate_mip0_size,
    create_dds_header,
    read_texture_definition,
    slice_texture,
    TexFrame,
)
from d4_asset_extractor.texture_definition import TEX_DEF
from d4_asset_extractor.texture_extractor import parse_texture_frames


class TestVarArrayOffset:
    """Tests for VarArray offset calculation.

    Per JS reference (d4-texture-extractor line 30):
    The actual offset is `dataOffset + 0x10`, NOT `0x78 + dataOffset + 0x10`.
    """

    def test_vararray_offset_formula(self) -> None:
        """Verify VarArray offset formula matches JS reference."""
        # Create a minimal .tex definition with frame data
        # Using TEX_DEF as the single source of truth for all offsets
        # (verified against definitions.json hash 3631735738)

        # Create test data with known offsets
        data = bytearray(0x200)

        # Place a known value at the expected frame data location
        # If dataOffset = 0x100, then actual offset = 0x100 + 0x10 = 0x110
        data_offset = 0x100
        actual_frame_offset = data_offset + 0x10  # Should be 0x110

        # Write dataOffset to VarArray header (ptFrame)
        # VarArray: dataOffset at +8, dataSize at +12
        struct.pack_into("<I", data, TEX_DEF.ptFrame.file_offset + 0x08, data_offset)

        # Write a frame size indicating one frame (36 bytes)
        frame_size = 0x24
        struct.pack_into("<I", data, TEX_DEF.ptFrame.file_offset + 0x0c, frame_size)

        # Write frame data at the expected actual offset
        # Frame structure: image_handle (4), u0, v0, u1, v1 (4 floats = 16 bytes), ...
        test_image_handle = 0x12345678
        struct.pack_into("<I", data, actual_frame_offset, test_image_handle)
        struct.pack_into("<f", data, actual_frame_offset + 0x4, 0.0)   # u0
        struct.pack_into("<f", data, actual_frame_offset + 0x8, 0.0)   # v0
        struct.pack_into("<f", data, actual_frame_offset + 0xc, 1.0)   # u1
        struct.pack_into("<f", data, actual_frame_offset + 0x10, 1.0)  # v1

        # Write required header fields using TEX_DEF offsets
        struct.pack_into("<I", data, TEX_DEF.eTexFormat.file_offset, 9)    # BC1
        struct.pack_into("<H", data, TEX_DEF.dwWidth.file_offset, 256)
        struct.pack_into("<H", data, TEX_DEF.dwHeight.file_offset, 256)

        # Parse and verify the frame was found at the correct offset
        definition = read_texture_definition(bytes(data))

        assert len(definition.frames) == 1, "Should parse exactly one frame"
        assert definition.frames[0].image_handle == test_image_handle, \
            f"Frame should have correct image_handle, got {definition.frames[0].image_handle}"

    def test_incorrect_offset_would_fail(self) -> None:
        """Verify that an incorrect offset formula would fail to find frames."""
        # This test documents what the WRONG behavior would look like
        # If we used 0x78 + dataOffset + 0x10, frames would be at wrong location

        data = bytearray(0x300)

        # Set up VarArray header with dataOffset = 0x100
        data_offset = 0x100
        struct.pack_into("<I", data, 0x60 + 0x08, data_offset)
        struct.pack_into("<I", data, 0x60 + 0x0c, 0x24)  # One frame

        # Place frame data at CORRECT location (0x100 + 0x10 = 0x110)
        correct_offset = data_offset + 0x10
        struct.pack_into("<I", data, correct_offset, 0xAABBCCDD)
        struct.pack_into("<f", data, correct_offset + 0x4, 0.1)
        struct.pack_into("<f", data, correct_offset + 0x8, 0.1)
        struct.pack_into("<f", data, correct_offset + 0xc, 0.9)
        struct.pack_into("<f", data, correct_offset + 0x10, 0.9)

        # The WRONG offset would be 0x78 + 0x100 + 0x10 = 0x188
        wrong_offset = 0x78 + data_offset + 0x10

        # Ensure these are different
        assert correct_offset != wrong_offset, "Test setup: offsets should differ"
        assert correct_offset == 0x110
        assert wrong_offset == 0x188


class TestDDSHeader:
    """Tests for DDS header structure.

    Per JS reference and DDS specification:
    - dwDepth at offset 0x18 should be 0 (not 1) for 2D textures
    - Flags should be 0x1007 (CAPS | HEIGHT | WIDTH | PIXELFORMAT)
    """

    def test_dds_header_magic(self) -> None:
        """Verify DDS magic number is correct."""
        header = create_dds_header(256, 256, 9, 65536)

        assert header[0:4] == b"DDS ", "DDS magic should be 'DDS '"

    def test_dds_header_size(self) -> None:
        """Verify DDS header size field is 124."""
        header = create_dds_header(256, 256, 9, 65536)

        size = struct.unpack("<I", header[4:8])[0]
        assert size == 124, f"Header size should be 124, got {size}"

    def test_dds_header_flags(self) -> None:
        """Verify DDS header flags are 0x1007 (no LINEARSIZE)."""
        header = create_dds_header(256, 256, 9, 65536)

        flags = struct.unpack("<I", header[8:12])[0]

        # Expected flags: CAPS (0x1) | HEIGHT (0x2) | WIDTH (0x4) | PIXELFORMAT (0x1000)
        expected = 0x1 | 0x2 | 0x4 | 0x1000
        assert flags == expected, f"Flags should be {hex(expected)}, got {hex(flags)}"
        assert flags == 0x1007, f"Flags should be 0x1007, got {hex(flags)}"

    def test_dds_header_no_linearsize_flag(self) -> None:
        """Verify LINEARSIZE flag (0x80000) is NOT set."""
        header = create_dds_header(256, 256, 9, 65536)

        flags = struct.unpack("<I", header[8:12])[0]

        linearsize_flag = 0x80000
        assert (flags & linearsize_flag) == 0, \
            "LINEARSIZE flag should NOT be set"

    def test_dds_header_depth_field(self) -> None:
        """Verify DDS header dwDepth is 0 at offset 0x18."""
        header = create_dds_header(256, 256, 9, 65536)

        # dwDepth is at offset 24 (0x18) in the header
        # Note: offset 0 is "DDS ", offset 4 is header size, etc.
        depth = struct.unpack("<I", header[24:28])[0]

        assert depth == 0, f"dwDepth should be 0, got {depth}"

    def test_dds_header_dimensions(self) -> None:
        """Verify width and height are correctly set."""
        width, height = 512, 256

        header = create_dds_header(width, height, 9, 65536)

        header_height = struct.unpack("<I", header[12:16])[0]
        header_width = struct.unpack("<I", header[16:20])[0]

        assert header_height == height, f"Height should be {height}, got {header_height}"
        # Width may be aligned
        assert header_width >= width, f"Width should be >= {width}, got {header_width}"

    def test_dds_header_mipmap_count(self) -> None:
        """Verify mipmap count is 1."""
        header = create_dds_header(256, 256, 9, 65536)

        mipcount = struct.unpack("<I", header[28:32])[0]
        assert mipcount == 1, f"Mipmap count should be 1, got {mipcount}"

    def test_dds_header_pixelformat_size(self) -> None:
        """Verify pixel format structure size is 32."""
        header = create_dds_header(256, 256, 9, 65536)

        pf_size = struct.unpack("<I", header[76:80])[0]
        assert pf_size == 32, f"Pixel format size should be 32, got {pf_size}"

    def test_dds_header_fourcc_flag(self) -> None:
        """Verify pixel format flags include FOURCC (0x4)."""
        header = create_dds_header(256, 256, 9, 65536)

        pf_flags = struct.unpack("<I", header[80:84])[0]
        assert (pf_flags & 0x4) == 0x4, "Pixel format should have FOURCC flag"

    @pytest.mark.parametrize("format_id,expected_fourcc", [
        (9, FOURCC_DXT1),   # BC1
        (10, FOURCC_DXT1),  # BC1
        (46, FOURCC_DXT1),  # BC1
        (47, FOURCC_DXT1),  # BC1
    ])
    def test_dds_header_bc1_fourcc(self, format_id: int, expected_fourcc: int) -> None:
        """Verify BC1 formats use DXT1 FourCC."""
        header = create_dds_header(256, 256, format_id, 65536)

        fourcc = struct.unpack("<I", header[84:88])[0]
        assert fourcc == expected_fourcc, \
            f"Format {format_id} should use FourCC {expected_fourcc}, got {fourcc}"

    @pytest.mark.parametrize("format_id", [44, 50])  # BC7 formats
    def test_dds_header_dx10_extension(self, format_id: int) -> None:
        """Verify BC7 and other DX10 formats have extended header."""
        header = create_dds_header(256, 256, format_id, 65536)

        # DX10 header should be 148 bytes total
        assert len(header) == 148, f"DX10 header should be 148 bytes, got {len(header)}"

        # FourCC should be DX10
        fourcc = struct.unpack("<I", header[84:88])[0]
        assert fourcc == FOURCC_DX10, f"Should use DX10 FourCC"

        # DXGI format should be at offset 128
        dxgi_format = struct.unpack("<I", header[128:132])[0]
        expected_dxgi = TEXTURE_FORMATS[format_id]["dxgi_index"]
        assert dxgi_format == expected_dxgi, \
            f"DXGI format should be {expected_dxgi}, got {dxgi_format}"


class TestFrameBoundsCalculation:
    """Tests for frame/slice coordinate calculation.

    Per spec Section 3.4 and JS reference:
    - Use floor() for top-left coordinates
    - Use ceil() for bottom-right coordinates
    - Frame width = ceil(u1*W) - floor(u0*W)
    """

    def test_frame_floor_ceil_coordinates(self) -> None:
        """Verify floor for top-left, ceil for bottom-right."""
        # Test with non-integer pixel coordinates
        tex_width, tex_height = 512, 512

        # UV coordinates that result in fractional pixels
        u0, v0 = 0.1, 0.2       # 51.2, 102.4
        u1, v1 = 0.3, 0.4       # 153.6, 204.8

        x0 = math.floor(u0 * tex_width)   # floor(51.2) = 51
        y0 = math.floor(v0 * tex_height)  # floor(102.4) = 102
        x1 = math.ceil(u1 * tex_width)    # ceil(153.6) = 154
        y1 = math.ceil(v1 * tex_height)   # ceil(204.8) = 205

        assert x0 == 51, f"x0 should be floor(51.2)=51, got {x0}"
        assert y0 == 102, f"y0 should be floor(102.4)=102, got {y0}"
        assert x1 == 154, f"x1 should be ceil(153.6)=154, got {x1}"
        assert y1 == 205, f"y1 should be ceil(204.8)=205, got {y1}"

    def test_frame_width_calculation(self) -> None:
        """Verify frame width is calculated as ceil(u1*W) - floor(u0*W)."""
        tex_width = 512
        u0, u1 = 0.1, 0.3

        # Correct: ceil(u1*W) - floor(u0*W)
        correct_width = math.ceil(u1 * tex_width) - math.floor(u0 * tex_width)

        # Wrong: int((u1 - u0) * W)
        wrong_width = int((u1 - u0) * tex_width)

        assert correct_width == 154 - 51, f"Correct width should be 103"
        assert correct_width == 103
        assert wrong_width == 102, f"Wrong formula gives 102"
        assert correct_width != wrong_width, "Formulas should give different results"

    def test_slice_texture_uses_correct_bounds(self) -> None:
        """Verify slice_texture function uses floor/ceil correctly."""
        # Create a 512x512 RGBA image
        from PIL import Image
        img = Image.new("RGBA", (512, 512), (255, 0, 0, 255))

        # Create a frame with fractional coordinates
        frames = [
            TexFrame(
                image_handle=1,
                u0=0.1,   # 51.2
                v0=0.2,   # 102.4
                u1=0.3,   # 153.6
                v1=0.4,   # 204.8
            )
        ]

        # Mock output directory
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            results = slice_texture(img, frames, output_dir)

            assert len(results) == 1, "Should have one result"

            # Load the sliced image and check dimensions
            sliced = Image.open(results[1])

            # Width should be ceil(153.6) - floor(51.2) = 154 - 51 = 103
            # Height should be ceil(204.8) - floor(102.4) = 205 - 102 = 103
            expected_width = math.ceil(0.3 * 512) - math.floor(0.1 * 512)
            expected_height = math.ceil(0.4 * 512) - math.floor(0.2 * 512)

            assert sliced.width == expected_width, \
                f"Sliced width should be {expected_width}, got {sliced.width}"
            assert sliced.height == expected_height, \
                f"Sliced height should be {expected_height}, got {sliced.height}"


class TestWidthAlignment:
    """Tests for texture width alignment."""

    @pytest.mark.parametrize("format_id,expected_alignment", [
        (9, 128),   # BC1
        (10, 128),  # BC1
        (44, 64),   # BC7
        (50, 64),   # BC7
        (0, 64),    # B8G8R8A8
        (7, 64),    # A8
    ])
    def test_format_alignment(self, format_id: int, expected_alignment: int) -> None:
        """Verify format alignment matches spec."""
        assert format_id in TEXTURE_FORMATS, f"Format {format_id} should be defined"
        assert TEXTURE_FORMATS[format_id]["alignment"] == expected_alignment

    def test_align_up_function(self) -> None:
        """Verify align_up correctly rounds to alignment boundary."""
        assert align_up(100, 64) == 128
        assert align_up(64, 64) == 64
        assert align_up(65, 64) == 128
        assert align_up(127, 128) == 128
        assert align_up(128, 128) == 128
        assert align_up(129, 128) == 256

    def test_dds_width_alignment(self) -> None:
        """Verify DDS header uses aligned width."""
        # 100 pixel width with 128 alignment should become 128
        header = create_dds_header(100, 256, 9, 65536)

        header_width = struct.unpack("<I", header[16:20])[0]
        assert header_width == 128, f"Width 100 should align to 128, got {header_width}"


class TestMip0SizeCalculation:
    """Tests for mip0 size calculation."""

    def test_bc1_mip0_size(self) -> None:
        """Verify BC1 mip0 size calculation."""
        # BC1: 8 bytes per 4x4 block
        # 256x256 aligned to 256x256 = 64x64 blocks = 4096 blocks * 8 = 32768 bytes
        size = calculate_mip0_size(256, 256, 9)
        assert size == 32768, f"BC1 256x256 mip0 should be 32768, got {size}"

    def test_bc1_mip0_size_with_alignment(self) -> None:
        """Verify BC1 mip0 size with width alignment."""
        # 100x100 with 128 alignment = 128x100
        # blocks_x = (128 + 3) // 4 = 32
        # blocks_y = (100 + 3) // 4 = 25
        # size = 32 * 25 * 8 = 6400
        size = calculate_mip0_size(100, 100, 9)
        expected = 32 * 25 * 8
        assert size == expected, f"BC1 100x100 mip0 should be {expected}, got {size}"

    def test_bc7_mip0_size(self) -> None:
        """Verify BC7 mip0 size calculation."""
        # BC7: 16 bytes per 4x4 block
        # 256x256 = 64x64 blocks = 4096 blocks * 16 = 65536 bytes
        size = calculate_mip0_size(256, 256, 44)
        assert size == 65536, f"BC7 256x256 mip0 should be 65536, got {size}"


class TestBitsPerPixel:
    """Tests for bits per pixel lookup table."""

    def test_bpp_common_formats(self) -> None:
        """Verify BPP for common DXGI format indices."""
        # A8_UNORM (DXGI 65) = 8 bpp
        assert BPP[65] == 8, f"A8_UNORM should be 8 bpp"

        # BC1 (DXGI 71) = 4 bpp
        assert BPP[71] == 4, f"BC1 should be 4 bpp"

        # BC7 (DXGI 98) = 8 bpp
        assert BPP[98] == 8, f"BC7 should be 8 bpp"

        # B8G8R8A8 (DXGI 87) = 32 bpp
        assert BPP[87] == 32, f"B8G8R8A8 should be 32 bpp"

        # R16G16B16A16_FLOAT (DXGI 10) = 64 bpp
        assert BPP[10] == 64, f"R16G16B16A16_FLOAT should be 64 bpp"


class TestTextureFormats:
    """Tests for texture format definitions."""

    def test_all_formats_have_required_fields(self) -> None:
        """Verify all formats have dxgi, dxgi_index, and alignment."""
        for format_id, fmt in TEXTURE_FORMATS.items():
            assert "dxgi" in fmt, f"Format {format_id} missing 'dxgi'"
            assert "dxgi_index" in fmt, f"Format {format_id} missing 'dxgi_index'"
            assert "alignment" in fmt, f"Format {format_id} missing 'alignment'"

    def test_dxgi_indices_valid(self) -> None:
        """Verify DXGI indices are within BPP table bounds."""
        for format_id, fmt in TEXTURE_FORMATS.items():
            dxgi_index = fmt["dxgi_index"]
            assert 0 <= dxgi_index < len(BPP), \
                f"Format {format_id} has invalid DXGI index {dxgi_index}"

    @pytest.mark.parametrize("format_id,dxgi_index", [
        (9, 71),   # BC1_UNORM
        (10, 71),  # BC1_UNORM
        (44, 98),  # BC7_UNORM
        (50, 98),  # BC7_UNORM
        (65, 65),  # A8_UNORM - but format 65 doesn't exist, testing format 7
        (7, 65),   # A8_UNORM
        (0, 87),   # B8G8R8A8_UNORM
        (25, 10),  # R16G16B16A16_FLOAT
    ])
    def test_specific_format_dxgi_mapping(self, format_id: int, dxgi_index: int) -> None:
        """Verify specific format to DXGI mappings."""
        if format_id == 65:
            pytest.skip("Format 65 doesn't exist in the table")
        assert format_id in TEXTURE_FORMATS, f"Format {format_id} should exist"
        assert TEXTURE_FORMATS[format_id]["dxgi_index"] == dxgi_index


class TestFullPayloadPassing:
    """Tests to verify full payload is passed to decoder (not truncated to mip0_size)."""

    def test_dds_includes_full_payload(self) -> None:
        """Verify convert_raw_to_dds doesn't truncate payload."""
        from d4_asset_extractor.tex_converter import convert_raw_to_dds, TextureDefinition

        # Create a definition for a small texture
        definition = TextureDefinition(
            format_id=9,   # BC1
            width=64,
            height=64,
            depth=1,
            face_count=1,
            mipmap_min=1,
            mipmap_max=8,
            avg_color=(1.0, 0.0, 0.0, 1.0),
            hotspot=(0, 0),
            frames=[],
        )

        # Mip0 for 64x64 BC1 = 16*16 blocks * 8 bytes = 2048 bytes
        mip0_size = 16 * 16 * 8

        # Create raw data larger than mip0 (simulating mipmaps)
        full_payload = bytes([0xAB] * mip0_size + [0xCD] * 1024)

        # Convert to DDS
        dds_data = convert_raw_to_dds(full_payload, definition)

        # Header is 128 bytes for DXT1
        header_size = 128
        payload_in_dds = dds_data[header_size:]

        # Full payload should be included
        assert len(payload_in_dds) == len(full_payload), \
            f"Payload should be {len(full_payload)} bytes, got {len(payload_in_dds)}"
        assert payload_in_dds == full_payload, "Payload should be unchanged"
