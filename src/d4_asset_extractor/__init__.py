"""
Diablo IV Asset Extractor

Extract textures from Diablo IV CASC storage. Pure Python, no external tools.
"""

__version__ = "0.1.0"

from .casc_reader import D4CASCReader
from .texture_extractor import (
    TextureExtractor,
    TextureFrame,
    TextureInfo,
    TextureExtractionError,
    InterleavedBC1Error,
)

__all__ = [
    "D4CASCReader",
    "TextureExtractor",
    "TextureFrame",
    "TextureInfo",
    "TextureExtractionError",
    "InterleavedBC1Error",
]
