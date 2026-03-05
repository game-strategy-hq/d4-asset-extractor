"""
TVFS (Table Virtual File System) parser for Diablo IV.

Based on CascLib's TVFSRootHandler.cs and D4RootHandler.cs.

References:
    - https://github.com/WoW-Tools/CascLib
    - https://wowdev.wiki/TVFS
"""

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TVFSHeader:
    """TVFS directory header."""
    magic: bytes  # "TVFS"
    format_version: int
    header_size: int
    ekey_size: int
    patch_key_size: int
    flags: int
    path_table_offset: int
    path_table_size: int
    vfs_table_offset: int
    vfs_table_size: int
    cft_table_offset: int
    cft_table_size: int
    max_depth: int
    est_table_offset: int
    est_table_size: int
    cft_offs_size: int = 0
    est_offs_size: int = 0
    path_table: bytes = b""
    vfs_table: bytes = b""
    cft_table: bytes = b""


@dataclass
class VfsRootEntry:
    """VFS file entry."""
    ekey: bytes  # 9-byte truncated EKey
    content_offset: int
    content_length: int
    cft_offset: int


@dataclass
class PathTableEntry:
    """Path table entry."""
    name: bytes
    node_flags: int
    node_value: int


# Constants
TVFS_ROOT_MAGIC = b"TVFS"
TVFS_PTE_PATH_SEPARATOR_PRE = 0x0001
TVFS_PTE_PATH_SEPARATOR_POST = 0x0002
TVFS_PTE_NODE_VALUE = 0x0004
TVFS_FOLDER_NODE = 0x80000000
TVFS_FOLDER_SIZE_MASK = 0x7FFFFFFF


def read_int32_be(data: bytes, offset: int = 0) -> int:
    """Read big-endian 32-bit integer."""
    return struct.unpack(">I", data[offset:offset + 4])[0]


def read_int16_be(data: bytes, offset: int = 0) -> int:
    """Read big-endian 16-bit integer."""
    return struct.unpack(">H", data[offset:offset + 2])[0]


def read_int_be(data: bytes, num_bytes: int) -> int:
    """Read big-endian integer of variable size."""
    value = 0
    for i in range(num_bytes):
        value = (value << 8) | data[i]
    return value


def get_offset_field_size(table_size: int) -> int:
    """Determine offset field size based on table size."""
    if table_size > 0xFFFFFF:
        return 4
    elif table_size > 0xFFFF:
        return 3
    elif table_size > 0xFF:
        return 2
    else:
        return 1


def parse_tvfs_header(data: bytes) -> TVFSHeader:
    """Parse TVFS directory header."""
    if data[:4] != TVFS_ROOT_MAGIC:
        raise ValueError(f"Invalid TVFS magic: {data[:4]}")

    header = TVFSHeader(
        magic=data[0:4],
        format_version=data[4],
        header_size=data[5],
        ekey_size=data[6],
        patch_key_size=data[7],
        flags=read_int32_be(data, 8),
        path_table_offset=read_int32_be(data, 12),
        path_table_size=read_int32_be(data, 16),
        vfs_table_offset=read_int32_be(data, 20),
        vfs_table_size=read_int32_be(data, 24),
        cft_table_offset=read_int32_be(data, 28),
        cft_table_size=read_int32_be(data, 32),
        max_depth=read_int16_be(data, 36),
        est_table_offset=read_int32_be(data, 38),
        est_table_size=read_int32_be(data, 42),
    )

    header.cft_offs_size = get_offset_field_size(header.cft_table_size)
    header.est_offs_size = get_offset_field_size(header.est_table_size)

    # Read tables
    header.path_table = data[header.path_table_offset:header.path_table_offset + header.path_table_size]
    header.vfs_table = data[header.vfs_table_offset:header.vfs_table_offset + header.vfs_table_size]
    header.cft_table = data[header.cft_table_offset:header.cft_table_offset + header.cft_table_size]

    return header


def capture_path_entry(path_table: bytes, offset: int) -> tuple[PathTableEntry, int]:
    """Parse a single path table entry. Returns (entry, new_offset)."""
    entry = PathTableEntry(name=b"", node_flags=0, node_value=0)
    pos = offset

    # Check for pre-separator
    if pos < len(path_table) and path_table[pos] == 0:
        entry.node_flags |= TVFS_PTE_PATH_SEPARATOR_PRE
        pos += 1

    # Read name
    if pos < len(path_table) and path_table[pos] != 0xFF:
        name_len = path_table[pos]
        pos += 1
        entry.name = path_table[pos:pos + name_len]
        pos += name_len

    # Check for post-separator
    if pos < len(path_table) and path_table[pos] == 0:
        entry.node_flags |= TVFS_PTE_PATH_SEPARATOR_POST
        pos += 1

    # Check for node value
    if pos < len(path_table):
        if path_table[pos] == 0xFF:
            pos += 1
            entry.node_value = read_int32_be(path_table, pos)
            entry.node_flags |= TVFS_PTE_NODE_VALUE
            pos += 4
        elif path_table[pos] != 0:
            entry.node_flags |= TVFS_PTE_PATH_SEPARATOR_POST

    return entry, pos


def capture_vfs_span_entry(header: TVFSHeader, vfs_offset: int, span_idx: int) -> Optional[VfsRootEntry]:
    """Parse a VFS span entry."""
    vfs_table = header.vfs_table

    if vfs_offset >= len(vfs_table):
        return None

    span_count = vfs_table[vfs_offset]
    if span_count < 1 or span_count > 224:
        return None

    # Each span entry: 4 bytes offset + 4 bytes length + cft_offs_size bytes cft_offset
    entry_size = 4 + 4 + header.cft_offs_size
    entry_offset = vfs_offset + 1 + (span_idx * entry_size)

    if entry_offset + entry_size > len(vfs_table):
        return None

    content_offset = read_int32_be(vfs_table, entry_offset)
    content_length = read_int32_be(vfs_table, entry_offset + 4)
    cft_offset = read_int_be(vfs_table[entry_offset + 8:entry_offset + 8 + header.cft_offs_size], header.cft_offs_size)

    # Get EKey from CFT table
    cft_table = header.cft_table
    if cft_offset + header.ekey_size > len(cft_table):
        return None

    ekey = cft_table[cft_offset:cft_offset + header.ekey_size]

    return VfsRootEntry(
        ekey=ekey,
        content_offset=content_offset,
        content_length=content_length,
        cft_offset=cft_offset,
    )


def parse_tvfs_files(data: bytes) -> dict[str, VfsRootEntry]:
    """
    Parse TVFS data and return mapping of file paths to VFS entries.

    Returns:
        Dict mapping file path to VfsRootEntry
    """
    header = parse_tvfs_header(data)
    files = {}

    def parse_path_table(path_table: bytes, path_prefix: str = ""):
        """Recursively parse path table."""
        pos = 0

        # Skip initial folder marker if present
        if len(path_table) > 5 and path_table[0] == 0xFF:
            node_value = read_int32_be(path_table, 1)
            if node_value & TVFS_FOLDER_NODE:
                pos = 5

        while pos < len(path_table):
            entry, new_pos = capture_path_entry(path_table, pos)

            if new_pos == pos:
                # No progress, break to avoid infinite loop
                break

            # Build path
            path = path_prefix
            if entry.node_flags & TVFS_PTE_PATH_SEPARATOR_PRE:
                path += "/"
            path += entry.name.decode("ascii", errors="replace")
            if entry.node_flags & TVFS_PTE_PATH_SEPARATOR_POST:
                path += "/"

            if entry.node_flags & TVFS_PTE_NODE_VALUE:
                if entry.node_value & TVFS_FOLDER_NODE:
                    # It's a folder - recurse
                    folder_size = (entry.node_value & TVFS_FOLDER_SIZE_MASK) - 4
                    if folder_size > 0 and new_pos + folder_size <= len(path_table):
                        sub_table = path_table[new_pos:new_pos + folder_size]
                        parse_path_table(sub_table, path)
                        new_pos += folder_size
                else:
                    # It's a file - get VFS entry
                    vfs_entry = capture_vfs_span_entry(header, entry.node_value, 0)
                    if vfs_entry:
                        # Clean up path
                        clean_path = path.strip("/").replace("//", "/")
                        files[clean_path] = vfs_entry

            pos = new_pos

    parse_path_table(header.path_table)
    return files


def find_texture_files(files: dict[str, VfsRootEntry]) -> list[tuple[str, VfsRootEntry]]:
    """Find texture files (.tex) in parsed VFS."""
    textures = []
    for path, entry in files.items():
        if path.endswith(".tex") or "/44/" in path or "/Texture/" in path.lower():
            textures.append((path, entry))
    return textures


# SNO Group ID for textures
SNO_GROUP_TEXTURE = 44


@dataclass
class SNOInfo:
    """SNO (Scene Node Object) info."""
    group_id: int
    sno_id: int
    name: str
    ext: str = ""


SNO_EXTENSIONS = {
    1: ".acr", 6: ".ani", 7: ".an2", 8: ".ans", 9: ".app",
    27: ".prt", 29: ".pow", 33: ".scn", 42: ".stl", 43: ".srf",
    44: ".tex", 46: ".ui", 57: ".mat", 73: ".itm", 104: ".aff",
}


def parse_core_toc(data: bytes) -> dict[int, SNOInfo]:
    """
    Parse CoreTOC.dat to get SNO ID to name mappings.

    Returns:
        Dict mapping SNO ID to SNOInfo
    """
    sno_dict = {}
    pos = 0

    # Check for magic
    magic = struct.unpack("<I", data[0:4])[0]
    if magic == 0xBCDE6611:
        pos = 4

    num_groups = struct.unpack("<I", data[pos:pos + 4])[0]
    pos += 4

    # Read entry counts
    entry_counts = []
    for _ in range(num_groups):
        entry_counts.append(struct.unpack("<I", data[pos:pos + 4])[0])
        pos += 4

    # Read entry offsets
    entry_offsets = []
    for _ in range(num_groups):
        entry_offsets.append(struct.unpack("<I", data[pos:pos + 4])[0])
        pos += 4

    # Skip unk counts
    pos += num_groups * 4

    # Skip hashes if magic present
    if magic == 0xBCDE6611:
        pos += num_groups * 4

    # Skip unk1
    pos += 4

    # Calculate header size
    if magic == 0xBCDE6611:
        header_size = 4 + 4 + num_groups * (4 + 4 + 4 + 4) + 4
    else:
        header_size = 4 + num_groups * (4 + 4 + 4) + 4

    # Parse entries
    for group_idx in range(num_groups):
        if entry_counts[group_idx] > 0:
            entry_pos = entry_offsets[group_idx] + header_size

            for _ in range(entry_counts[group_idx]):
                sno_group = struct.unpack("<I", data[entry_pos:entry_pos + 4])[0]
                sno_id = struct.unpack("<I", data[entry_pos + 4:entry_pos + 8])[0]
                name_offset = struct.unpack("<I", data[entry_pos + 8:entry_pos + 12])[0]
                entry_pos += 12

                # Read name
                name_pos = entry_offsets[group_idx] + header_size + 12 * entry_counts[group_idx] + name_offset
                name_end = data.find(b"\x00", name_pos)
                name = data[name_pos:name_end].decode("utf-8", errors="replace")

                ext = SNO_EXTENSIONS.get(sno_group, f".{sno_group:03d}")

                sno_dict[sno_id] = SNOInfo(
                    group_id=sno_group,
                    sno_id=sno_id,
                    name=name,
                    ext=ext,
                )

    return sno_dict
