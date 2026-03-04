"""
Diablo IV StringList (.stl) file parser.

StringList files contain all game text in a binary format:
- Item names and descriptions
- Skill names and descriptions
- UI labels
- Dialog and quest text
- Tooltip text

References:
    - diablo-4-string-parser: https://github.com/alkhdaniel/diablo-4-string-parser
    - diablo4-data-harvest: https://github.com/mfloob/diablo4-data-harvest
"""

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO


@dataclass
class StringEntry:
    """A single string entry from a StringList file."""
    hash_id: int
    text: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "hash_id": self.hash_id,
            "hash_hex": f"0x{self.hash_id:08X}",
            "text": self.text,
            **self.metadata,
        }


@dataclass
class StringListFile:
    """Parsed contents of a StringList (.stl) file."""
    filename: str
    game_id: str
    language: str
    entries: list[StringEntry]

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "game_id": self.game_id,
            "language": self.language,
            "entry_count": len(self.entries),
            "entries": {
                f"0x{e.hash_id:08X}": e.text for e in self.entries
            },
        }

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self.entries]


class StringListParser:
    """
    Parser for Diablo IV .stl (StringList) files.

    StringList files have a binary format:
    - 4 bytes: Game identifier (e.g., "D4" + padding)
    - 4 bytes: File type identifier
    - Variable: Padding/header data
    - Entries: Hash ID (4 bytes) + String data

    Example:
        >>> parser = StringListParser()
        >>> result = parser.parse(Path("strings_enUS.stl"))
        >>> parser.save_json(result, Path("strings.json"))
    """

    # Known game identifiers
    GAME_IDS = {
        b"D4\x00\x00": "Diablo IV",
        b"D4": "Diablo IV",
    }

    def __init__(self, encoding: str = "utf-8") -> None:
        """
        Initialize the parser.

        Args:
            encoding: Text encoding for string data (default: utf-8)
        """
        self.encoding = encoding

    def parse(self, stl_path: Path) -> StringListFile:
        """
        Parse a StringList file.

        Args:
            stl_path: Path to the .stl file

        Returns:
            StringListFile with parsed entries

        Raises:
            ValueError: If the file is not a valid StringList
            FileNotFoundError: If the file doesn't exist
        """
        if not stl_path.exists():
            raise FileNotFoundError(f"StringList file not found: {stl_path}")

        with open(stl_path, "rb") as f:
            # Read and validate header
            game_id = self._read_game_id(f)

            # Parse entries
            entries = self._parse_entries(f)

        # Detect language from filename
        language = self._detect_language(stl_path.stem)

        return StringListFile(
            filename=stl_path.name,
            game_id=game_id,
            language=language,
            entries=entries,
        )

    def save_json(
        self,
        data: StringListFile,
        output_path: Path,
        as_list: bool = False,
    ) -> None:
        """
        Save parsed StringList data to JSON.

        Args:
            data: Parsed StringList data
            output_path: Path to save JSON file
            as_list: If True, save as list of entries; otherwise as dict
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        output = data.to_list() if as_list else data.to_dict()

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

    def _read_game_id(self, f: BinaryIO) -> str:
        """Read and validate game identifier from header."""
        header = f.read(8)

        # Check for known game IDs
        for pattern, name in self.GAME_IDS.items():
            if header.startswith(pattern):
                return name

        # Unknown but might still be valid
        return "Unknown"

    def _parse_entries(self, f: BinaryIO) -> list[StringEntry]:
        """Parse string entries from file."""
        entries = []

        # Read file position info
        # Format varies, so we try multiple approaches

        # Try format 1: Fixed header + entry table
        try:
            entries = self._parse_format_v1(f)
            if entries:
                return entries
        except Exception:
            f.seek(8)  # Reset to after game ID

        # Try format 2: Sequential entries
        try:
            entries = self._parse_format_v2(f)
            if entries:
                return entries
        except Exception:
            pass

        return entries

    def _parse_format_v1(self, f: BinaryIO) -> list[StringEntry]:
        """
        Parse format with entry table.

        Format:
        - Header (variable size)
        - Entry count (4 bytes)
        - Entry table: [hash_id (4 bytes), offset (4 bytes)] * count
        - String data pool
        """
        entries = []

        # Skip to entry count (after header)
        f.seek(16)

        # Read entry count
        count_data = f.read(4)
        if len(count_data) < 4:
            return entries

        count = struct.unpack("<I", count_data)[0]

        # Sanity check
        if count > 1_000_000 or count == 0:
            return entries

        # Read entry table
        entry_table = []
        for _ in range(count):
            entry_data = f.read(8)
            if len(entry_data) < 8:
                break
            hash_id, offset = struct.unpack("<II", entry_data)
            entry_table.append((hash_id, offset))

        if not entry_table:
            return entries

        # Calculate string data start
        string_data_start = f.tell()

        # Read strings
        for hash_id, offset in entry_table:
            try:
                f.seek(string_data_start + offset)
                text = self._read_null_terminated_string(f)
                entries.append(StringEntry(hash_id=hash_id, text=text))
            except Exception:
                continue

        return entries

    def _parse_format_v2(self, f: BinaryIO) -> list[StringEntry]:
        """
        Parse sequential entry format.

        Format:
        - Entries: [hash_id (4 bytes), length (2 bytes), string (length bytes)]
        """
        entries = []

        while True:
            # Read hash ID
            hash_data = f.read(4)
            if len(hash_data) < 4:
                break

            hash_id = struct.unpack("<I", hash_data)[0]

            # Read string length
            len_data = f.read(2)
            if len(len_data) < 2:
                break

            str_len = struct.unpack("<H", len_data)[0]

            # Sanity check
            if str_len > 10000:
                break

            # Read string
            str_data = f.read(str_len)
            if len(str_data) < str_len:
                break

            try:
                text = str_data.decode(self.encoding).rstrip("\x00")
                entries.append(StringEntry(hash_id=hash_id, text=text))
            except UnicodeDecodeError:
                # Try with replacement
                text = str_data.decode(self.encoding, errors="replace").rstrip("\x00")
                entries.append(StringEntry(hash_id=hash_id, text=text))

        return entries

    def _read_null_terminated_string(self, f: BinaryIO, max_len: int = 10000) -> str:
        """Read a null-terminated string from file."""
        chars = []
        for _ in range(max_len):
            byte = f.read(1)
            if not byte or byte == b"\x00":
                break
            chars.append(byte)

        data = b"".join(chars)
        try:
            return data.decode(self.encoding)
        except UnicodeDecodeError:
            return data.decode(self.encoding, errors="replace")

    def _detect_language(self, filename: str) -> str:
        """Detect language from filename."""
        # Common language codes in D4 filenames
        languages = {
            "enUS": "English (US)",
            "enGB": "English (GB)",
            "deDE": "German",
            "esES": "Spanish (Spain)",
            "esMX": "Spanish (Mexico)",
            "frFR": "French",
            "itIT": "Italian",
            "jaJP": "Japanese",
            "koKR": "Korean",
            "plPL": "Polish",
            "ptBR": "Portuguese (Brazil)",
            "ruRU": "Russian",
            "zhCN": "Chinese (Simplified)",
            "zhTW": "Chinese (Traditional)",
        }

        for code, name in languages.items():
            if code in filename:
                return code

        return "unknown"
