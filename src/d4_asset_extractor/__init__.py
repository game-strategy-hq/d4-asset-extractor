"""
Diablo IV Asset Extractor

Extract textures from Diablo IV CASC storage.
Uses texconv as the primary decoder for BC-compressed textures when available.
"""

__version__ = "0.1.0"

from .casc_reader import D4CASCReader
from .texconv import (
    TexconvConfig,
    TexconvWrapper,
    TexconvError,
    TexconvNotFoundError,
    WhiskyNotFoundError,
    ConversionError,
)
from .texture_extractor import (
    TextureExtractor,
    TextureFrame,
    TextureInfo,
    TextureExtractionError,
    InterleavedBC1Error,
    EncryptedSNOError,
)
from .texture_definition import (
    TEX_DEF,
    Field,
    TextureDefinitionFields,
    TexFrame,
    TextureDefinition,
    read_texture_definition,
    resolve_vararray,
)

__all__ = [
    # CASC
    "D4CASCReader",
    # Texconv
    "TexconvConfig",
    "TexconvWrapper",
    "TexconvError",
    "TexconvNotFoundError",
    "WhiskyNotFoundError",
    "ConversionError",
    # Texture extraction
    "TextureExtractor",
    "TextureFrame",
    "TextureInfo",
    "TextureExtractionError",
    "InterleavedBC1Error",
    "EncryptedSNOError",
    # Texture definition (single source of truth for offsets)
    "TEX_DEF",
    "Field",
    "TextureDefinitionFields",
    "TexFrame",
    "TextureDefinition",
    "read_texture_definition",
    "resolve_vararray",
]
