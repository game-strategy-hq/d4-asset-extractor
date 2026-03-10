# Diablo IV Data Extraction Resources

This document catalogs all resources used to understand and implement Diablo IV asset extraction. These references informed the architecture, file format handling, and tooling decisions for this project.

---

## CASC Storage System

The foundational technology for D4 file storage.

### Technical Specifications

| Resource | URL | Description |
|----------|-----|-------------|
| **CASC Format Specification** | https://wowdev.wiki/CASC | Complete technical spec for Content Addressable Storage Container format. Covers data archives, index journals, encoding keys, and file identification. |
| **TACT Protocol** | https://wowdev.wiki/TACT | Trusted Application Content Transfer - the content delivery part of Blizzard's NGDP system. |
| **TVFS Documentation** | https://wowdev.wiki/TVFS | TACT Virtual File System - provides path-based access over content-addressed storage. |
| **CASC Overview (Zezula)** | http://www.zezula.net/en/casc/main.html | General overview of CASC technology and available tools. |
| **NGDP Wiki** | https://github.com/d07RiV/blizzget/wiki/NGDP | Next Generation Download Protocol documentation. |
| **FileDataID Reference** | https://wowpedia.fandom.com/wiki/FileDataID | How Blizzard identifies files across CASC storage. |

### Extraction Tools

| Resource | URL | Description |
|----------|-----|-------------|
| **CASCExplorer** | https://github.com/WoW-Tools/CASCExplorer | GUI/CLI tool for CASC extraction. Reference implementation. |
| **CASCExplorer Releases** | https://github.com/WoW-Tools/CASCExplorer/releases | Download page for CASCConsole.exe. |
| **Ladik's CASC Viewer** | https://www.hiveworkshop.com/threads/ladiks-casc-viewer.331540/ | Alternative CASC browser. |
| **jybp/casc** | https://github.com/jybp/casc | Rust library for CASC extraction - reference for format understanding. |
| **CascLib** | https://github.com/heksesang/CascLib | C++ CASC library - low-level implementation reference. |
| **cascette-rs** | https://github.com/wowemulation-dev/cascette-rs | Rust NGDP/CASC tools. |
| **blizzget** | https://github.com/d07RiV/blizzget | Blizzard CDN downloader with NGDP support. |

---

## Texture Extraction

Resources for understanding D4 texture formats and conversion.

### Primary References

| Resource | URL | Description |
|----------|-----|-------------|
| **d4-texture-extractor** | https://github.com/adainrivers/d4-texture-extractor | Node.js tool that extracts and converts D4 .tex files. Primary reference for texture pipeline. Archived May 2025 but functional. |
| **DirectXTex (texconv)** | https://github.com/microsoft/DirectXTex | Microsoft's texture processing tools. Used for DDS conversion. |

### Key Learnings from d4-texture-extractor

- `.tex` files require conversion to DDS intermediate format
- Texture filtering by pattern (e.g., `2DUI*`) isolates icon sets
- Atlas slicing needed for combined texture sheets
- Output formats: PNG (lossless), WebP (efficient), JPG (legacy)

### BC1 Interleaved Textures

Some D4 BC1 textures use a proprietary interleaved storage format with alternating data/zero blocks. texconv.exe handles these correctly when provided with the full payload data.

---

## Game Data Parsing

Resources for extracting structured game data (items, skills, strings).

### Data Repositories

| Resource | URL | Description |
|----------|-----|-------------|
| **DiabloTools/d4data** | https://github.com/DiabloTools/d4data | Pre-parsed JSON game data. Definitions, items, skills, aspects. Primary structured data source. |
| **d4data (blizzhackers)** | https://github.com/blizzhackers/d4data | Older/archived version of d4data. |
| **d4parse Documentation** | https://docs.diablo.farm/ | Documentation for d4parse tool and data formats. |

### Parsing Tools

| Resource | URL | Description |
|----------|-----|-------------|
| **d4parse** | https://github.com/Dakota628/d4parse | Go-based parser for SNO, TOC, and quest files. Reference for binary format understanding. |
| **diablo4-data-harvest** | https://github.com/mfloob/diablo4-data-harvest | Rust tool for .stl, .aff, .skl extraction. Archived Dec 2024. |
| **diablo-4-string-parser** | https://github.com/alkhdaniel/diablo-4-string-parser | Python .stl to JSON converter. Direct reference for StringList parsing implementation. |

### File Format Learnings

**StringList (.stl) Format:**
- Binary format with header + entry table + string pool
- Hash IDs (4 bytes) identify each string
- Supports multiple parsing approaches (table-based vs sequential)
- Language codes embedded in filenames (enUS, deDE, etc.)

**SNO Files:**
- Binary metadata structures
- Require specialized parsers (d4parse)
- Contain item definitions, skill data, world info

**TOC Files:**
- Table of contents / index format
- Convertible to YAML for inspection

---

## 3D Model Extraction

Resources for model/mesh extraction (optional feature).

| Resource | URL | Description |
|----------|-----|-------------|
| **DiabloTools Releases** | https://github.com/DiabloTools/Diablo4Tools-Releases | D4Analyzer tool for viewing and exporting models. |
| **Blender Template Guide** | https://www.deviantart.com/trappissy/art/Extract-Diablo-4-Blender-Template-Diablo4-1146664821 | Community workflow for D4 model extraction to Blender. |
| **ResHax D4 Forum** | https://reshax.com/topic/14-diablo-iv-app/ | Community discussion of .app model format. |
| **Sketchfab D4 Models** | https://sketchfab.com/tags/diablo4 | Community-extracted 3D models. |
| **DiabloFans Model Viewer** | https://www.diablofans.com/items/models | Online model viewer. |

---

## Community Databases

Existing databases that aggregate D4 data (useful for validation and comparison).

| Resource | URL | Description |
|----------|-----|-------------|
| **Diablo4.gg** | https://diablo4.gg/database/ | Comprehensive skills, items, enemies, aspects database. |
| **Maxroll D4** | https://maxroll.gg/d4/ | Build planner, guides, item database. |
| **Wowhead D4** | https://www.wowhead.com/diablo-4/database | Traditional wiki-style database. |
| **Diablo4.cc** | https://diablo4.cc/ | Items, recipes, aspects, paragon glyphs. |
| **D4Builds.gg** | https://d4builds.gg/ | Unique items and build organization. |
| **Lothrik Calculator** | https://lothrik.github.io/diablo4-build-calc/database/ | Build calculator with historical data tracking. |
| **Lothrik History** | https://lothrik.github.io/diablo4-build-calc/history/49213-49764.html | JSON comparison between game versions. |
| **TeamBRG D4DB** | https://teambrg.com/diablo-4/db | Skills and aspects database. |
| **Fextralife D4 Wiki** | https://diablo4.wiki.fextralife.com/Diablo+4+Wiki | Comprehensive guides and documentation. |
| **DaOpa D4 Site** | https://gamingwithdaopa.ellatha.com/diablo4/database-lists/ | Guides and database lists. |

---

## Web Scraping & Automation

Tools for gathering data from existing websites.

| Resource | URL | Description |
|----------|-----|-------------|
| **Maxroll D4 Scraper** | https://github.com/danparizher/maxroll-d4-scraper | Python scraper for maxroll.gg build data. Three-step pipeline: scraping, cleaning, translating. |

---

## Discord & Community Tools

| Resource | URL | Description |
|----------|-----|-------------|
| **Inarius Discord Bot** | https://github.com/ALCHElVlY/Inarius | Discord companion for D4 data queries. |
| **DiabloTools Organization** | https://github.com/DiabloTools | Central GitHub org for D4 extraction tools. |
| **Awesome-D4** | https://github.com/cagartner/awesome-d4 | Curated list of D4 projects and resources. |

---

## GitHub Discovery

| Resource | URL | Description |
|----------|-----|-------------|
| **Topic: diablo4** | https://github.com/topics/diablo4 | GitHub topic for D4 projects. |
| **Topic: diablo-4** | https://github.com/topics/diablo-4 | Alternative topic tag. |

---

## General Extraction Guides

| Resource | URL | Description |
|----------|-----|-------------|
| **WoW Data Extraction Cheat Sheet** | https://thunderysteak.github.io/wow-data-extract-cheat-sheet | General Blizzard game extraction techniques (applicable to D4). |
| **HIVE CASC Extraction Guide** | https://www.hiveworkshop.com/threads/extracting-game-files-mpq-and-casc.330895/ | Tutorial on CASC extraction. |
| **XeNTaX Forum D4 Thread** | https://forum.xen-tax.com/viewtopic.php@p=192300.html | Beta extraction discussion. |

---

## Architecture Decisions

### Why Python + texconv?

- **CASC reading**: Pure Python for cross-platform archive extraction
- **Texture decoding**: texconv.exe handles all BC formats correctly
- **macOS support**: Whisky (Wine wrapper) runs texconv transparently
- **CLI**: typer + rich for user-friendly interface

### Key Differences from Diablo Immortal

| Aspect | Diablo Immortal | Diablo IV |
|--------|-----------------|-----------|
| Storage | MPK (Netease) | CASC (Blizzard) |
| Engine | Cocos2d-based | Proprietary |
| Sprites | Atlas sheets + plist | Individual textures |
| Compression | LZ4 custom | CASC internal |
| Metadata | resource.repository | SNO/TOC files |
| Strings | Embedded | Separate .stl files |

This fundamental architecture difference means di-asset-extractor code cannot be directly reused - a new extraction pipeline was required.

---

## Version History

- **Initial Research**: March 2025
- **Project Created**: March 2025

---

## Contributing

Found a resource that should be documented here? Open a PR or issue.
