"""
Diablo IV texture (.tex) file conversion utilities.

D4 textures are stored in a proprietary .tex format that needs to be
converted to DDS first, then to standard image formats (PNG, JPG, WebP).

This module handles the conversion pipeline and optional post-processing
like cropping transparent borders and slicing texture atlases.

References:
    - d4-texture-extractor: https://github.com/adainrivers/d4-texture-extractor
    - texconv (DirectX): https://github.com/microsoft/DirectXTex
"""

import subprocess
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image


@dataclass
class TextureInfo:
    """Metadata about a D4 texture file."""
    width: int
    height: int
    format: str
    mipmaps: int
    is_atlas: bool = False
    slice_count: int = 1


class TextureConverter:
    """
    Convert Diablo IV .tex files to standard image formats.

    The conversion pipeline is:
    1. .tex → .dds (via internal conversion or texconv)
    2. .dds → target format (via Pillow or texconv)
    3. Optional cropping/slicing

    Attributes:
        output_format: Target format (png, jpg, webp)
        crop: Whether to crop transparent borders
        slice_atlases: Whether to slice texture atlases into individual images
        texconv_path: Path to texconv.exe for DDS conversion

    Example:
        >>> converter = TextureConverter(output_format="png", crop=True)
        >>> converter.convert(Path("icon.tex"), Path("./output"))
    """

    SUPPORTED_FORMATS = {"png", "jpg", "jpeg", "webp"}

    def __init__(
        self,
        output_format: str = "png",
        crop: bool = True,
        slice_atlases: bool = True,
        texconv_path: Optional[Path] = None,
    ) -> None:
        if output_format.lower() not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format: {output_format}. "
                f"Supported: {', '.join(self.SUPPORTED_FORMATS)}"
            )

        self.output_format = output_format.lower()
        if self.output_format == "jpeg":
            self.output_format = "jpg"

        self.crop = crop
        self.slice_atlases = slice_atlases
        self.texconv_path = texconv_path or Path("tools/texconv.exe")

    def convert(self, tex_file: Path, output_dir: Path) -> list[Path]:
        """
        Convert a .tex file to the target image format.

        Args:
            tex_file: Path to the .tex file
            output_dir: Directory to save converted images

        Returns:
            List of paths to converted images (may be multiple if sliced)

        Raises:
            ValueError: If the file is not a valid .tex file
            RuntimeError: If conversion fails
        """
        if not tex_file.exists():
            raise FileNotFoundError(f"Texture file not found: {tex_file}")

        if tex_file.suffix.lower() != ".tex":
            raise ValueError(f"Not a .tex file: {tex_file}")

        output_dir.mkdir(parents=True, exist_ok=True)

        # Read texture info
        info = self._read_texture_info(tex_file)

        # Convert to intermediate format (DDS or direct)
        dds_file = self._tex_to_dds(tex_file)

        try:
            # Convert DDS to image
            image = self._dds_to_image(dds_file)

            if image is None:
                raise RuntimeError(f"Failed to decode texture: {tex_file}")

            # Post-processing
            if self.crop:
                image = self._crop_transparent(image)

            # Save output
            output_files = []

            if self.slice_atlases and info.is_atlas and info.slice_count > 1:
                # Slice into individual images
                slices = self._slice_atlas(image, info)
                for i, slice_img in enumerate(slices):
                    output_path = output_dir / f"{tex_file.stem}_{i:03d}.{self.output_format}"
                    self._save_image(slice_img, output_path)
                    output_files.append(output_path)
            else:
                # Save single image
                output_path = output_dir / f"{tex_file.stem}.{self.output_format}"
                self._save_image(image, output_path)
                output_files.append(output_path)

            return output_files

        finally:
            # Clean up intermediate DDS file
            if dds_file != tex_file and dds_file.exists():
                dds_file.unlink()

    def _read_texture_info(self, tex_file: Path) -> TextureInfo:
        """
        Read metadata from a .tex file header.

        D4 .tex files have a proprietary header format.
        """
        with open(tex_file, "rb") as f:
            # Read header - format may vary
            header = f.read(64)

            # Basic parsing - actual format TBD based on reverse engineering
            # This is a placeholder that should be updated with actual format
            try:
                # Attempt to read dimensions from common header locations
                width = struct.unpack("<H", header[12:14])[0]
                height = struct.unpack("<H", header[14:16])[0]

                # Validate dimensions
                if width == 0 or height == 0 or width > 8192 or height > 8192:
                    width = 256
                    height = 256

                return TextureInfo(
                    width=width,
                    height=height,
                    format="unknown",
                    mipmaps=1,
                    is_atlas=width > 512 or height > 512,
                    slice_count=1,
                )
            except Exception:
                # Default fallback
                return TextureInfo(
                    width=256,
                    height=256,
                    format="unknown",
                    mipmaps=1,
                )

    def _tex_to_dds(self, tex_file: Path) -> Path:
        """
        Convert .tex to .dds format.

        Uses texconv.exe if available, otherwise attempts direct conversion.
        """
        dds_file = tex_file.with_suffix(".dds")

        # If texconv is available, use it
        if self.texconv_path.exists():
            try:
                cmd = [
                    str(self.texconv_path),
                    "-ft", "dds",
                    "-o", str(tex_file.parent),
                    str(tex_file),
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                if dds_file.exists():
                    return dds_file
            except subprocess.CalledProcessError:
                pass

        # Fallback: try to treat .tex as raw DDS data
        # Some .tex files are just DDS with different extension
        with open(tex_file, "rb") as f:
            magic = f.read(4)
            if magic == b"DDS ":
                # Already DDS format, just copy/rename
                import shutil
                shutil.copy(tex_file, dds_file)
                return dds_file

        # Return original file and let _dds_to_image handle it
        return tex_file

    def _dds_to_image(self, dds_file: Path) -> Optional[Image.Image]:
        """
        Convert DDS file to PIL Image.

        Attempts multiple methods:
        1. Direct PIL load (works for some DDS formats)
        2. texconv conversion to PNG then load
        3. Manual DDS parsing (limited format support)
        """
        # Try direct PIL load
        try:
            return Image.open(dds_file).convert("RGBA")
        except Exception:
            pass

        # Try texconv if available
        if self.texconv_path.exists():
            try:
                temp_png = dds_file.with_suffix(".png")
                cmd = [
                    str(self.texconv_path),
                    "-ft", "png",
                    "-o", str(dds_file.parent),
                    str(dds_file),
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                if temp_png.exists():
                    img = Image.open(temp_png).convert("RGBA")
                    temp_png.unlink()
                    return img
            except Exception:
                pass

        # Fallback: attempt raw read
        try:
            with open(dds_file, "rb") as f:
                data = f.read()

            # Try to create image from raw data
            # This is very format-dependent
            return None
        except Exception:
            return None

    def _crop_transparent(self, image: Image.Image) -> Image.Image:
        """Crop transparent borders from an image."""
        if image.mode != "RGBA":
            return image

        # Get bounding box of non-transparent pixels
        bbox = image.getbbox()
        if bbox:
            return image.crop(bbox)
        return image

    def _slice_atlas(
        self,
        image: Image.Image,
        info: TextureInfo,
    ) -> list[Image.Image]:
        """
        Slice a texture atlas into individual images.

        Attempts to detect grid layout and slice accordingly.
        """
        slices = []

        # Try to detect common icon sizes
        common_sizes = [64, 128, 256, 32, 48, 96]

        width, height = image.size

        for size in common_sizes:
            cols = width // size
            rows = height // size

            if cols > 0 and rows > 0 and (cols * size == width or rows * size == height):
                # Found a matching grid
                for row in range(rows):
                    for col in range(cols):
                        box = (
                            col * size,
                            row * size,
                            (col + 1) * size,
                            (row + 1) * size,
                        )
                        slice_img = image.crop(box)

                        # Skip fully transparent slices
                        if slice_img.mode == "RGBA":
                            extrema = slice_img.getextrema()
                            if extrema[3][1] > 0:  # Has some non-transparent pixels
                                slices.append(slice_img)
                        else:
                            slices.append(slice_img)

                if slices:
                    return slices

        # No grid detected, return original
        return [image]

    def _save_image(self, image: Image.Image, path: Path) -> None:
        """Save image in the target format."""
        if self.output_format == "jpg":
            # JPEG doesn't support transparency
            if image.mode == "RGBA":
                # Create white background
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[3])
                image = background
            image.save(path, "JPEG", quality=95)
        elif self.output_format == "webp":
            image.save(path, "WEBP", quality=95, lossless=True)
        else:  # PNG
            image.save(path, "PNG", optimize=True)
