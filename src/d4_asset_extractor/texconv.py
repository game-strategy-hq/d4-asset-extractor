"""
Texconv wrapper for DDS texture conversion.

Provides cross-platform support for Microsoft's texconv.exe tool,
which handles all D4 texture formats including GPU-tiled uncompressed textures.

Platform support:
    - Windows: Direct execution of texconv.exe
    - macOS: Execution via Whisky (Apple's Game Porting Toolkit)

References:
    - https://github.com/Microsoft/DirectXTex/releases
    - https://docs.getwhisky.app/
"""

import os
import platform
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image


class TexconvError(Exception):
    """Base exception for texconv-related errors."""

    pass


class TexconvNotFoundError(TexconvError):
    """texconv.exe not found in any search location."""

    pass


class WhiskyNotFoundError(TexconvError):
    """Whisky is required but not found (macOS)."""

    pass


class ConversionError(TexconvError):
    """texconv conversion failed."""

    pass


# Whisky paths
WHISKY_CMD = Path("/Applications/Whisky.app/Contents/Resources/WhiskyCmd")
WHISKY_BOTTLE_NAME = "d4-tools"


@dataclass
class TexconvConfig:
    """Configuration for texconv wrapper.

    Attributes:
        texconv_path: Explicit path to texconv.exe (overrides discovery)
        whisky_bottle: Whisky bottle name (macOS only)
        retry_count: Number of retries on transient failures
        retry_delay: Delay in seconds between retries
        timeout: Subprocess timeout in seconds
    """

    texconv_path: Optional[Path] = None
    whisky_bottle: str = WHISKY_BOTTLE_NAME
    retry_count: int = 1
    retry_delay: float = 0.1
    timeout: float = 30.0


# Module-level default wrapper instance
_default_wrapper: Optional["TexconvWrapper"] = None


def _find_texconv() -> Optional[Path]:
    """
    Find texconv.exe using discovery chain.

    Search order:
        1. D4_TEXCONV_PATH environment variable
        2. ./tools/texconv.exe (project-local)
        3. ~/.d4-tools/texconv.exe (user home)

    Returns:
        Path to texconv.exe if found, None otherwise
    """
    # Environment variable
    env_path = os.environ.get("D4_TEXCONV_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path

    # Project-local tools directory
    local = Path("tools") / "texconv.exe"
    if local.exists():
        return local

    # User home directory
    user_tools = Path.home() / ".d4-tools" / "texconv.exe"
    if user_tools.exists():
        return user_tools

    return None


def _is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system() == "Windows"


def _is_whisky_available() -> bool:
    """Check if Whisky is installed."""
    return WHISKY_CMD.exists()


def _get_whisky_env(bottle_name: str) -> dict[str, str]:
    """
    Get environment variables for a Whisky bottle.

    Args:
        bottle_name: Name of the Whisky bottle

    Returns:
        Environment dict with Wine paths configured
    """
    try:
        result = subprocess.run(
            [str(WHISKY_CMD), "shellenv", bottle_name],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if result.returncode != 0:
            return {}

        # Parse export statements
        env = os.environ.copy()
        for line in result.stdout.strip().split("\n"):
            if line.startswith("export "):
                # Parse: export VAR="value" or export VAR=value
                parts = line[7:].split("=", 1)
                if len(parts) == 2:
                    key = parts[0]
                    value = parts[1].strip('"').strip("'")
                    # Expand $PATH references
                    if "$PATH" in value:
                        value = value.replace("$PATH", env.get("PATH", ""))
                    env[key] = value
        return env
    except Exception:
        return {}


def _ensure_whisky_bottle(bottle_name: str) -> bool:
    """
    Ensure a Whisky bottle exists, creating if needed.

    Args:
        bottle_name: Name of the bottle to create

    Returns:
        True if bottle exists or was created, False on failure
    """
    if not _is_whisky_available():
        return False

    try:
        # Check if bottle exists
        result = subprocess.run(
            [str(WHISKY_CMD), "list"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if bottle_name in result.stdout:
            return True

        # Create bottle
        result = subprocess.run(
            [str(WHISKY_CMD), "create", bottle_name],
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        return result.returncode == 0
    except Exception:
        return False


class TexconvWrapper:
    """
    Cross-platform wrapper for texconv.exe.

    Handles:
        - Automatic tool discovery
        - Whisky integration for macOS
        - Temp file management
        - Retry logic for transient failures
    """

    def __init__(self, config: Optional[TexconvConfig] = None):
        """
        Initialize texconv wrapper.

        Args:
            config: Optional configuration. If None, uses defaults.
        """
        self.config = config or TexconvConfig()
        self._texconv_path: Optional[Path] = None
        self._is_windows = _is_windows()
        self._whisky_env: Optional[dict[str, str]] = None

        # Resolve paths
        self._resolve_paths()

    def _resolve_paths(self) -> None:
        """Resolve texconv path and Whisky environment."""
        # Texconv path
        if self.config.texconv_path:
            self._texconv_path = self.config.texconv_path
        else:
            self._texconv_path = _find_texconv()

        # Whisky environment (only needed on macOS)
        if not self._is_windows and _is_whisky_available():
            _ensure_whisky_bottle(self.config.whisky_bottle)
            self._whisky_env = _get_whisky_env(self.config.whisky_bottle)

    @property
    def texconv_path(self) -> Optional[Path]:
        """Get the resolved texconv.exe path."""
        return self._texconv_path

    def is_available(self) -> bool:
        """
        Check if texconv is available for use.

        Returns:
            True if texconv.exe is found and Whisky is available (if needed)
        """
        if not self._texconv_path or not self._texconv_path.exists():
            return False

        if not self._is_windows:
            if not _is_whisky_available():
                return False
            if not self._whisky_env:
                return False

        return True

    def _unix_to_wine_path(self, path: Path) -> str:
        """Convert Unix path to Wine Z: drive path."""
        return f"Z:{str(path.resolve())}"

    def _build_command(self, input_path: Path, output_dir: Path) -> list[str]:
        """
        Build the texconv command line.

        Args:
            input_path: Path to input DDS file
            output_dir: Directory for output

        Returns:
            Command line as list of strings
        """
        if not self._texconv_path:
            raise TexconvNotFoundError("texconv.exe path not set")

        # Convert paths for Wine on non-Windows (Z: drive maps to /)
        if self._is_windows:
            input_str = str(input_path)
            output_str = str(output_dir)
        else:
            input_str = self._unix_to_wine_path(input_path)
            output_str = self._unix_to_wine_path(output_dir)

        # Base texconv command
        texconv_args = [
            input_str,
            "-ft",
            "png",  # Output format
            "-f",
            "R8G8B8A8_UNORM",  # Force RGBA8
            "-y",  # Overwrite existing
            "-o",
            output_str,  # Output directory
        ]

        if self._is_windows:
            return [str(self._texconv_path)] + texconv_args
        else:
            # Use wine64 from Whisky environment
            wine_path = self._whisky_env.get("PATH", "").split(":")[0]
            wine64 = Path(wine_path) / "wine64" if wine_path else Path("wine64")
            return [str(wine64), str(self._texconv_path)] + texconv_args

    def convert_dds_to_image(self, dds_data: bytes) -> Image.Image:
        """
        Convert DDS data to a PIL Image using texconv.

        Args:
            dds_data: Raw DDS file bytes

        Returns:
            PIL Image in RGBA mode

        Raises:
            TexconvNotFoundError: texconv.exe not found
            WhiskyNotFoundError: Whisky required but not found
            ConversionError: Conversion failed
        """
        if not self.is_available():
            if not self._texconv_path or not self._texconv_path.exists():
                raise TexconvNotFoundError(
                    "texconv.exe not found. Download from "
                    "https://github.com/Microsoft/DirectXTex/releases "
                    "and place in ./tools/ or ~/.d4-tools/"
                )
            if not self._is_windows and not _is_whisky_available():
                raise WhiskyNotFoundError(
                    "Whisky is required on macOS. "
                    "Install via: brew install --cask whisky"
                )

        last_error: Optional[Exception] = None

        for attempt in range(self.config.retry_count + 1):
            try:
                return self._do_conversion(dds_data)
            except ConversionError as e:
                last_error = e
                if attempt < self.config.retry_count:
                    time.sleep(self.config.retry_delay)
                    continue
                raise

        # Should not reach here, but satisfy type checker
        raise last_error or ConversionError("Conversion failed")

    def _do_conversion(self, dds_data: bytes) -> Image.Image:
        """
        Perform the actual DDS to image conversion.

        Args:
            dds_data: Raw DDS file bytes

        Returns:
            PIL Image
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dds_file = temp_path / "texture.dds"
            dds_file.write_bytes(dds_data)

            cmd = self._build_command(dds_file, temp_path)

            # Use Whisky environment on macOS
            env = self._whisky_env if not self._is_windows else None

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.config.timeout,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                raise ConversionError(
                    f"texconv timed out after {self.config.timeout}s"
                )
            except FileNotFoundError as e:
                raise ConversionError(f"Failed to execute texconv: {e}")

            if result.returncode != 0:
                raise ConversionError(
                    f"texconv failed (exit {result.returncode}): {result.stderr}"
                )

            # texconv outputs filename.png
            png_file = temp_path / "texture.png"
            if not png_file.exists():
                raise ConversionError(
                    f"texconv did not produce output file. stdout: {result.stdout}"
                )

            # Load and copy image (copy so it persists after temp dir cleanup)
            img = Image.open(png_file)
            return img.copy()


def get_default_wrapper() -> TexconvWrapper:
    """Get or create the default texconv wrapper instance."""
    global _default_wrapper
    if _default_wrapper is None:
        _default_wrapper = TexconvWrapper()
    return _default_wrapper


def is_available(config: Optional[TexconvConfig] = None) -> bool:
    """
    Check if texconv is available.

    Args:
        config: Optional configuration. If None, uses default wrapper.

    Returns:
        True if texconv can be used for conversions
    """
    if config:
        return TexconvWrapper(config).is_available()
    return get_default_wrapper().is_available()


def convert_dds(
    dds_data: bytes, config: Optional[TexconvConfig] = None
) -> Image.Image:
    """
    Convert DDS data to PIL Image using texconv.

    Convenience function using module-level wrapper.

    Args:
        dds_data: Raw DDS file bytes
        config: Optional configuration. If None, uses default wrapper.

    Returns:
        PIL Image in RGBA mode

    Raises:
        TexconvError: If conversion fails
    """
    if config:
        wrapper = TexconvWrapper(config)
    else:
        wrapper = get_default_wrapper()

    return wrapper.convert_dds_to_image(dds_data)
