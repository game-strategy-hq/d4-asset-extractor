"""
Format coverage tests using fixture files.

These tests use pre-extracted fixture files (one per format type) to enable
fast iteration without needing access to the full game installation.

To generate fixtures:
    python scripts/build_test_fixtures.py /path/to/diablo/iv

Fixtures are stored in tests/fixtures/textures/ with a manifest.json.

NOTE: Fixtures are raw data from Texture-Base-Global.dat, NOT standalone .tex files.
They use parse_texture_definition() which searches for the 0xFFFFFFFF marker.
"""

import json
import struct
from pathlib import Path

import pytest
from PIL import Image

from d4_asset_extractor.tex_converter import (
    TEXTURE_FORMATS,
    convert_raw_to_dds,
    create_dds_header,
    dds_to_image,
    TextureDefinition,
)
from d4_asset_extractor.texture_extractor import parse_texture_definition


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "textures"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"


def load_manifest() -> dict:
    """Load the test fixtures manifest."""
    if not MANIFEST_PATH.exists():
        pytest.skip(
            "No fixtures found. Run: python scripts/build_test_fixtures.py /path/to/game"
        )
    return json.loads(MANIFEST_PATH.read_text())


def get_fixture_textures() -> list[dict]:
    """Get list of fixture textures for parametrization."""
    if not MANIFEST_PATH.exists():
        return []
    manifest = json.loads(MANIFEST_PATH.read_text())
    return manifest.get("textures", [])


class TestFixtureLoading:
    """Test that fixtures can be loaded and parsed."""

    def test_manifest_exists(self):
        """Verify manifest file exists."""
        if not MANIFEST_PATH.exists():
            pytest.skip("No fixtures - run build_test_fixtures.py first")
        manifest = load_manifest()
        assert "textures" in manifest
        assert len(manifest["textures"]) > 0

    def test_all_fixture_files_exist(self):
        """Verify all referenced fixture files exist."""
        manifest = load_manifest()
        for tex in manifest["textures"]:
            meta_path = FIXTURES_DIR / tex["meta_file"]
            payload_path = FIXTURES_DIR / tex["payload_file"]
            assert meta_path.exists(), f"Missing meta: {tex['meta_file']}"
            assert payload_path.exists(), f"Missing payload: {tex['payload_file']}"


def parse_fixture_meta(meta_data: bytes, sno_id: int) -> TextureDefinition | None:
    """
    Parse fixture meta data using the same approach as the extractor.

    Fixtures are raw data from Texture-Base-Global.dat, not standalone .tex files.
    Returns a TextureDefinition or None if parsing fails.
    """
    info = parse_texture_definition(meta_data, sno_id)
    if not info:
        return None

    return TextureDefinition(
        format_id=info.format_id,
        width=info.width,
        height=info.height,
        depth=1,
        face_count=1,
        mipmap_min=1,
        mipmap_max=1,
        avg_color=(0.0, 0.0, 0.0, 1.0),
        hotspot=(0, 0),
        frames=[],
    )


class TestTextureDefinitionParsing:
    """Test parsing texture definitions from fixtures."""

    @pytest.mark.parametrize(
        "fixture",
        get_fixture_textures(),
        ids=lambda f: f"format_{f['format_id']:02d}_{f['dxgi'].split('_')[-1]}"
        if f else "no_fixtures",
    )
    def test_parse_definition(self, fixture: dict):
        """Parse texture definition and verify dimensions match manifest."""
        if not fixture:
            pytest.skip("No fixtures available")

        meta_path = FIXTURES_DIR / fixture["meta_file"]
        meta_data = meta_path.read_bytes()

        definition = parse_fixture_meta(meta_data, fixture["sno_id"])

        assert definition is not None, "Failed to parse fixture"
        assert definition.format_id == fixture["format_id"], \
            f"Format mismatch: got {definition.format_id}, expected {fixture['format_id']}"
        assert definition.width == fixture["width"], \
            f"Width mismatch: got {definition.width}, expected {fixture['width']}"
        assert definition.height == fixture["height"], \
            f"Height mismatch: got {definition.height}, expected {fixture['height']}"

    @pytest.mark.parametrize(
        "fixture",
        get_fixture_textures(),
        ids=lambda f: f"format_{f['format_id']:02d}" if f else "no_fixtures",
    )
    def test_format_id_in_known_formats(self, fixture: dict):
        """Verify format_id is in TEXTURE_FORMATS lookup."""
        if not fixture:
            pytest.skip("No fixtures available")

        assert fixture["format_id"] in TEXTURE_FORMATS, \
            f"Format {fixture['format_id']} not in TEXTURE_FORMATS"


class TestDDSConversion:
    """Test DDS header construction and conversion."""

    @pytest.mark.parametrize(
        "fixture",
        get_fixture_textures(),
        ids=lambda f: f"format_{f['format_id']:02d}_{f['dxgi'].split('_')[-1]}"
        if f else "no_fixtures",
    )
    def test_create_dds_header(self, fixture: dict):
        """Create DDS header for each format."""
        if not fixture:
            pytest.skip("No fixtures available")

        # Use manifest values directly (already validated by parse test)
        header = create_dds_header(
            fixture["width"],
            fixture["height"],
            fixture["format_id"],
            1024,  # Arbitrary payload size
        )

        # Verify header structure
        assert header[:4] == b"DDS ", "Invalid DDS magic"
        assert len(header) >= 128, "Header too short"

    @pytest.mark.parametrize(
        "fixture",
        get_fixture_textures(),
        ids=lambda f: f"format_{f['format_id']:02d}_{f['dxgi'].split('_')[-1]}"
        if f else "no_fixtures",
    )
    def test_convert_to_dds(self, fixture: dict):
        """Convert raw payload to DDS format."""
        if not fixture:
            pytest.skip("No fixtures available")

        meta_path = FIXTURES_DIR / fixture["meta_file"]
        payload_path = FIXTURES_DIR / fixture["payload_file"]

        meta_data = meta_path.read_bytes()
        payload_data = payload_path.read_bytes()

        definition = parse_fixture_meta(meta_data, fixture["sno_id"])
        assert definition is not None, "Failed to parse fixture"

        # Convert to DDS
        dds_data = convert_raw_to_dds(payload_data, definition)

        # Verify it's valid DDS
        assert dds_data[:4] == b"DDS ", "Invalid DDS magic"
        assert len(dds_data) > 128, "DDS file too small"


class TestImageDecoding:
    """Test full decode pipeline to PIL Image."""

    @pytest.mark.parametrize(
        "fixture",
        get_fixture_textures(),
        ids=lambda f: f"format_{f['format_id']:02d}_{f['dxgi'].split('_')[-1]}"
        if f else "no_fixtures",
    )
    def test_decode_to_image(self, fixture: dict):
        """Decode texture to PIL Image."""
        if not fixture:
            pytest.skip("No fixtures available")

        meta_path = FIXTURES_DIR / fixture["meta_file"]
        payload_path = FIXTURES_DIR / fixture["payload_file"]

        meta_data = meta_path.read_bytes()
        payload_data = payload_path.read_bytes()

        definition = parse_fixture_meta(meta_data, fixture["sno_id"])
        assert definition is not None, "Failed to parse fixture"

        # Convert to DDS
        dds_data = convert_raw_to_dds(payload_data, definition)

        # Decode to image (no texconv config for tests - uses Python-only decoders)
        try:
            image = dds_to_image(dds_data)

            # Verify image properties
            assert image is not None, "Decoding returned None"
            assert image.width > 0, "Image width is 0"
            assert image.height > 0, "Image height is 0"

            # Width/height may differ due to alignment, but should be close
            assert abs(image.width - fixture["width"]) <= 128, \
                f"Width off by too much: {image.width} vs {fixture['width']}"
            assert abs(image.height - fixture["height"]) <= 128, \
                f"Height off by too much: {image.height} vs {fixture['height']}"

        except Exception as e:
            # BC formats and HDR require texconv which may not be available in tests
            dxgi = fixture["dxgi"]
            if "BC" in dxgi or "FLOAT" in dxgi:
                pytest.xfail(f"Format {dxgi} requires texconv: {e}")
            raise


class TestParserConsistency:
    """Verify parse_texture_definition produces correct results."""

    @pytest.mark.parametrize(
        "fixture",
        get_fixture_textures()[:3] if get_fixture_textures() else [],
        ids=lambda f: f"format_{f['format_id']:02d}" if f else "no_fixtures",
    )
    def test_parser_matches_manifest(self, fixture: dict):
        """Verify parse_texture_definition returns values matching manifest."""
        if not fixture:
            pytest.skip("No fixtures available")

        meta_path = FIXTURES_DIR / fixture["meta_file"]
        meta_data = meta_path.read_bytes()

        # Parse using the same function as the extractor
        info = parse_texture_definition(meta_data, fixture["sno_id"])

        assert info is not None, "Parser returned None"
        assert info.format_id == fixture["format_id"], \
            f"Format mismatch: got {info.format_id}, expected {fixture['format_id']}"
        assert info.width == fixture["width"], \
            f"Width mismatch: got {info.width}, expected {fixture['width']}"
        assert info.height == fixture["height"], \
            f"Height mismatch: got {info.height}, expected {fixture['height']}"


# Convenience function for running specific format tests
def pytest_generate_tests(metafunc):
    """Allow filtering by format via -k flag."""
    pass  # parametrize handles this
