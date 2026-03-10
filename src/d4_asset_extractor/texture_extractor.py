"""
Texture extraction pipeline for Diablo IV.

This module provides a high-level API for extracting textures from D4 CASC storage.
Uses texconv as the primary decoder for BC-compressed textures when available.
"""

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from .casc_reader import D4CASCReader, read_cascfile
from .tex_converter import TEXTURE_FORMATS, calculate_mip0_size, create_dds_header, dds_to_image
from .texconv import TexconvConfig, TexconvWrapper, is_available as texconv_is_available
from .tvfs_parser import (
    VfsRootEntry,
    parse_tvfs_files,
    parse_core_toc,
    parse_encrypted_snos,
    parse_shared_payloads_mapping,
)


class TextureExtractionError(Exception):
    """Error during texture extraction with details about the failure."""
    pass


class InterleavedBC1Error(TextureExtractionError):
    """BC1 texture uses D4's proprietary interleaved format (requires Windows texconv)."""
    pass


class EncryptedSNOError(TextureExtractionError):
    """SNO is encrypted and cannot be extracted without decryption keys."""
    pass


class SharedPayloadError(TextureExtractionError):
    """Error when following shared payload redirect."""
    pass


@dataclass
class TextureFrame:
    """A frame/slice within a texture atlas."""

    index: int
    x: int
    y: int
    width: int
    height: int
    u0: float
    v0: float
    u1: float
    v1: float


@dataclass
class TextureInfo:
    """Parsed texture information from Texture-Base-Global.dat."""

    sno_id: int
    format_id: int
    width: int
    height: int
    depth: int
    face_count: int
    mipmap_min: int
    mipmap_max: int
    avg_color: tuple[float, float, float, float]
    definition_offset: int
    definition_size: int


def parse_texture_definition(data: bytes, sno_id: int) -> Optional[TextureInfo]:
    """
    Parse a texture definition from Texture-Base-Global.dat.

    Field offsets are derived from the TextureDefinition type in d4data's definitions.json
    (type hash 3631735738). The structure is parsed using fixed offsets rather than
    marker-based heuristics.

    Source: https://github.com/DiabloTools/d4data
        - definitions.json: TextureDefinition type with field offsets
        - parse.js: parseCombinedMetaFile() and readStructure()

    TextureDefinition field offsets (from definitions.json):
        offset  0: SNO ID (4 bytes) - validated against expected sno_id
        offset  8: sUIStylePreset
        offset 12: eTexFormat (4 bytes) - texture compression format
        offset 16: dwVolumeXSlices (2 bytes)
        offset 18: dwVolumeYSlices (2 bytes)
        offset 20: dwWidth (2 bytes)
        offset 22: dwHeight (2 bytes)
        offset 24: dwDepth (4 bytes)
        offset 28: dwFaceCount (1 byte)
        offset 29: dwMipMapLevelMin (1 byte)
        offset 30: dwMipMapLevelMax (1 byte)
        offset 40: rgbavalAvgColor (16 bytes - 4 floats)
    """
    if len(data) < 56:  # Minimum size for required fields
        return None

    # Validate SNO ID at offset 0
    stored_sno_id = struct.unpack("<I", data[0:4])[0]
    if stored_sno_id != sno_id:
        return None

    # Parse fields using fixed offsets from TextureDefinition type
    format_id = struct.unpack("<I", data[12:16])[0]
    width = struct.unpack("<H", data[20:22])[0]
    height = struct.unpack("<H", data[22:24])[0]
    depth = struct.unpack("<I", data[24:28])[0]
    face_count = data[28] if len(data) > 28 else 1
    mipmap_min = data[29] if len(data) > 29 else 0
    mipmap_max = data[30] if len(data) > 30 else 0

    # Average color at offset 40 (rgbavalAvgColor)
    avg_r = avg_g = avg_b = avg_a = 0.0
    if len(data) >= 56:
        avg_r = struct.unpack("<f", data[40:44])[0]
        avg_g = struct.unpack("<f", data[44:48])[0]
        avg_b = struct.unpack("<f", data[48:52])[0]
        avg_a = struct.unpack("<f", data[52:56])[0]

    return TextureInfo(
        sno_id=sno_id,
        format_id=format_id,
        width=width,
        height=height,
        depth=depth,
        face_count=face_count,
        mipmap_min=mipmap_min,
        mipmap_max=mipmap_max,
        avg_color=(avg_r, avg_g, avg_b, avg_a),
        definition_offset=0,
        definition_size=len(data),
    )


def parse_texture_frames(
    data: bytes, tex_width: int, tex_height: int
) -> list[TextureFrame]:
    """
    Parse frame/slice data from a texture definition in Texture-Base-Global.dat.

    The structure in Texture-Base-Global.dat differs from standalone .tex files.
    We search for consecutive valid frame structures by looking for UV coordinate patterns.

    Args:
        data: Raw texture definition data from Texture-Base-Global.dat
        tex_width: Texture width in pixels
        tex_height: Texture height in pixels

    Returns:
        List of TextureFrame objects
    """
    frames = []
    frame_size = 0x24  # 36 bytes per frame

    if len(data) < 0xC0:
        return frames

    # Search for first valid frame by scanning for UV coordinate patterns
    # A valid frame has: image_handle (4 bytes), u0, v0, u1, v1 (4 floats)
    # where all UVs are in 0-1 range and u1 > u0, v1 > v0
    frame_start = -1

    for offset in range(0xC0, len(data) - frame_size, 4):
        try:
            u0 = struct.unpack_from("<f", data, offset + 0x4)[0]
            v0 = struct.unpack_from("<f", data, offset + 0x8)[0]
            u1 = struct.unpack_from("<f", data, offset + 0xc)[0]
            v1 = struct.unpack_from("<f", data, offset + 0x10)[0]

            # Check for valid UV coordinates (non-degenerate, proper range)
            # Note: 0.0 <= allows frames starting at atlas origin (0,0)
            if (0.0 <= u0 < 1.0 and 0.0 <= v0 < 1.0 and
                0.0 < u1 <= 1.0 and 0.0 < v1 <= 1.0 and
                u1 > u0 and v1 > v0):
                frame_start = offset
                break
        except struct.error:
            continue

    if frame_start < 0:
        return frames

    # Parse frames from the found start position
    frame_idx = 0
    offset = frame_start

    while offset + frame_size <= len(data):
        try:
            image_handle = struct.unpack_from("<I", data, offset)[0]
            u0 = struct.unpack_from("<f", data, offset + 0x4)[0]
            v0 = struct.unpack_from("<f", data, offset + 0x8)[0]
            u1 = struct.unpack_from("<f", data, offset + 0xc)[0]
            v1 = struct.unpack_from("<f", data, offset + 0x10)[0]

            # Stop if we hit invalid UV data (end of frames)
            if not (0.0 <= u0 <= 1.0 and 0.0 <= v0 <= 1.0 and
                    0.0 <= u1 <= 1.0 and 0.0 <= v1 <= 1.0):
                break

            # Skip frames with degenerate dimensions
            if u1 <= u0 or v1 <= v0:
                offset += frame_size
                continue

            # Calculate pixel bounds (floor for top-left, ceil for bottom-right)
            x = math.floor(u0 * tex_width)
            y = math.floor(v0 * tex_height)
            x1 = math.ceil(u1 * tex_width)
            y1 = math.ceil(v1 * tex_height)
            w = x1 - x
            h = y1 - y

            if w > 0 and h > 0:
                frames.append(
                    TextureFrame(
                        index=frame_idx,
                        x=x,
                        y=y,
                        width=w,
                        height=h,
                        u0=u0,
                        v0=v0,
                        u1=u1,
                        v1=v1,
                    )
                )
                frame_idx += 1

            offset += frame_size
        except struct.error:
            break

    return frames


class TextureExtractor:
    """
    High-level texture extraction from Diablo IV CASC storage.

    Memory optimized: Uses lazy loading and doesn't keep large data in memory.
    Uses texconv as the primary decoder for BC-compressed textures when available.
    """

    def __init__(
        self,
        game_dir: Path,
        texconv_config: Optional[TexconvConfig] = None,
    ):
        """
        Initialize the extractor with the game directory.

        Args:
            game_dir: Path to Diablo IV installation directory
            texconv_config: Optional texconv configuration for BC texture decoding
        """
        self.game_dir = Path(game_dir)
        self.reader = D4CASCReader(game_dir)
        self.texconv_config = texconv_config
        self._texconv_wrapper: Optional[TexconvWrapper] = None

        # Only store lightweight references, not full data
        self._vfs2_ckey: Optional[str] = None
        self._tex_base_entry: Optional[VfsRootEntry] = None
        self._coretoc_entry: Optional[VfsRootEntry] = None
        self._encrypted_snos_entry: Optional[VfsRootEntry] = None
        self._shared_payloads_entry: Optional[VfsRootEntry] = None

        # Lightweight indexes (just offsets, not full data)
        self.texture_index: dict[int, tuple[int, int]] = {}  # sno_id -> (offset, size)
        self._payload_ekeys: dict[int, VfsRootEntry] = {}  # sno_id -> VfsRootEntry
        self._sno_names: dict[int, str] = {}  # sno_id -> name (only for textures)
        self._encrypted_sno_ids: set[int] = set()  # Set of encrypted SNO IDs
        self._shared_payload_redirects: dict[int, int] = {}  # source_sno -> target_sno

        self._init_indexes()

    def _init_indexes(self) -> None:
        """Build lightweight indexes without keeping large data in memory."""
        # Get VFS-2 ckey
        self._vfs2_ckey = self.reader.get_vfs_ckey("vfs-2")
        if not self._vfs2_ckey:
            raise ValueError("VFS-2 not found in build config")

        # Read VFS-2 to build minimal index
        vfs2_data = self.reader.read_by_ckey(self._vfs2_ckey)
        if not vfs2_data:
            raise ValueError("Could not read VFS-2 data")

        # Parse VFS to get file entries (we need to do this once)
        vfs_files = parse_tvfs_files(vfs2_data)

        # Extract just what we need
        self._tex_base_entry = vfs_files.get("Texture-Base-Global.dat")
        self._coretoc_entry = vfs_files.get("CoreTOC.dat")
        self._encrypted_snos_entry = vfs_files.get("EncryptedSNOs.dat")
        self._shared_payloads_entry = vfs_files.get("CoreTOCSharedPayloadsMapping.dat")

        if not self._tex_base_entry:
            raise ValueError("Texture-Base-Global.dat not found in VFS")

        # Build payload index (sno_id -> ekey for payload files)
        for path, entry in vfs_files.items():
            if path.startswith("payload/"):
                try:
                    sno_id = int(path.split("/")[1])
                    self._payload_ekeys[sno_id] = entry
                except ValueError:
                    pass

        # Free the large vfs_files dict
        del vfs_files
        del vfs2_data

        # Build texture definition index (lightweight - just offsets)
        self._build_texture_index()

        # Load SNO names only for textures
        self._load_texture_names()

        # Load encrypted SNO IDs
        self._load_encrypted_snos()

        # Load shared payload redirects
        self._load_shared_payloads()

    def _build_texture_index(self) -> None:
        """
        Build texture definition index from Texture-Base-Global.dat.

        The offset calculation follows d4data's parseCombinedMetaFile() logic:
        https://github.com/DiabloTools/d4data/blob/main/parse.js

        Key insight: Texture entries (snoGroup 44) require special alignment:
        1. Align file_data_offset to 8-byte boundary: ((offset + 7) // 8) * 8
        2. Add 8 extra bytes for textures (snoGroup == 44 in parse.js line 1335-1337)

        This differs from naive sequential offset calculation which produces
        incorrect offsets and wrong metadata values (e.g., 512x512 instead of 768x576).
        """
        if not self._tex_base_entry:
            return

        tex_base_data = self._read_vfs_entry(self._tex_base_entry)
        if not tex_base_data:
            return

        magic = struct.unpack("<I", tex_base_data[:4])[0]
        if magic != 0x44CF00F5:
            return

        entry_count = struct.unpack("<I", tex_base_data[4:8])[0]
        index_offset = 8

        # d4data's alignment calculation for combined meta files:
        # Start after the index table, then align each entry
        alignment = 8
        file_data_offset = 8 + entry_count * 8

        for i in range(entry_count):
            idx_pos = index_offset + i * 8
            sno_id = struct.unpack("<I", tex_base_data[idx_pos : idx_pos + 4])[0]
            def_size = struct.unpack("<I", tex_base_data[idx_pos + 4 : idx_pos + 8])[0]

            # Align to 8-byte boundary: ((offset + 8 - 1) / 8) * 8
            # Then add 8 for textures (snoGroup == 44)
            # Source: d4data parse.js lines 1328-1337
            aligned_offset = ((file_data_offset + alignment - 1) // alignment) * alignment
            actual_offset = aligned_offset + 8  # +8 for texture entries

            self.texture_index[sno_id] = (actual_offset, def_size)
            file_data_offset = actual_offset + def_size

        # Keep reference to read definitions later
        self._tex_base_data = tex_base_data

    def _load_texture_names(self) -> None:
        """Load SNO names only for textures (not all 684K entries)."""
        if not self._coretoc_entry:
            return

        coretoc_data = self._read_vfs_entry(self._coretoc_entry)
        if not coretoc_data:
            return

        # Parse CoreTOC
        sno_dict = parse_core_toc(coretoc_data)

        # Only keep names for textures (group 44)
        for sno_id, info in sno_dict.items():
            if info.group_id == 44 and sno_id in self.texture_index:
                self._sno_names[sno_id] = info.name

        del sno_dict
        del coretoc_data

    def _load_encrypted_snos(self) -> None:
        """Load the set of encrypted SNO IDs from EncryptedSNOs.dat."""
        if not self._encrypted_snos_entry:
            # File not found in VFS - this is OK, not all builds have it
            return

        encrypted_data = self._read_vfs_entry(self._encrypted_snos_entry)
        if not encrypted_data:
            return

        # Parse the encrypted SNO list
        self._encrypted_sno_ids = parse_encrypted_snos(encrypted_data)

        del encrypted_data

    def _load_shared_payloads(self) -> None:
        """Load shared payload redirects from CoreTOCSharedPayloadsMapping.dat."""
        if not self._shared_payloads_entry:
            # File not found in VFS - this is OK, not all builds have it
            return

        shared_data = self._read_vfs_entry(self._shared_payloads_entry)
        if not shared_data:
            return

        # Parse the shared payloads mapping
        self._shared_payload_redirects = parse_shared_payloads_mapping(shared_data)

        del shared_data

    def get_payload_sno_id(self, sno_id: int) -> int:
        """
        Get the actual SNO ID to use for payload lookup.

        Some textures share payloads with other textures. This method
        follows the redirect chain to find the actual payload location.

        Args:
            sno_id: The original texture SNO ID

        Returns:
            The SNO ID where the payload is actually stored
        """
        # Follow redirect chain (with loop detection)
        visited = set()
        current = sno_id

        while current in self._shared_payload_redirects:
            if current in visited:
                # Circular reference - shouldn't happen but be safe
                break
            visited.add(current)
            current = self._shared_payload_redirects[current]

        return current

    def has_shared_payload(self, sno_id: int) -> bool:
        """
        Check if a texture uses a shared payload from another texture.

        Args:
            sno_id: The SNO ID to check

        Returns:
            True if the texture redirects to another texture's payload
        """
        return sno_id in self._shared_payload_redirects

    @property
    def shared_payload_count(self) -> int:
        """Return the count of textures using shared payloads."""
        # Count only redirects where the source is a texture
        return len(
            set(self._shared_payload_redirects.keys()) & set(self.texture_index.keys())
        )

    def _read_vfs_entry(self, entry: VfsRootEntry) -> Optional[bytes]:
        """Read data for a VFS entry."""
        ekey_int = int.from_bytes(entry.ekey, "big")
        if ekey_int not in self.reader.file_table:
            return None

        info = self.reader.file_table[ekey_int]
        return read_cascfile(
            str(self.reader.data_path) + "/", info.data_file, info.offset
        )

    def get_texture_info(self, sno_id: int) -> Optional[TextureInfo]:
        """Get texture information for a given SNO ID."""
        if sno_id not in self.texture_index:
            return None

        def_offset, def_size = self.texture_index[sno_id]
        definition_data = self._tex_base_data[def_offset : def_offset + def_size]

        info = parse_texture_definition(definition_data, sno_id)
        if info:
            info.definition_offset = def_offset
            info.definition_size = def_size
        return info

    def get_texture_name(self, sno_id: int) -> Optional[str]:
        """Get the name of a texture by SNO ID."""
        return self._sno_names.get(sno_id)

    def is_encrypted(self, sno_id: int) -> bool:
        """
        Check if a texture SNO is encrypted.

        Args:
            sno_id: The SNO ID to check

        Returns:
            True if the SNO is in the encrypted list
        """
        return sno_id in self._encrypted_sno_ids

    @property
    def encrypted_texture_count(self) -> int:
        """Return the count of encrypted textures in the index."""
        return len(self._encrypted_sno_ids & set(self.texture_index.keys()))

    @property
    def texconv_available(self) -> bool:
        """Check if texconv is available for BC texture decoding."""
        if self._texconv_wrapper is None:
            self._texconv_wrapper = TexconvWrapper(self.texconv_config)
        return self._texconv_wrapper.is_available()

    def _get_texconv_wrapper(self) -> Optional[TexconvWrapper]:
        """Get the texconv wrapper if available."""
        if self._texconv_wrapper is None:
            self._texconv_wrapper = TexconvWrapper(self.texconv_config)
        return self._texconv_wrapper if self._texconv_wrapper.is_available() else None

    def list_textures(
        self, filter_pattern: Optional[str] = None
    ) -> list[tuple[int, str]]:
        """
        List available textures.

        Args:
            filter_pattern: Optional glob-style pattern to filter by name

        Returns:
            List of (sno_id, name) tuples
        """
        import fnmatch

        textures = []
        for sno_id, name in self._sno_names.items():
            if filter_pattern is None or fnmatch.fnmatch(name, filter_pattern):
                textures.append((sno_id, name))

        return sorted(textures, key=lambda x: x[1])

    def extract_texture(
        self,
        sno_id: int,
        crop: bool = True,
        skip_encrypted: bool = True,
    ) -> Optional[Image.Image]:
        """
        Extract a texture as a PIL Image.

        Args:
            sno_id: The SNO ID of the texture
            crop: Whether to crop to actual texture dimensions
            skip_encrypted: If True, return None for encrypted textures.
                           If False, raise EncryptedSNOError.

        Returns:
            PIL Image or None if extraction fails

        Raises:
            EncryptedSNOError: If skip_encrypted is False and the texture is encrypted
        """
        # Check if this SNO is encrypted
        if self.is_encrypted(sno_id):
            name = self.get_texture_name(sno_id) or f"sno_{sno_id}"
            if skip_encrypted:
                return None
            else:
                raise EncryptedSNOError(
                    f"Texture '{name}' (SNO {sno_id}) is encrypted. "
                    f"Cannot extract without decryption keys."
                )

        # Get texture info
        tex_info = self.get_texture_info(sno_id)
        if not tex_info:
            return None

        # Check format is supported
        if tex_info.format_id not in TEXTURE_FORMATS:
            return None

        # Get the actual payload SNO ID (may redirect to shared payload)
        payload_sno_id = self.get_payload_sno_id(sno_id)

        # Read payload from the resolved SNO ID
        if payload_sno_id not in self._payload_ekeys:
            return None

        payload_data = self._read_vfs_entry(self._payload_ekeys[payload_sno_id])
        if not payload_data:
            return None

        # Calculate expected mip0 size
        mip0_size = calculate_mip0_size(tex_info.width, tex_info.height, tex_info.format_id)
        if mip0_size <= 0:
            return None

        is_bc1 = tex_info.format_id in (9, 10, 46, 47)

        # Build DDS data
        dds_header = create_dds_header(
            tex_info.width, tex_info.height, tex_info.format_id, len(payload_data),
        )
        dds_data = dds_header + payload_data

        try:
            # Check for problematic BC1 textures with interleaved storage
            # These have ~50% zero blocks and can't be decoded correctly by Python decoders
            is_interleaved_bc1 = False
            if is_bc1:
                zero_blocks = sum(
                    1 for i in range(0, min(len(payload_data), 8000), 8)
                    if all(b == 0 for b in payload_data[i:i+8])
                )
                total_blocks = min(len(payload_data), 8000) // 8
                zero_ratio = zero_blocks / total_blocks if total_blocks > 0 else 0

                # If >30% zero blocks, this is D4's interleaved BC1 format
                if zero_ratio > 0.3:
                    is_interleaved_bc1 = True

                    # Try texconv first for interleaved BC1
                    wrapper = self._get_texconv_wrapper()
                    if wrapper:
                        try:
                            img = wrapper.convert_dds_to_image(dds_data)
                            if img.mode != "RGBA":
                                img = img.convert("RGBA")
                            if crop and (img.width > tex_info.width or img.height > tex_info.height):
                                img = img.crop((0, 0, tex_info.width, tex_info.height))
                            return img
                        except Exception:
                            pass  # Fall through to raise error

                    # No texconv available - raise error for caller
                    raise InterleavedBC1Error(
                        f"BC1 texture uses D4's interleaved format "
                        f"({zero_ratio:.0%} zero blocks). "
                        f"Requires texconv.exe to decode. "
                        f"Install from https://github.com/Microsoft/DirectXTex/releases"
                    )

            # Standard texture: use dds_to_image (texconv primary, Python fallback)
            img = dds_to_image(dds_data, texconv_config=self.texconv_config)

            # Convert to RGBA
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            # Crop to actual declared dimensions (stored width may include padding)
            if crop and (img.width > tex_info.width or img.height > tex_info.height):
                img = img.crop((0, 0, tex_info.width, tex_info.height))

            return img
        except InterleavedBC1Error:
            raise  # Re-raise for caller to handle
        except Exception:
            return None

    def extract_texture_to_file(
        self,
        sno_id: int,
        output_path: Path,
        crop: bool = True,
        skip_encrypted: bool = True,
    ) -> bool:
        """
        Extract a texture and save to file.

        Args:
            sno_id: The SNO ID of the texture
            output_path: Output file path
            crop: Whether to crop to actual texture dimensions
            skip_encrypted: If True, return False for encrypted textures.
                           If False, raise EncryptedSNOError.

        Returns:
            True if successful

        Raises:
            EncryptedSNOError: If skip_encrypted is False and the texture is encrypted
        """
        img = self.extract_texture(sno_id, crop=crop, skip_encrypted=skip_encrypted)
        if not img:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "PNG", optimize=True)
        return True

    def get_texture_frames(self, sno_id: int) -> list[TextureFrame]:
        """
        Get frame/slice data for a texture atlas.

        Args:
            sno_id: The SNO ID of the texture

        Returns:
            List of TextureFrame objects defining sub-regions
        """
        if sno_id not in self.texture_index:
            return []

        info = self.get_texture_info(sno_id)
        if not info:
            return []

        def_offset, def_size = self.texture_index[sno_id]
        definition_data = self._tex_base_data[def_offset : def_offset + def_size]

        return parse_texture_frames(definition_data, info.width, info.height)

    def slice_texture(
        self,
        sno_id: int,
        output_dir: Path,
        min_size: int = 16,
        max_size: int = 512,
    ) -> list[Path]:
        """
        Extract a texture atlas and slice it into individual icons.

        Args:
            sno_id: The SNO ID of the texture
            output_dir: Directory to save sliced icons
            min_size: Minimum icon dimension (skip smaller)
            max_size: Maximum icon dimension (skip larger)

        Returns:
            List of paths to saved icon files
        """
        img = self.extract_texture(sno_id)
        if not img:
            return []

        frames = self.get_texture_frames(sno_id)
        if not frames:
            return []

        name = self.get_texture_name(sno_id) or f"texture_{sno_id}"
        output_dir = Path(output_dir) / name
        output_dir.mkdir(parents=True, exist_ok=True)

        saved = []
        for frame in frames:
            # Filter by size
            if frame.width < min_size or frame.height < min_size:
                continue
            if frame.width > max_size or frame.height > max_size:
                continue

            # Crop frame from atlas
            try:
                icon = img.crop(
                    (frame.x, frame.y, frame.x + frame.width, frame.y + frame.height)
                )

                # Skip fully transparent icons
                if icon.mode == "RGBA":
                    bbox = icon.getbbox()
                    if not bbox:
                        continue

                # Save
                path = output_dir / f"{frame.index:03d}_{frame.width}x{frame.height}.png"
                icon.save(path, "PNG", optimize=True)
                saved.append(path)
            except Exception:
                pass

        return saved

    def extract_all_icons(
        self,
        output_dir: Path,
        filter_pattern: str = "2DUI*",
        min_size: int = 16,
        max_size: int = 256,
    ) -> dict[str, list[Path]]:
        """
        Extract all icons from texture atlases matching a pattern.

        Args:
            output_dir: Base directory for output
            filter_pattern: Glob pattern to filter textures
            min_size: Minimum icon dimension
            max_size: Maximum icon dimension

        Returns:
            Dict mapping texture name to list of saved icon paths
        """
        results = {}
        textures = self.list_textures(filter_pattern)

        for sno_id, name in textures:
            saved = self.slice_texture(sno_id, output_dir, min_size, max_size)
            if saved:
                results[name] = saved

        return results

    @property
    def version(self) -> str:
        """Get the game version string."""
        return self.reader.version
