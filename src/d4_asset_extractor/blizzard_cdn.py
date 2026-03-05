"""
Direct Blizzard CDN access for D4 data extraction.

This module implements enough of the TACT/NGDP protocol to download
D4 textures directly from Blizzard's CDN without needing CASCConsole.

References:
    - https://wowdev.wiki/CASC
    - https://wowdev.wiki/TACT
"""

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import io

# D4 product code
PRODUCT = "fenris"

# CDN endpoints
PATCH_SERVER = "http://us.patch.battle.net:1119"
CDN_HOST = "http://us.cdn.blizzard.com"
CDN_PATH = "tpr/fenris"


@dataclass
class ArchiveIndex:
    """Index for locating files in archives."""
    # Maps 9-byte EKey prefix -> (archive_index, offset, size)
    entries: dict[bytes, tuple[int, int, int]]
    archives: list[str]  # Archive hashes


def fetch_file_index(file_index_hash: str) -> bytes:
    """Fetch the file index from CDN."""
    url = f"{CDN_HOST}/{CDN_PATH}/data/{file_index_hash[0:2]}/{file_index_hash[2:4]}/{file_index_hash}.index"
    with urlopen(url, timeout=60) as resp:
        return resp.read()


@dataclass
class FileIndex:
    """Index mapping 9-byte EKey prefixes to full 16-byte EKeys."""
    # Maps 9-byte prefix -> (full 16-byte EKey, size)
    entries: dict[bytes, tuple[bytes, int]]


def parse_file_index(index_data: bytes) -> FileIndex:
    """
    Parse file index to map 9-byte EKey prefixes to full 16-byte EKeys.

    The file-index contains entries that can be looked up by prefix.
    Files can then be fetched directly from CDN using the full 16-byte EKey.

    Scans the index to find valid entries (16-byte key + 4-byte size).
    """
    entries = {}

    # Scan for valid entries
    # Entry format: 16-byte EKey + 4-byte size (big-endian)
    # We scan and validate each potential entry

    pos = 0
    while pos + 20 <= len(index_data):
        ekey = index_data[pos:pos + 16]

        # Skip if this looks like zeros/padding
        if ekey[:2] == b"\x00\x00":
            pos += 1
            continue

        size = struct.unpack(">I", index_data[pos + 16:pos + 20])[0]

        # Validate: reasonable size and key has variety (is a hash)
        if 100 < size < 500_000_000:
            unique_bytes = len(set(ekey))
            if unique_bytes >= 8:  # Real hashes have variety
                prefix = ekey[:9]
                if prefix not in entries:  # Keep first occurrence
                    entries[prefix] = (ekey, size)
                # After finding an entry, skip past it
                pos += 20
                continue

        pos += 1

    return FileIndex(entries=entries)


def fetch_by_ekey(ekey: bytes) -> Optional[bytes]:
    """
    Fetch file data directly from CDN using full 16-byte EKey.

    Returns raw data (may be BLTE encoded), or None if not found.
    """
    ekey_hex = ekey.hex()
    url = f"{CDN_HOST}/{CDN_PATH}/data/{ekey_hex[0:2]}/{ekey_hex[2:4]}/{ekey_hex}"

    try:
        with urlopen(url, timeout=60) as resp:
            return resp.read()
    except HTTPError:
        return None


def parse_archive_index(index_data: bytes, archives: list[str]) -> ArchiveIndex:
    """
    Parse file index to map EKey prefixes to archive locations.

    Note: For D4, files can often be fetched directly by EKey, making
    archive lookups unnecessary. Use FileIndex and fetch_by_ekey instead.
    """
    entries = {}

    # Index format: blocks of 4096 bytes, each block has entries
    # Entry: 16 bytes key + 4 bytes size (BE) + 4 bytes offset (BE) = 24 bytes
    # Each block ends with padding and a footer

    pos = 0
    block_size = 4096
    entry_size = 24

    while pos + block_size <= len(index_data):
        block = index_data[pos:pos + block_size]

        # Parse entries in this block
        entry_pos = 0
        while entry_pos + entry_size <= block_size - 16:  # Leave room for footer
            ekey = block[entry_pos:entry_pos + 16]

            # Check for end of entries (all zeros or padding)
            if ekey == b"\x00" * 16:
                break

            size = struct.unpack(">I", block[entry_pos + 16:entry_pos + 20])[0]
            offset = struct.unpack(">I", block[entry_pos + 20:entry_pos + 24])[0]

            if size > 0 and size < 0x7FFFFFFF:
                # Use 9-byte prefix for lookup (matches VFS entries)
                prefix = ekey[:9]
                # Archive index is encoded in high bits of offset
                archive_idx = (offset >> 30) & 0x3F
                actual_offset = offset & 0x3FFFFFFF

                entries[prefix] = (archive_idx, actual_offset, size)

            entry_pos += entry_size

        pos += block_size

    return ArchiveIndex(entries=entries, archives=archives)


@dataclass
class FullArchiveIndex:
    """
    Complete archive index covering all files.

    Maps 9-byte EKey prefixes to (archive_hash, offset, size).
    """
    entries: dict[bytes, tuple[str, int, int]]


def build_full_archive_index(archives: list[str], cache_dir: Path) -> FullArchiveIndex:
    """
    Build a comprehensive index by parsing all individual archive indices.

    This is slow on first run but results are cached.
    """
    cache_path = cache_dir / "full_archive_index.bin"

    # Entry format: 9 prefix + 32 archive_hash + 4 offset + 4 size = 49 bytes
    entry_size = 49

    if cache_path.exists():
        # Load cached index
        entries = {}
        data = cache_path.read_bytes()
        pos = 0
        while pos + entry_size <= len(data):
            prefix = data[pos:pos + 9]
            archive_hash = data[pos + 9:pos + 41].decode("ascii")
            offset = struct.unpack(">I", data[pos + 41:pos + 45])[0]
            size = struct.unpack(">I", data[pos + 45:pos + 49])[0]
            entries[prefix] = (archive_hash, offset, size)
            pos += entry_size
        return FullArchiveIndex(entries=entries)

    # Build index from scratch
    print(f"Building full archive index from {len(archives)} archives...")
    entries = {}

    for i, archive_hash in enumerate(archives):
        if (i + 1) % 50 == 0:
            print(f"  Processing archive {i + 1}/{len(archives)}...")

        url = f"{CDN_HOST}/{CDN_PATH}/data/{archive_hash[0:2]}/{archive_hash[2:4]}/{archive_hash}.index"
        try:
            with urlopen(url, timeout=10) as resp:
                index_data = resp.read()

            # Individual archive indices use 24-byte entries: 16-byte key + 4-byte size + 4-byte offset
            # But they may not be aligned to 24-byte boundaries
            # Scan for valid entries
            pos = 0
            while pos + 24 <= len(index_data):
                ekey = index_data[pos:pos + 16]

                # Skip zero padding
                if ekey[:4] == b"\x00\x00\x00\x00":
                    pos += 1
                    continue

                size = struct.unpack(">I", index_data[pos + 16:pos + 20])[0]
                offset = struct.unpack(">I", index_data[pos + 20:pos + 24])[0]

                # Validate entry
                if 0 < size < 500_000_000 and offset < 0x80000000:
                    unique_bytes = len(set(ekey))
                    if unique_bytes >= 6:  # Hash should have variety
                        prefix = ekey[:9]
                        if prefix not in entries:
                            entries[prefix] = (archive_hash, offset, size)
                        # Skip to next entry
                        pos += 24
                        continue

                pos += 1

        except Exception:
            continue

    print(f"  Built index with {len(entries)} entries")

    # Cache the index
    cache_data = bytearray()
    for prefix, (archive_hash, offset, size) in entries.items():
        cache_data.extend(prefix)
        cache_data.extend(archive_hash.encode("ascii"))
        cache_data.extend(struct.pack(">I", offset))
        cache_data.extend(struct.pack(">I", size))

    cache_path.write_bytes(cache_data)

    return FullArchiveIndex(entries=entries)


def fetch_from_full_index(
    index: FullArchiveIndex,
    ekey_prefix: bytes,
) -> Optional[bytes]:
    """
    Fetch file data using the full archive index.

    Args:
        index: Full archive index
        ekey_prefix: 9-byte EKey prefix from VFS

    Returns:
        Raw file data (may be BLTE encoded), or None if not found
    """
    location = index.entries.get(ekey_prefix)
    if not location:
        return None

    archive_hash, offset, size = location
    url = f"{CDN_HOST}/{CDN_PATH}/data/{archive_hash[0:2]}/{archive_hash[2:4]}/{archive_hash}"

    req = Request(url)
    req.add_header("Range", f"bytes={offset}-{offset + size - 1}")

    try:
        with urlopen(req, timeout=60) as resp:
            return resp.read()
    except HTTPError as e:
        if e.code == 416:
            return None
        raise


def fetch_from_archive(
    archive_index: ArchiveIndex,
    ekey_prefix: bytes,
) -> Optional[bytes]:
    """
    Fetch file data from an archive using a partial EKey.

    Args:
        archive_index: Parsed archive index
        ekey_prefix: 9-byte EKey prefix from VFS

    Returns:
        Raw file data (may be BLTE encoded), or None if not found
    """
    location = archive_index.entries.get(ekey_prefix)
    if not location:
        return None

    archive_idx, offset, size = location

    if archive_idx >= len(archive_index.archives):
        return None

    archive_hash = archive_index.archives[archive_idx]
    url = f"{CDN_HOST}/{CDN_PATH}/data/{archive_hash[0:2]}/{archive_hash[2:4]}/{archive_hash}"

    # Use Range request to fetch just the file we need
    req = Request(url)
    req.add_header("Range", f"bytes={offset}-{offset + size - 1}")

    try:
        with urlopen(req, timeout=60) as resp:
            return resp.read()
    except HTTPError as e:
        if e.code == 416:  # Range not satisfiable
            # Try fetching without range
            return None
        raise


@dataclass
class BuildInfo:
    """D4 build information from CDN."""
    region: str
    build_config: str
    cdn_config: str
    build_id: int
    version: str


def get_versions() -> list[BuildInfo]:
    """Fetch available D4 versions from patch server."""
    url = f"{PATCH_SERVER}/{PRODUCT}/versions"

    with urlopen(url, timeout=30) as resp:
        content = resp.read().decode("utf-8")

    builds = []
    for line in content.strip().split("\n"):
        if line.startswith("#") or line.startswith("Region"):
            continue

        parts = line.split("|")
        if len(parts) >= 5:
            builds.append(BuildInfo(
                region=parts[0],
                build_config=parts[1],
                cdn_config=parts[2],
                build_id=int(parts[4]) if parts[4] else 0,
                version=parts[5] if len(parts) > 5 else "",
            ))

    return builds


def fetch_config(hash_key: str) -> dict:
    """Fetch a config file from CDN."""
    # Config path: {cdn}/{path}/config/{hash[0:2]}/{hash[2:4]}/{hash}
    url = f"{CDN_HOST}/{CDN_PATH}/config/{hash_key[0:2]}/{hash_key[2:4]}/{hash_key}"

    with urlopen(url, timeout=30) as resp:
        content = resp.read().decode("utf-8")

    config = {}
    for line in content.strip().split("\n"):
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip()

    return config


def fetch_data(hash_key: str) -> bytes:
    """Fetch a data file from CDN."""
    # Data path: {cdn}/{path}/data/{hash[0:2]}/{hash[2:4]}/{hash}
    url = f"{CDN_HOST}/{CDN_PATH}/data/{hash_key[0:2]}/{hash_key[2:4]}/{hash_key}"

    with urlopen(url, timeout=60) as resp:
        return resp.read()


def parse_encoding(data: bytes) -> dict[bytes, bytes]:
    """
    Parse encoding file to map CKeys to EKeys.

    The encoding file maps content hashes (CKey) to encoded hashes (EKey).
    Uses pattern matching to find the start of CEKey entries since the
    format has variable-length string blocks.

    Returns:
        Dict mapping CKey (16 bytes) to EKey (16 bytes)
    """
    if data[:2] != b"EN":
        raise ValueError("Not a valid encoding file")

    ckey_size = data[3]  # Usually 16
    ekey_size = data[4]  # Usually 16

    # Find CEKey entries by pattern matching
    # Entry format: 1 byte count (1-5), 5 bytes size, 16 bytes ckey, 16*count bytes ekeys
    # Look for consecutive valid entries

    def is_valid_entry_start(offset: int) -> bool:
        if offset + 38 >= len(data):
            return False
        key_count = data[offset]
        if key_count < 1 or key_count > 5:
            return False
        # Check no long runs of zeros in hashes
        ckey = data[offset + 6:offset + 22]
        if b"\x00" * 6 in ckey:
            return False
        return True

    # Search for the start of CEKey data
    cekey_start = None
    for offset in range(0, min(2000000, len(data) - 100)):
        if is_valid_entry_start(offset):
            # Verify next few entries are also valid
            valid_count = 0
            check_offset = offset
            for _ in range(5):
                if not is_valid_entry_start(check_offset):
                    break
                key_count = data[check_offset]
                check_offset += 6 + ckey_size + (ekey_size * key_count)
                valid_count += 1

            if valid_count >= 4:
                cekey_start = offset
                break

    if cekey_start is None:
        return {}

    # Parse all entries from this point
    mappings = {}
    offset = cekey_start

    while offset + 38 < len(data):
        key_count = data[offset]
        if key_count == 0 or key_count > 10:
            offset += 1
            continue

        file_size = int.from_bytes(data[offset + 1:offset + 6], "big")
        if file_size > 1000000000:  # 1GB sanity check
            offset += 1
            continue

        ckey = data[offset + 6:offset + 6 + ckey_size]
        ekey = data[offset + 6 + ckey_size:offset + 6 + ckey_size + ekey_size]

        if len(ckey) == ckey_size and len(ekey) == ekey_size:
            mappings[ckey] = ekey

        offset += 6 + ckey_size + (ekey_size * key_count)

    return mappings


def download_texture(content_key: str, output_path: Path) -> bool:
    """
    Download a specific texture by its content key.

    Note: This requires knowing the CKey->EKey mapping from the encoding file.
    """
    try:
        data = fetch_data(content_key)

        # BLTE encoded data starts with "BLTE"
        if data[:4] == b"BLTE":
            data = decode_blte(data)

        output_path.write_bytes(data)
        return True
    except HTTPError:
        return False


def decode_blte(data: bytes) -> bytes:
    """Decode BLTE (Blizzard Transfer Encoding) data."""
    if data[:4] != b"BLTE":
        return data

    # Read header
    header_size = struct.unpack(">I", data[4:8])[0]

    if header_size == 0:
        # Single chunk, raw data after 8-byte header
        chunk_data = data[8:]
        return decompress_chunk(chunk_data)

    # Multiple chunks
    # Skip to chunk info table
    offset = 8
    flags = data[offset]
    chunk_count = struct.unpack(">I", b"\x00" + data[offset+1:offset+4])[0]
    offset += 4

    # Read chunk entries
    chunks = []
    for _ in range(chunk_count):
        comp_size = struct.unpack(">I", data[offset:offset+4])[0]
        decomp_size = struct.unpack(">I", data[offset+4:offset+8])[0]
        checksum = data[offset+8:offset+24]
        offset += 24
        chunks.append((comp_size, decomp_size))

    # Read and decompress chunks
    result = io.BytesIO()
    for comp_size, decomp_size in chunks:
        chunk_data = data[offset:offset+comp_size]
        offset += comp_size
        result.write(decompress_chunk(chunk_data))

    return result.getvalue()


def decompress_chunk(data: bytes) -> bytes:
    """Decompress a single BLTE chunk."""
    if not data:
        return b""

    mode = data[0:1]
    payload = data[1:]

    if mode == b"N":
        # Not compressed
        return payload
    elif mode == b"Z":
        # Zlib compressed
        return zlib.decompress(payload)
    elif mode == b"E":
        # Encrypted - would need key
        raise ValueError("Encrypted chunk - key required")
    else:
        # Unknown, return as-is
        return data


def list_available_files(build_config: dict) -> list[str]:
    """
    List files available in a build.

    This requires parsing the VFS (Virtual File System) tables.
    """
    # Would need to parse vfs-root and walk the file tree
    return []


def main():
    """Test CDN access."""
    print("Fetching D4 version info...")
    versions = get_versions()

    us_build = next((v for v in versions if v.region == "us"), None)
    if not us_build:
        print("No US build found")
        return

    print(f"D4 Version: {us_build.version}")
    print(f"Build ID: {us_build.build_id}")
    print(f"Build Config: {us_build.build_config}")

    print("\nFetching build config...")
    config = fetch_config(us_build.build_config)

    print(f"Build Name: {config.get('build-name', 'Unknown')}")
    print(f"Encoding: {config.get('encoding', 'Unknown')}")
    print(f"VFS Root: {config.get('vfs-root', 'Unknown')}")


if __name__ == "__main__":
    main()
