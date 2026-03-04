<#
.SYNOPSIS
    Download Diablo IV game data from Blizzard CDN (no game installation required).

.DESCRIPTION
    Uses CASCConsole.exe to download D4 assets directly from Blizzard's CDN.
    This script handles:
    - Downloading CASCConsole if not present
    - Fetching specified asset presets
    - Creating a manifest of downloaded files

.PARAMETER Preset
    Download preset: minimal, ui-icons, item-icons, skill-icons, strings, strings-en
    Default: minimal

.PARAMETER OutputDir
    Output directory for downloaded files.
    Default: ./game-data

.PARAMETER CASCConsolePath
    Path to CASCConsole.exe. Will auto-download if not found.
    Default: ./tools/CASCConsole.exe

.EXAMPLE
    .\download-game-data.ps1 -Preset minimal
    Downloads a minimal test set (~50MB)

.EXAMPLE
    .\download-game-data.ps1 -Preset ui-icons -OutputDir ./icons
    Downloads all UI icons (~500MB)

.EXAMPLE
    .\download-game-data.ps1 -Preset strings-en
    Downloads English strings only (~5MB)
#>

param(
    [ValidateSet("minimal", "ui-icons", "item-icons", "skill-icons", "strings", "strings-en", "all-textures")]
    [string]$Preset = "minimal",

    [string]$OutputDir = "./game-data",

    [string]$CASCConsolePath = "./tools/CASCConsole.exe",

    [switch]$SkipDownloadTool
)

$ErrorActionPreference = "Stop"

# Diablo IV product code
$D4_PRODUCT = "fenris"

# Asset patterns by preset
$PRESETS = @{
    "minimal" = @(
        "2DUI_Icons_Item_Helm_*.tex",
        "2DUI_Icons_Item_Weapon_*.tex",
        "*enUS*.stl"
    )
    "ui-icons" = @(
        "2DUI_Icons_Item_*.tex",
        "2DUI_Icons_Skill_*.tex",
        "2DUI_Icons_Buff_*.tex",
        "2DUI_Icons_Achievement_*.tex"
    )
    "item-icons" = @(
        "2DUI_Icons_Item_*.tex"
    )
    "skill-icons" = @(
        "2DUI_Icons_Skill_*.tex"
    )
    "strings" = @(
        "*.stl"
    )
    "strings-en" = @(
        "*enUS*.stl"
    )
    "all-textures" = @(
        "*.tex"
    )
}

# CASCExplorer download URL
$CASC_RELEASE_URL = "https://github.com/WoW-Tools/CASCExplorer/releases/latest"

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Text)
    Write-Host "[*] $Text" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Text)
    Write-Host "[✓] $Text" -ForegroundColor Green
}

function Write-Error {
    param([string]$Text)
    Write-Host "[✗] $Text" -ForegroundColor Red
}

function Get-CASCConsole {
    param([string]$DestPath)

    $toolsDir = Split-Path $DestPath -Parent
    if (-not (Test-Path $toolsDir)) {
        New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
    }

    Write-Step "CASCConsole.exe not found. Downloading..."
    Write-Host ""
    Write-Host "  Please download manually from:" -ForegroundColor White
    Write-Host "  $CASC_RELEASE_URL" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Extract CASCConsole.exe to: $DestPath" -ForegroundColor White
    Write-Host ""

    # Try to open browser
    try {
        Start-Process $CASC_RELEASE_URL
    } catch {
        # Ignore if browser can't open
    }

    Write-Host "Press Enter after placing CASCConsole.exe in the tools folder..."
    Read-Host

    if (-not (Test-Path $DestPath)) {
        Write-Error "CASCConsole.exe still not found at $DestPath"
        exit 1
    }
}

function Download-Assets {
    param(
        [string]$CASCConsole,
        [string]$OutputDir,
        [string[]]$Patterns
    )

    $totalFiles = 0

    foreach ($pattern in $Patterns) {
        Write-Step "Downloading: $pattern"

        $args = @(
            "online:$D4_PRODUCT",
            "-o", $OutputDir,
            "-f", $pattern,
            "-e"
        )

        try {
            $result = & $CASCConsole @args 2>&1
            $output = $result | Out-String

            # Try to parse file count from output
            if ($output -match "(\d+)\s+file") {
                $totalFiles += [int]$Matches[1]
            }

            Write-Success "Completed: $pattern"
        } catch {
            Write-Host "  Warning: Some files may have failed for $pattern" -ForegroundColor Yellow
        }
    }

    return $totalFiles
}

function Create-Manifest {
    param(
        [string]$OutputDir,
        [string]$Preset,
        [string[]]$Patterns,
        [int]$FileCount
    )

    $totalSize = 0
    Get-ChildItem -Path $OutputDir -Recurse -File | ForEach-Object {
        $totalSize += $_.Length
    }
    $totalSizeMB = [math]::Round($totalSize / 1MB, 2)

    $manifest = @{
        download_date = (Get-Date -Format "o")
        build_version = "latest"
        product = $D4_PRODUCT
        preset = $Preset
        patterns = $Patterns
        file_count = $FileCount
        total_size_mb = $totalSizeMB
    }

    $manifestPath = Join-Path $OutputDir "manifest.json"
    $manifest | ConvertTo-Json -Depth 10 | Set-Content $manifestPath -Encoding UTF8

    return $manifest
}

# ═══════════════════════════════════════════════════════════════════════════
# Main Script
# ═══════════════════════════════════════════════════════════════════════════

Write-Header "Diablo IV Online Data Downloader"

Write-Host "  Preset:     $Preset" -ForegroundColor White
Write-Host "  Output:     $OutputDir" -ForegroundColor White
Write-Host "  CASC Tool:  $CASCConsolePath" -ForegroundColor White
Write-Host ""

# Check for CASCConsole
if (-not (Test-Path $CASCConsolePath)) {
    if ($SkipDownloadTool) {
        Write-Error "CASCConsole.exe not found and -SkipDownloadTool specified"
        exit 1
    }
    Get-CASCConsole -DestPath $CASCConsolePath
}

Write-Success "CASCConsole.exe found"

# Create output directory
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

# Get patterns for preset
$patterns = $PRESETS[$Preset]
Write-Step "Patterns to download:"
foreach ($p in $patterns) {
    Write-Host "    - $p" -ForegroundColor Gray
}
Write-Host ""

# Download
Write-Header "Downloading from Blizzard CDN"
Write-Host "  This may take a while depending on the preset size..." -ForegroundColor Gray
Write-Host ""

$fileCount = Download-Assets -CASCConsole $CASCConsolePath -OutputDir $OutputDir -Patterns $patterns

# Create manifest
Write-Step "Creating manifest..."
$manifest = Create-Manifest -OutputDir $OutputDir -Preset $Preset -Patterns $patterns -FileCount $fileCount

# Summary
Write-Header "Download Complete"
Write-Host "  Files downloaded: $($manifest.file_count)" -ForegroundColor Green
Write-Host "  Total size:       $($manifest.total_size_mb) MB" -ForegroundColor Green
Write-Host "  Location:         $(Resolve-Path $OutputDir)" -ForegroundColor Green
Write-Host "  Manifest:         $(Join-Path $OutputDir 'manifest.json')" -ForegroundColor Green
Write-Host ""

# Count by type
$texCount = (Get-ChildItem -Path $OutputDir -Filter "*.tex" -Recurse -ErrorAction SilentlyContinue).Count
$stlCount = (Get-ChildItem -Path $OutputDir -Filter "*.stl" -Recurse -ErrorAction SilentlyContinue).Count

Write-Host "  .tex files: $texCount" -ForegroundColor Gray
Write-Host "  .stl files: $stlCount" -ForegroundColor Gray
Write-Host ""

Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Convert textures:  d4-extract textures $OutputDir ./output" -ForegroundColor Gray
Write-Host "  2. Parse strings:     d4-extract strings $OutputDir ./strings" -ForegroundColor Gray
Write-Host ""
