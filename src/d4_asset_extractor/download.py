"""
Online CASC download utilities.

Downloads Diablo IV game data directly from Blizzard's CDN without
requiring a local game installation. Uses CASCConsole's online mode.

References:
    - CASCExplorer: https://github.com/WoW-Tools/CASCExplorer
    - Blizzard CDN: Uses TACT/NGDP protocol
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

console = Console()

# D4 product code for Blizzard CDN
D4_PRODUCT_CODE = "fenris"  # Internal codename for Diablo IV

# Default file patterns for different asset types
ASSET_PATTERNS = {
    "ui-icons": [
        "2DUI_Icons_Item_*",
        "2DUI_Icons_Skill_*",
        "2DUI_Icons_Buff_*",
        "2DUI_Icons_Achievement_*",
    ],
    "item-icons": [
        "2DUI_Icons_Item_*",
    ],
    "skill-icons": [
        "2DUI_Icons_Skill_*",
    ],
    "strings": [
        "StringList_*.stl",
    ],
    "strings-en": [
        "StringList_*enUS*.stl",
    ],
    "all-textures": [
        "*.tex",
    ],
    "minimal": [
        "2DUI_Icons_Item_Helm_*.tex",
        "2DUI_Icons_Item_Weapon_*.tex",
        "StringList_*enUS*.stl",
    ],
}


@dataclass
class DownloadManifest:
    """Tracks what was downloaded and when."""
    download_date: str
    build_version: str
    product: str
    patterns: list[str]
    file_count: int
    total_size_mb: float

    def save(self, path: Path) -> None:
        with open(path, "w") as f:
            json.dump({
                "download_date": self.download_date,
                "build_version": self.build_version,
                "product": self.product,
                "patterns": self.patterns,
                "file_count": self.file_count,
                "total_size_mb": self.total_size_mb,
            }, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> Optional["DownloadManifest"]:
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return cls(**data)
        except Exception:
            return None


class OnlineDownloader:
    """
    Download D4 assets from Blizzard CDN using CASCConsole.

    CASCConsole supports online mode with syntax:
        CASCConsole.exe online:<product> -o <output> -f <filter> -e

    Attributes:
        casc_console_path: Path to CASCConsole.exe
        output_dir: Directory to save downloaded files
    """

    def __init__(
        self,
        casc_console_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.casc_console_path = casc_console_path or Path("tools/CASCConsole.exe")
        self.output_dir = output_dir or Path("./game-data")

    def check_casc_console(self) -> bool:
        """Check if CASCConsole.exe is available."""
        return self.casc_console_path.exists()

    def get_available_builds(self) -> list[str]:
        """
        Query available D4 builds from CDN.

        Note: This requires parsing CASCConsole output or using
        the Ribbit protocol directly. For now, returns empty list
        and relies on CASCConsole to use latest.
        """
        # CASCConsole auto-selects latest build when using online mode
        return []

    def download(
        self,
        patterns: list[str],
        build: Optional[str] = None,
    ) -> DownloadManifest:
        """
        Download files matching patterns from Blizzard CDN.

        Args:
            patterns: List of file patterns to download
            build: Specific build version (None = latest)

        Returns:
            DownloadManifest with download details
        """
        if not self.check_casc_console():
            raise FileNotFoundError(
                f"CASCConsole.exe not found at {self.casc_console_path}\n"
                "Download from: https://github.com/WoW-Tools/CASCExplorer/releases"
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)

        total_files = 0

        for pattern in patterns:
            # Build command for online extraction
            # Format: CASCConsole.exe online:fenris -o <output> -f <filter> -e
            cmd = [
                str(self.casc_console_path),
                f"online:{D4_PRODUCT_CODE}",
                "-o", str(self.output_dir),
                "-f", pattern,
                "-e",  # Extract mode
            ]

            console.print(f"[dim]Downloading: {pattern}[/dim]")

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 minute timeout per pattern
                )

                # Parse output for file count
                for line in result.stdout.split("\n"):
                    if "extracted" in line.lower():
                        try:
                            count = int("".join(filter(str.isdigit, line)))
                            total_files += count
                        except ValueError:
                            pass

            except subprocess.TimeoutExpired:
                console.print(f"[yellow]Warning: Timeout downloading {pattern}[/yellow]")
            except subprocess.CalledProcessError as e:
                console.print(f"[yellow]Warning: Failed {pattern}: {e}[/yellow]")

        # Calculate total size
        total_size = sum(
            f.stat().st_size
            for f in self.output_dir.rglob("*")
            if f.is_file()
        )

        # Create manifest
        manifest = DownloadManifest(
            download_date=datetime.now().isoformat(),
            build_version=build or "latest",
            product=D4_PRODUCT_CODE,
            patterns=patterns,
            file_count=total_files,
            total_size_mb=total_size / (1024 * 1024),
        )

        manifest.save(self.output_dir / "manifest.json")

        return manifest


# CLI commands
app = typer.Typer(
    name="d4-download",
    help="Download Diablo IV game data from Blizzard CDN.",
    add_completion=False,
)


@app.command("list-presets")
def list_presets() -> None:
    """Show available download presets."""
    table = Table(title="Download Presets")
    table.add_column("Preset", style="cyan")
    table.add_column("Patterns")
    table.add_column("Description")

    descriptions = {
        "minimal": "Small test set (~50MB) - few icons + English strings",
        "ui-icons": "All UI icons (~500MB) - items, skills, buffs, achievements",
        "item-icons": "Item icons only (~200MB)",
        "skill-icons": "Skill icons only (~100MB)",
        "strings": "All language strings (~50MB)",
        "strings-en": "English strings only (~5MB)",
        "all-textures": "ALL textures (~10GB+) - use with caution",
    }

    for name, patterns in ASSET_PATTERNS.items():
        table.add_row(
            name,
            ", ".join(patterns[:2]) + ("..." if len(patterns) > 2 else ""),
            descriptions.get(name, ""),
        )

    console.print(table)


@app.command("fetch")
def fetch(
    preset: Optional[str] = typer.Argument(
        None,
        help="Preset name (run 'list-presets' to see options)",
    ),
    output_dir: Path = typer.Option(
        Path("./game-data"),
        "--output", "-o",
        help="Output directory for downloaded files",
    ),
    pattern: Optional[list[str]] = typer.Option(
        None,
        "--pattern", "-p",
        help="Custom file pattern(s) to download",
    ),
    casc_console: Path = typer.Option(
        Path("tools/CASCConsole.exe"),
        "--casc-console",
        help="Path to CASCConsole.exe",
    ),
) -> None:
    """
    Download D4 game data from Blizzard CDN.

    Requires CASCConsole.exe but NOT a D4 installation.

    Examples:
        d4-download fetch minimal
        d4-download fetch ui-icons -o ./icons
        d4-download fetch --pattern "2DUI_Icons_Item_Helm*"
    """
    # Determine patterns to use
    if pattern:
        patterns = list(pattern)
    elif preset:
        if preset not in ASSET_PATTERNS:
            console.print(f"[red]Unknown preset: {preset}[/red]")
            console.print("Run 'd4-download list-presets' to see options.")
            raise typer.Exit(1)
        patterns = ASSET_PATTERNS[preset]
    else:
        console.print("[red]Specify a preset or --pattern[/red]")
        console.print("Run 'd4-download list-presets' to see options.")
        raise typer.Exit(1)

    console.print(f"[bold blue]Diablo IV Online Downloader[/bold blue]")
    console.print(f"  Output: {output_dir}")
    console.print(f"  Patterns: {', '.join(patterns)}")
    console.print()

    downloader = OnlineDownloader(
        casc_console_path=casc_console,
        output_dir=output_dir,
    )

    if not downloader.check_casc_console():
        console.print("[red]Error: CASCConsole.exe not found[/red]")
        console.print()
        console.print("Download from:")
        console.print("  https://github.com/WoW-Tools/CASCExplorer/releases")
        console.print()
        console.print(f"Place CASCConsole.exe in: {casc_console}")
        raise typer.Exit(1)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading from Blizzard CDN...", total=None)
            manifest = downloader.download(patterns)
            progress.update(task, completed=True)

        console.print()
        console.print(f"[green]Download complete![/green]")
        console.print(f"  Files: {manifest.file_count}")
        console.print(f"  Size: {manifest.total_size_mb:.1f} MB")
        console.print(f"  Location: {output_dir.absolute()}")
        console.print(f"  Manifest: {output_dir / 'manifest.json'}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Download cancelled.[/yellow]")
        raise typer.Exit(130)


@app.command("status")
def status(
    data_dir: Path = typer.Argument(
        Path("./game-data"),
        help="Game data directory to check",
    ),
) -> None:
    """Check status of downloaded game data."""
    manifest_path = data_dir / "manifest.json"
    manifest = DownloadManifest.load(manifest_path)

    if not manifest:
        console.print(f"[yellow]No manifest found in {data_dir}[/yellow]")
        console.print("Run 'd4-download fetch <preset>' to download data.")
        raise typer.Exit(1)

    console.print(f"[bold blue]Downloaded Game Data[/bold blue]")
    console.print(f"  Directory: {data_dir.absolute()}")
    console.print(f"  Downloaded: {manifest.download_date}")
    console.print(f"  Build: {manifest.build_version}")
    console.print(f"  Files: {manifest.file_count}")
    console.print(f"  Size: {manifest.total_size_mb:.1f} MB")
    console.print(f"  Patterns: {', '.join(manifest.patterns)}")

    # Check actual files
    tex_count = len(list(data_dir.rglob("*.tex")))
    stl_count = len(list(data_dir.rglob("*.stl")))

    console.print()
    console.print(f"  .tex files: {tex_count}")
    console.print(f"  .stl files: {stl_count}")


def main() -> None:
    """Entry point for d4-download CLI."""
    app()


if __name__ == "__main__":
    main()
