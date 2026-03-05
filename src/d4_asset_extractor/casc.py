"""
CASC (Content Addressable Storage Container) extraction utilities.

Diablo IV uses Blizzard's CASC storage system for game files.
This module wraps CASCConsole.exe for extraction operations.

References:
    - CASC Format: https://wowdev.wiki/CASC
    - CASCExplorer: https://github.com/WoW-Tools/CASCExplorer
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Common Diablo IV installation paths
COMMON_INSTALL_PATHS = [
    # Windows (x86 is typical Battle.net default)
    Path("C:/Program Files (x86)/Diablo IV"),
    Path("C:/Program Files/Diablo IV"),
    Path("C:/Program Files (x86)/Battle.net/Games/Diablo IV"),
    Path("D:/Games/Diablo IV"),
    Path("D:/Diablo IV"),
    # macOS (if applicable)
    Path("/Applications/Diablo IV"),
    Path.home() / "Applications/Diablo IV",
]


@dataclass
class CASCInfo:
    """Information about a CASC storage."""
    build: str
    data_files: int
    total_size_bytes: int

    @property
    def total_size_gb(self) -> float:
        return self.total_size_bytes / (1024 ** 3)


def find_game_directory() -> Optional[Path]:
    """
    Attempt to auto-detect Diablo IV installation directory.

    Checks common installation paths and returns the first valid one found.

    Returns:
        Path to game directory if found, None otherwise.
    """
    for path in COMMON_INSTALL_PATHS:
        if path.exists() and (path / "Data").exists():
            return path

    # Try to find via environment variable
    if "DIABLO4_PATH" in os.environ:
        env_path = Path(os.environ["DIABLO4_PATH"])
        if env_path.exists():
            return env_path

    return None


class CASCExtractor:
    """
    Wrapper for CASC file extraction.

    Uses CASCConsole.exe (from WoW-Tools/CASCExplorer) for extraction.
    Can also work with pre-extracted CASC files.

    Attributes:
        game_dir: Path to Diablo IV installation
        casc_console_path: Path to CASCConsole.exe (optional)

    Example:
        >>> extractor = CASCExtractor(Path("C:/Program Files/Diablo IV"))
        >>> if extractor.is_valid():
        ...     textures = extractor.extract_textures(filter_pattern="2DUI*")
    """

    def __init__(
        self,
        game_dir: Path,
        casc_console_path: Optional[Path] = None,
    ) -> None:
        self.game_dir = Path(game_dir)
        self.casc_console_path = casc_console_path or _find_tool("CASCConsole.exe")
        self._data_dir = self.game_dir / "Data"


def _find_tool(name: str) -> Path:
    """Find a tool in standard locations."""
    # Check local tools/ directory first
    local = Path("tools") / name
    if local.exists():
        return local

    # Check user's .d4-tools directory
    user_tools = Path.home() / ".d4-tools" / name
    if user_tools.exists():
        return user_tools

    # Return local path as default (will error later if not found)
    return local

    def is_valid(self) -> bool:
        """Check if this appears to be a valid Diablo IV CASC installation."""
        if not self._data_dir.exists():
            return False

        # Check for CASC data files (data.000, data.001, etc.)
        data_files = list(self._data_dir.glob("data.*"))
        if not data_files:
            return False

        # Check for .idx index files
        idx_files = list(self._data_dir.glob("*.idx"))
        if not idx_files:
            return False

        return True

    def get_info(self) -> dict:
        """
        Get information about the CASC storage.

        Returns:
            Dictionary with build, data_files count, and total_size_gb.
        """
        if not self.is_valid():
            return {"build": "Unknown", "data_files": 0, "total_size_gb": 0.0}

        data_files = list(self._data_dir.glob("data.*"))
        total_size = sum(f.stat().st_size for f in data_files if f.is_file())

        # Try to read build info from .build.info if it exists
        build_info_path = self.game_dir / ".build.info"
        build = "Unknown"
        if build_info_path.exists():
            try:
                content = build_info_path.read_text()
                # Parse build info format
                lines = content.strip().split("\n")
                if len(lines) >= 2:
                    headers = lines[0].split("|")
                    values = lines[1].split("|")
                    for i, header in enumerate(headers):
                        if "Version" in header and i < len(values):
                            build = values[i]
                            break
            except Exception:
                pass

        return {
            "build": build,
            "data_files": len(data_files),
            "total_size_gb": total_size / (1024 ** 3),
        }

    def extract_textures(
        self,
        output_dir: Optional[Path] = None,
        filter_pattern: str = "*",
    ) -> list[Path]:
        """
        Extract .tex texture files from CASC storage.

        Args:
            output_dir: Directory to extract files to. Uses temp dir if not specified.
            filter_pattern: Glob pattern to filter texture names (e.g., "2DUI*").

        Returns:
            List of paths to extracted .tex files.
        """
        if output_dir is None:
            output_dir = Path("./extracted/textures")
        output_dir.mkdir(parents=True, exist_ok=True)

        # If we have CASCConsole, use it for extraction
        if self.casc_console_path.exists():
            return self._extract_with_casc_console(output_dir, "*.tex", filter_pattern)

        # Otherwise, look for pre-extracted files
        return self._find_extracted_files(output_dir, "*.tex", filter_pattern)

    def extract_strings(
        self,
        output_dir: Optional[Path] = None,
        language: str = "enUS",
    ) -> list[Path]:
        """
        Extract .stl (StringList) files from CASC storage.

        Args:
            output_dir: Directory to extract files to.
            language: Language code to extract.

        Returns:
            List of paths to extracted .stl files.
        """
        if output_dir is None:
            output_dir = Path("./extracted/strings")
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.casc_console_path.exists():
            return self._extract_with_casc_console(output_dir, "*.stl", f"*{language}*")

        return self._find_extracted_files(output_dir, "*.stl", f"*{language}*")

    def extract_all(
        self,
        output_dir: Path,
        filter_pattern: str = "*",
    ) -> int:
        """
        Extract all files matching pattern from CASC storage.

        Args:
            output_dir: Directory to extract files to.
            filter_pattern: Glob pattern to filter files.

        Returns:
            Number of files extracted.
        """
        if not self.casc_console_path.exists():
            raise FileNotFoundError(
                f"CASCConsole.exe not found at {self.casc_console_path}. "
                "Download from https://github.com/WoW-Tools/CASCExplorer/releases"
            )

        output_dir.mkdir(parents=True, exist_ok=True)

        # Build CASCConsole command
        cmd = [
            str(self.casc_console_path),
            str(self.game_dir),
            "-o", str(output_dir),
            "-f", filter_pattern,
            "-e",  # Extract mode
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            # Parse output to count extracted files
            # CASCConsole typically outputs "Extracted X files"
            extracted = 0
            for line in result.stdout.split("\n"):
                if "extracted" in line.lower():
                    try:
                        extracted = int("".join(filter(str.isdigit, line)))
                    except ValueError:
                        pass
            return extracted
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"CASCConsole extraction failed: {e.stderr}")
        except FileNotFoundError:
            raise FileNotFoundError(
                "CASCConsole.exe not found. Please download from "
                "https://github.com/WoW-Tools/CASCExplorer/releases"
            )

    def _extract_with_casc_console(
        self,
        output_dir: Path,
        extension: str,
        name_filter: str,
    ) -> list[Path]:
        """Extract files using CASCConsole.exe."""
        # Combine extension and name filter
        full_filter = name_filter.replace("*", "") + extension if name_filter != "*" else extension

        cmd = [
            str(self.casc_console_path),
            str(self.game_dir),
            "-o", str(output_dir),
            "-f", full_filter,
            "-e",
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"CASCConsole extraction failed: {e}")

        # Return list of extracted files
        return list(output_dir.rglob(extension))

    def _find_extracted_files(
        self,
        directory: Path,
        extension: str,
        name_filter: str,
    ) -> list[Path]:
        """Find already-extracted files matching pattern."""
        if name_filter == "*":
            return list(directory.rglob(extension))

        # Apply name filter
        all_files = list(directory.rglob(extension))
        import fnmatch
        return [f for f in all_files if fnmatch.fnmatch(f.stem, name_filter)]
