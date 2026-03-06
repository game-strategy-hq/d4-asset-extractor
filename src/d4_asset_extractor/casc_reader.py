"""
Pure Python CASC reader for Diablo IV.

Reads game files directly from the CASC storage without requiring external tools.
Based on PyCASC and CascLib implementations.

References:
    - https://wowdev.wiki/CASC
    - https://github.com/RaidAndFade/PyCASC
    - https://github.com/ladislav-zezula/CascLib
"""

import struct
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional


@dataclass
class FileInfo:
    """Information about a file in CASC storage."""
    ekey: int  # 9-byte encoded key (as int)
    data_file: int  # data.XXX file number
    offset: int  # offset within data file
    compressed_size: int
    ckey: Optional[int] = None  # content key (if known)


def parse_build_info(path: Path) -> dict[str, str]:
    """Parse .build.info file to extract build configuration keys."""
    content = path.read_text()
    lines = content.strip().split('\n')
    if len(lines) < 2:
        raise ValueError("Invalid .build.info format")

    headers = [h.split('!')[0] for h in lines[0].split('|')]
    values = lines[1].split('|')

    return {headers[i]: values[i] for i in range(min(len(headers), len(values)))}


def parse_build_config(content: str) -> dict[str, str]:
    """Parse a build configuration file."""
    config = {}
    for line in content.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            key, value = line.split('=', 1)
            config[key.strip()] = value.strip()
    return config


def prefix_hash(hash_hex: str) -> str:
    """Convert hash to config path format (xx/yy/hash)."""
    return f"{hash_hex[0:2]}/{hash_hex[2:4]}/{hash_hex}"


def var_int(f, num_bytes: int, little_endian: bool = True) -> int:
    """Read variable-length integer from file (matches PyCASC behavior)."""
    data = f.read(num_bytes)
    return int.from_bytes(data, byteorder='little' if little_endian else 'big', signed=False)


def read_idx_file(path: Path) -> list[FileInfo]:
    """Parse an .idx file to get file table entries."""
    entries = []
    with open(path, 'rb') as f:
        # Read header
        hl, hh, u_0, bi, u_1, ess, eos, eks, afhb, atsm, _, elen, eh = struct.unpack(
            "IIH6BQQII", f.read(0x28)
        )

        entry_size = ess + eos + eks

        # Read entries
        for x in range(0x28, 0x28 + elen, entry_size):
            ek = var_int(f, eks, False)
            eo = var_int(f, eos, False)
            es = var_int(f, ess, True)

            e = FileInfo(
                ekey=ek,
                data_file=eo >> 30,
                offset=eo & (2**30 - 1),
                compressed_size=es
            )
            entries.append(e)

    return entries


def read_casc_data_header(f: BytesIO) -> tuple:
    """Read CASC data file entry header."""
    blth, sz, f_0, f_1, chkA, chkB = struct.unpack("16sI2b4s4s", f.read(30))
    return blth, sz, f_0, f_1, chkA, chkB


def read_blte_header(f: BytesIO) -> tuple:
    """Read BLTE (Blizzard Transfer Encoding) header."""
    magic = f.read(4)
    if magic != b"BLTE":
        raise ValueError(f"Invalid BLTE magic: {magic}")

    sz = struct.unpack("I", f.read(4))[0]
    if sz == 0:
        # Single chunk, no header
        return 0, 0, 1, [(-1, -1, b'')]

    flg = f.read(1)[0]
    cc = int.from_bytes(f.read(3), 'big')

    chunks = []
    for _ in range(cc):
        comp_size, decomp_size = struct.unpack(">II", f.read(8))
        checksum = f.read(16)
        chunks.append((comp_size, decomp_size, checksum))

    return sz, flg, cc, chunks


class EncryptedChunkError(Exception):
    """Raised when encountering an encrypted BLTE chunk."""
    pass


class UnsupportedEncodingError(Exception):
    """Raised for unsupported BLTE encoding types."""
    pass


def read_blte_chunk(f: BytesIO, chunk_info: tuple) -> bytes:
    """
    Read and decompress a BLTE chunk.

    Supported encodings:
        N - Plain/uncompressed (7.5% of D4 files)
        Z - Zlib compressed (90.9% of D4 files)

    Unsupported encodings:
        E - Encrypted (0.8% of D4 files, only EncryptedNameDict-*.dat)
        F - Frame (not used in D4)
        S - ZSTD (not used in D4)

    Raises:
        EncryptedChunkError: For encrypted chunks (requires Blizzard's keys)
        UnsupportedEncodingError: For unknown encoding types
    """
    comp_size, decomp_size, _ = chunk_info

    etype = f.read(1)

    if etype == b"N":
        # Plain/uncompressed data
        return f.read(decomp_size if decomp_size > 0 else -1)
    elif etype == b"Z":
        # Zlib compressed
        compressed = f.read(comp_size - 1 if decomp_size > 0 else -1)
        return zlib.decompress(compressed)
    elif etype == b"E":
        # Encrypted - only affects EncryptedNameDict-*.dat files in D4
        # These are name obfuscation files, not actual game content
        raise EncryptedChunkError(
            "Encrypted BLTE chunk (requires Blizzard encryption keys)"
        )
    else:
        raise UnsupportedEncodingError(f"Unknown BLTE encoding type: {etype}")


def parse_blte(data: bytes, max_size: int = -1) -> Optional[bytes]:
    """
    Parse BLTE encoded data and return decompressed content.

    Args:
        data: Raw BLTE data including header
        max_size: Maximum bytes to decompress (-1 for unlimited)

    Returns:
        Decompressed data, or None if the data is encrypted/unsupported
    """
    f = BytesIO(data)
    header = read_blte_header(f)

    result = BytesIO()
    total_size = 0

    for chunk in header[3]:
        try:
            chunk_data = read_blte_chunk(f, chunk)
        except (EncryptedChunkError, UnsupportedEncodingError):
            # Return None for encrypted/unsupported content
            return None
        result.write(chunk_data)
        total_size += len(chunk_data)

        if max_size > 0 and total_size >= max_size:
            break

    return result.getvalue()


def read_cascfile(
    data_path: str, data_index: int, offset: int, max_size: int = -1
) -> Optional[bytes]:
    """
    Read a file from CASC data storage.

    Args:
        data_path: Path to the data directory
        data_index: Data file number (data.XXX)
        offset: Byte offset within the data file
        max_size: Maximum bytes to read (-1 for unlimited)

    Returns:
        Decompressed file data, or None if encrypted/unsupported
    """
    data_file = Path(data_path) / f"data.{data_index:03d}"

    with open(data_file, 'rb') as f:
        f.seek(offset)
        # Read data header
        read_casc_data_header(f)
        # Read BLTE data starting after header
        blte_start = f.tell()
        # Read enough data for BLTE parsing
        f.seek(blte_start)
        blte_data = f.read()  # Read rest of entry (will be bounded by BLTE structure)

    return parse_blte(blte_data, max_size)


def parse_encoding_file(data: bytes, whole_key: bool = False) -> dict[int, int]:
    """
    Parse encoding file to build ckey -> ekey mapping.

    Returns:
        Dict mapping content key (ckey) to encoded key (ekey)
    """
    f = BytesIO(data)

    magic = f.read(2)
    if magic != b"EN":
        raise ValueError(f"Invalid encoding file magic: {magic}")

    version, ckey_len, ekey_len = struct.unpack("3B", f.read(3))
    ckey_pagesize = int.from_bytes(f.read(2), 'big') * 1024
    ekey_pagesize = int.from_bytes(f.read(2), 'big') * 1024
    ckey_pagecount = int.from_bytes(f.read(4), 'big')
    ekey_pagecount = int.from_bytes(f.read(4), 'big')
    f.seek(1, 1)  # Skip unk_1
    espec_blocksize = int.from_bytes(f.read(4), 'big')

    # Skip espec data
    f.seek(espec_blocksize, 1)

    # Parse ckey pages
    ckey_map = {}
    header_start = f.tell()
    header_len = 0x20 * ckey_pagecount

    for i in range(ckey_pagecount):
        f.seek(header_start + header_len + i * ckey_pagesize)

        while True:
            ekcount = struct.unpack("H", f.read(2))[0]
            if ekcount == 0:
                break

            f.seek(4, 1)  # Skip cfsize
            ckey = int.from_bytes(f.read(ckey_len), 'big')

            if whole_key:
                ekey = int.from_bytes(f.read(ekey_len), 'big')
            else:
                ekey = int.from_bytes(f.read(ekey_len)[:9], 'big')

            ckey_map[ckey] = ekey

            # Skip additional ekeys if any
            f.seek(ekey_len * (ekcount - 1), 1)

    return ckey_map


class D4CASCReader:
    """
    Diablo IV CASC file reader.

    Provides access to game files stored in Blizzard's CASC format
    without requiring external tools like CASCConsole.

    Example:
        >>> reader = D4CASCReader(Path("/path/to/Diablo IV"))
        >>> vfs2_data = reader.read_by_ckey("f6f9dee685c42da934e272a19e475677")
    """

    def __init__(self, game_dir: Path):
        self.game_dir = Path(game_dir)
        self.data_path = self._find_data_path()
        self.config_path = self.game_dir / "Data" / "config"

        # Load build configuration
        self.build_info = self._load_build_info()
        self.build_config = self._load_build_config()

        # Build file table from .idx files
        self.file_table: dict[int, FileInfo] = {}
        self._build_file_table()

        # Parse encoding file for ckey -> ekey mapping
        self.ckey_map: dict[int, int] = {}
        self._load_encoding()

    def _find_data_path(self) -> Path:
        """Find the CASC data directory."""
        # D4 structure: game_dir/Data/data/
        nested = self.game_dir / "Data" / "data"
        if nested.exists() and list(nested.glob("data.*")):
            return nested

        # Standard structure: game_dir/Data/
        standard = self.game_dir / "Data"
        if standard.exists():
            return standard

        raise FileNotFoundError(f"Could not find CASC data directory in {self.game_dir}")

    def _load_build_info(self) -> dict[str, str]:
        """Load .build.info file."""
        build_info_path = self.game_dir / ".build.info"
        if not build_info_path.exists():
            raise FileNotFoundError(f".build.info not found at {build_info_path}")
        return parse_build_info(build_info_path)

    def _load_build_config(self) -> dict[str, str]:
        """Load build configuration file."""
        build_key = self.build_info.get("Build Key")
        if not build_key:
            raise ValueError("Build Key not found in .build.info")

        config_file = self.config_path / prefix_hash(build_key)
        if not config_file.exists():
            raise FileNotFoundError(f"Build config not found at {config_file}")

        return parse_build_config(config_file.read_text())

    def _build_file_table(self) -> None:
        """Build file table from .idx files."""
        for idx_file in self.data_path.glob("*.idx"):
            entries = read_idx_file(idx_file)
            for entry in entries:
                if entry.ekey not in self.file_table:
                    self.file_table[entry.ekey] = entry

    def _load_encoding(self) -> None:
        """Load and parse encoding file."""
        enc_ckey, enc_ekey = self.build_config["encoding"].split()
        # The file table uses 9-byte ekey (18 hex chars)
        enc_ekey_int = int(enc_ekey[:18], 16)

        if enc_ekey_int not in self.file_table:
            # Debug: print what we're looking for and what we have
            sample_keys = list(self.file_table.keys())[:5]
            raise FileNotFoundError(
                f"Encoding file not found. Looking for ekey {enc_ekey[:18]} ({enc_ekey_int}). "
                f"Sample keys: {[hex(k) for k in sample_keys]}"
            )

        enc_info = self.file_table[enc_ekey_int]
        enc_data = read_cascfile(
            str(self.data_path) + "/",
            enc_info.data_file,
            enc_info.offset
        )

        self.ckey_map = parse_encoding_file(enc_data)

    def read_by_ckey(self, ckey_hex: str, max_size: int = -1) -> Optional[bytes]:
        """
        Read a file by its content key (ckey).

        Args:
            ckey_hex: 32-character hex string content key
            max_size: Maximum bytes to read (-1 for unlimited)

        Returns:
            File data as bytes, or None if not found
        """
        ckey_int = int(ckey_hex, 16)

        if ckey_int not in self.ckey_map:
            return None

        ekey_int = self.ckey_map[ckey_int]

        if ekey_int not in self.file_table:
            return None

        info = self.file_table[ekey_int]
        return read_cascfile(
            str(self.data_path) + "/",
            info.data_file,
            info.offset,
            max_size
        )

    def read_by_ekey(self, ekey: bytes) -> Optional[bytes]:
        """
        Read a file by its encoded key (ekey).

        Args:
            ekey: 9-byte encoded key

        Returns:
            File data as bytes, or None if not found
        """
        ekey_int = int.from_bytes(ekey, 'big')

        if ekey_int not in self.file_table:
            return None

        info = self.file_table[ekey_int]
        return read_cascfile(
            str(self.data_path) + "/",
            info.data_file,
            info.offset
        )

    def get_vfs_ckey(self, vfs_name: str) -> Optional[str]:
        """Get the content key for a VFS manifest."""
        if vfs_name not in self.build_config:
            return None
        return self.build_config[vfs_name].split()[0]

    @property
    def version(self) -> str:
        """Get the game version string."""
        return self.build_info.get("Version", "Unknown")

    @property
    def build_uid(self) -> str:
        """Get the build UID (product code)."""
        return self.build_config.get("build-uid", "Unknown")
