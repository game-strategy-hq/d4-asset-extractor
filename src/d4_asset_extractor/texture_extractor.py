"""
Texture extraction pipeline for Diablo IV.

This module provides a high-level API for extracting textures from D4 CASC storage
using pure Python (no external tools required for most formats).
"""

import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from .casc_reader import D4CASCReader, read_cascfile
from .tex_converter import TEXTURE_FORMATS, calculate_mip0_size, create_dds_header, dds_to_image
from .tvfs_parser import VfsRootEntry, parse_tvfs_files, parse_core_toc


class TextureExtractionError(Exception):
    """Error during texture extraction with details about the failure."""
    pass


class InterleavedBC1Error(TextureExtractionError):
    """BC1 texture uses D4's proprietary interleaved format (requires Windows texconv)."""
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

    The definition has a variable-length header. We find the 0xFFFFFFFF marker
    and parse relative to that position.
    """
    # Find 0xFFFFFFFF marker in the data
    marker_offset = -1
    for i in range(0, min(256, len(data) - 4), 4):
        val = struct.unpack("<I", data[i : i + 4])[0]
        if val == 0xFFFFFFFF:
            marker_offset = i
            break

    if marker_offset == -1:
        return None

    # The structure relative to marker:
    # marker-8: SNO ID (we use the passed sno_id instead)
    # marker: 0xFFFFFFFF
    # marker+4: format_id
    # marker+8: volume slices
    # marker+12: width, height
    # etc.
    sno_id_offset = marker_offset - 8
    if sno_id_offset < 0:
        return None

    base = sno_id_offset

    # Validate we have enough data
    if base + 0x30 > len(data):
        return None

    # Check for 0xFFFFFFFF marker at base+8
    marker = struct.unpack("<I", data[base + 8 : base + 12])[0]
    if marker != 0xFFFFFFFF:
        return None

    format_id = struct.unpack("<I", data[base + 12 : base + 16])[0]
    width = struct.unpack("<H", data[base + 20 : base + 22])[0]
    height = struct.unpack("<H", data[base + 22 : base + 24])[0]
    depth = struct.unpack("<I", data[base + 24 : base + 28])[0]
    face_count = data[base + 28] if base + 28 < len(data) else 1
    mipmap_min = data[base + 29] if base + 29 < len(data) else 1
    mipmap_max = data[base + 30] if base + 30 < len(data) else 1

    # Average color
    avg_r = avg_g = avg_b = avg_a = 0.0
    if base + 0x44 <= len(data):
        avg_r = struct.unpack("<f", data[base + 0x34 : base + 0x38])[0]
        avg_g = struct.unpack("<f", data[base + 0x38 : base + 0x3C])[0]
        avg_b = struct.unpack("<f", data[base + 0x3C : base + 0x40])[0]
        avg_a = struct.unpack("<f", data[base + 0x40 : base + 0x44])[0]

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
    Parse frame/slice data from a texture definition.

    Scans for UV coordinate rectangles that define sub-regions of the texture.
    These are used for texture atlases containing multiple icons/sprites.

    Args:
        data: Raw texture definition data
        tex_width: Texture width in pixels
        tex_height: Texture height in pixels

    Returns:
        List of TextureFrame objects, deduplicated and sorted by position
    """
    frames = []
    seen = set()  # Track unique frames by (x, y, w, h)

    for i in range(0, len(data) - 16, 4):
        try:
            u0 = struct.unpack("<f", data[i : i + 4])[0]
            v0 = struct.unpack("<f", data[i + 4 : i + 8])[0]
            u1 = struct.unpack("<f", data[i + 8 : i + 12])[0]
            v1 = struct.unpack("<f", data[i + 12 : i + 16])[0]

            # Valid UV rectangle check
            if not (0.0 <= u0 < u1 <= 1.0 and 0.0 <= v0 < v1 <= 1.0):
                continue

            # Skip degenerate or full-texture frames
            if u1 - u0 < 0.02 or v1 - v0 < 0.02:
                continue
            if u0 < 0.01 and v0 < 0.01 and u1 > 0.99 and v1 > 0.99:
                continue

            # Calculate pixel bounds
            x = int(u0 * tex_width)
            y = int(v0 * tex_height)
            w = int((u1 - u0) * tex_width)
            h = int((v1 - v0) * tex_height)

            # Skip tiny or oversized frames
            if w < 10 or h < 10:
                continue
            if w > tex_width * 0.9 or h > tex_height * 0.9:
                continue

            # Deduplicate by bounds (allow 2px tolerance)
            key = (x // 2, y // 2, w // 2, h // 2)
            if key in seen:
                continue
            seen.add(key)

            frames.append(
                TextureFrame(
                    index=len(frames),
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
        except struct.error:
            pass

    # Sort by position (top-left to bottom-right)
    frames.sort(key=lambda f: (f.y, f.x))
    for i, frame in enumerate(frames):
        frame.index = i

    return frames


class TextureExtractor:
    """
    High-level texture extraction from Diablo IV CASC storage.

    Memory optimized: Uses lazy loading and doesn't keep large data in memory.
    """

    def __init__(self, game_dir: Path):
        """Initialize the extractor with the game directory."""
        self.game_dir = Path(game_dir)
        self.reader = D4CASCReader(game_dir)

        # Only store lightweight references, not full data
        self._vfs2_ckey: Optional[str] = None
        self._tex_base_entry: Optional[VfsRootEntry] = None
        self._coretoc_entry: Optional[VfsRootEntry] = None

        # Lightweight indexes (just offsets, not full data)
        self.texture_index: dict[int, tuple[int, int]] = {}  # sno_id -> (offset, size)
        self._payload_ekeys: dict[int, VfsRootEntry] = {}  # sno_id -> VfsRootEntry
        self._sno_names: dict[int, str] = {}  # sno_id -> name (only for textures)

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

    def _build_texture_index(self) -> None:
        """Build texture definition index from Texture-Base-Global.dat header."""
        if not self._tex_base_entry:
            return

        # Read just the header of Texture-Base-Global.dat
        tex_base_data = self._read_vfs_entry(self._tex_base_entry)
        if not tex_base_data:
            return

        magic = struct.unpack("<I", tex_base_data[:4])[0]
        if magic != 0x44CF00F5:
            return

        entry_count = struct.unpack("<I", tex_base_data[4:8])[0]
        index_offset = 8
        def_offset = 8 + entry_count * 8

        for i in range(entry_count):
            idx_pos = index_offset + i * 8
            sno_id = struct.unpack("<I", tex_base_data[idx_pos : idx_pos + 4])[0]
            def_size = struct.unpack("<I", tex_base_data[idx_pos + 4 : idx_pos + 8])[0]
            self.texture_index[sno_id] = (def_offset, def_size)
            def_offset += def_size

        # We need to keep a reference to read definitions later
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

    def _find_best_payload_offset(
        self,
        payload: bytes,
        mip0_size: int,
        format_id: int,
        width: int,
        height: int,
        max_search: int = 100000,
        step: int = 1024,
    ) -> int:
        """
        Find the best payload offset for high-ratio textures.

        Some D4 textures store mipmaps with non-standard padding, causing
        the mip0 data to not be at offset 0. This method scans offsets
        to find the one that produces the most detailed/varied image.

        Args:
            payload: Raw payload bytes
            mip0_size: Expected size of mip level 0
            format_id: D4 texture format ID
            width: Texture width in pixels
            height: Texture height in pixels
            max_search: Maximum offset to search
            step: Step size between offset checks

        Returns:
            Best offset for mip0 data
        """
        if len(payload) <= mip0_size:
            return 0

        best_offset = 0
        best_score = 0.0

        max_offset = min(max_search, len(payload) - mip0_size)

        for offset in range(0, max_offset + 1, step):
            data = payload[offset : offset + mip0_size]
            if len(data) < mip0_size:
                break

            try:
                header = create_dds_header(width, height, format_id, len(data))
                dds = header + data

                img = Image.open(BytesIO(dds))
                img.load()
                arr = np.array(img.convert("RGBA"))

                # Score by variance of non-transparent pixels
                non_zero = arr[arr[:, :, 3] > 0]
                if len(non_zero) > 0:
                    variance = float(np.var(non_zero[:, :3]))
                    if variance > best_score:
                        best_score = variance
                        best_offset = offset
            except Exception:
                pass

        return best_offset

    def extract_texture(
        self,
        sno_id: int,
        crop: bool = True,
    ) -> Optional[Image.Image]:
        """
        Extract a texture as a PIL Image.

        Args:
            sno_id: The SNO ID of the texture
            crop: Whether to crop to actual texture dimensions

        Returns:
            PIL Image or None if extraction fails
        """
        # Get texture info
        tex_info = self.get_texture_info(sno_id)
        if not tex_info:
            return None

        # Check format is supported
        if tex_info.format_id not in TEXTURE_FORMATS:
            return None

        # Read payload
        if sno_id not in self._payload_ekeys:
            return None

        payload_data = self._read_vfs_entry(self._payload_ekeys[sno_id])
        if not payload_data:
            return None

        # Calculate expected mip0 size
        mip0_size = calculate_mip0_size(tex_info.width, tex_info.height, tex_info.format_id)
        if mip0_size <= 0:
            return None

        # Check payload ratio - high ratio textures have non-standard row padding
        payload_ratio = len(payload_data) / mip0_size
        is_bc1 = tex_info.format_id in (9, 10, 46, 47)

        try:
            # Check for problematic BC1 textures with interleaved storage
            # These have ~50% zero blocks and can't be decoded correctly
            if is_bc1:
                zero_blocks = sum(
                    1 for i in range(0, min(len(payload_data), 8000), 8)
                    if all(b == 0 for b in payload_data[i:i+8])
                )
                total_blocks = min(len(payload_data), 8000) // 8
                zero_ratio = zero_blocks / total_blocks if total_blocks > 0 else 0

                # If >30% zero blocks, this is D4's interleaved BC1 format
                # which requires Windows texconv.exe to decode
                if zero_ratio > 0.3:
                    raise InterleavedBC1Error(
                        f"BC1 texture uses D4's interleaved format "
                        f"({zero_ratio:.0%} zero blocks). "
                        f"Requires Windows texconv.exe to decode."
                    )

            # Standard texture: use DDS/PIL
            if len(payload_data) > mip0_size:
                texture_data = payload_data[:mip0_size]
            else:
                texture_data = payload_data

            dds_header = create_dds_header(
                tex_info.width, tex_info.height, tex_info.format_id, len(texture_data),
            )
            dds_data = dds_header + texture_data
            img = dds_to_image(dds_data)

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
    ) -> bool:
        """
        Extract a texture and save to file.

        Args:
            sno_id: The SNO ID of the texture
            output_path: Output file path
            crop: Whether to crop to actual texture dimensions

        Returns:
            True if successful
        """
        img = self.extract_texture(sno_id, crop=crop)
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
