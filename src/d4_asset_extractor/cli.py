"""
Command-line interface for Diablo IV asset extraction.

Usage:
    d4-extract textures <game_dir> [output_dir] [--filter PATTERN] [--format FORMAT]
    d4-extract strings <game_dir> [output_dir]
    d4-extract data <game_dir> [output_dir]
    d4-extract all <game_dir> [output_dir]
"""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from d4_asset_extractor import __version__
from d4_asset_extractor.casc import CASCExtractor, find_game_directory
from d4_asset_extractor.texture import TextureConverter
from d4_asset_extractor.strings import StringListParser

app = typer.Typer(
    name="d4-extract",
    help="Extract Diablo IV game assets from CASC storage.",
    add_completion=False,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"d4-asset-extractor v{__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False, "--version", "-v", callback=version_callback, help="Show version and exit."
    ),
) -> None:
    """Diablo IV Asset Extractor - Extract textures, strings, and game data."""
    pass


@app.command()
def textures(
    game_dir: Path = typer.Argument(
        ...,
        help="Path to Diablo IV installation directory.",
        exists=True,
        dir_okay=True,
        file_okay=False,
    ),
    output_dir: Optional[Path] = typer.Argument(
        None,
        help="Output directory for extracted textures. Defaults to ./textures",
    ),
    filter_pattern: str = typer.Option(
        "*",
        "--filter",
        "-f",
        help="Filter pattern for texture names (e.g., '2DUI*' for UI icons, 'Items*' for items).",
    ),
    output_format: str = typer.Option(
        "png",
        "--format",
        "-o",
        help="Output image format: png, jpg, or webp.",
    ),
    no_crop: bool = typer.Option(
        False,
        "--no-crop",
        "-nc",
        help="Disable automatic cropping of transparent borders.",
    ),
    no_slice: bool = typer.Option(
        False,
        "--no-slice",
        "-ns",
        help="Disable slicing of texture atlases.",
    ),
    concurrency: int = typer.Option(
        4,
        "--concurrency",
        "-c",
        help="Number of parallel conversion tasks.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-V",
        help="Show debug output from CASCConsole.",
    ),
) -> None:
    """
    Extract and convert .tex texture files to standard image formats.

    Examples:
        d4-extract textures "C:\\Program Files\\Diablo IV" ./icons --filter "2DUI*"
        d4-extract textures /path/to/d4 --format webp --filter "Items*"
    """
    output = output_dir or Path("./textures")
    output.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold blue]Diablo IV Texture Extractor[/bold blue]")
    console.print(f"  Game directory: {game_dir}")
    console.print(f"  Output directory: {output}")
    console.print(f"  Filter: {filter_pattern}")
    console.print(f"  Format: {output_format}")
    console.print()

    try:
        # Initialize CASC extractor
        casc = CASCExtractor(game_dir)
        if not casc.is_valid():
            console.print(
                "[red]Error:[/red] Could not find valid Diablo IV CASC data. "
                "Make sure the game is installed."
            )
            raise typer.Exit(1)

        # Extract .tex files
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Extracting CASC files...", total=None)
            tex_files = casc.extract_textures(filter_pattern=filter_pattern, verbose=verbose)
            progress.update(task, completed=True, total=1)

            if not tex_files:
                console.print(f"[yellow]No texture files found matching '{filter_pattern}'[/yellow]")
                raise typer.Exit(0)

            # Find meta and payload directories
            extracted_base = Path("extracted/textures/Base")
            meta_dir = extracted_base / "meta" / "Texture"
            payload_dir = extracted_base / "payload" / "Texture"

            if not meta_dir.exists() or not payload_dir.exists():
                console.print("[red]Error:[/red] Expected meta and payload directories not found.")
                console.print(f"  Looking for: {meta_dir}")
                console.print(f"  And: {payload_dir}")
                raise typer.Exit(1)

            # Get payload files (the actual texture data)
            payload_files = list(payload_dir.glob("*.tex"))
            console.print(f"Found {len(payload_files)} texture files")

            task = progress.add_task("Converting textures...", total=len(payload_files))
            converted = 0
            failed = 0

            from .tex_converter import convert_tex_to_png

            for payload_file in payload_files:
                meta_file = meta_dir / payload_file.name
                if not meta_file.exists():
                    if verbose:
                        console.print(f"[dim]Skipping {payload_file.name} - no meta file[/dim]")
                    progress.advance(task)
                    continue

                try:
                    output_path = output / f"{payload_file.stem}.{output_format}"
                    success = convert_tex_to_png(
                        meta_file, payload_file, output_path,
                        crop=not no_crop
                    )
                    if success:
                        converted += 1
                    else:
                        failed += 1
                except Exception as e:
                    if verbose:
                        console.print(f"[dim]Failed: {payload_file.name} - {e}[/dim]")
                    failed += 1
                progress.advance(task)

        console.print()
        console.print(f"[green]Converted:[/green] {converted} textures")
        if failed:
            console.print(f"[yellow]Failed:[/yellow] {failed} textures")
        console.print(f"[blue]Output:[/blue] {output.absolute()}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Extraction cancelled.[/yellow]")
        raise typer.Exit(130)


@app.command()
def strings(
    game_dir: Path = typer.Argument(
        ...,
        help="Path to Diablo IV installation directory or extracted CASC files.",
        exists=True,
    ),
    output_dir: Optional[Path] = typer.Argument(
        None,
        help="Output directory for parsed string files. Defaults to ./strings",
    ),
    language: str = typer.Option(
        "enUS",
        "--language",
        "-l",
        help="Language code to extract (e.g., enUS, deDE, frFR).",
    ),
) -> None:
    """
    Parse .stl (StringList) files to JSON format.

    StringList files contain all game text: item names, skill descriptions,
    UI labels, dialog, etc.

    Examples:
        d4-extract strings "C:\\Program Files\\Diablo IV" ./strings
        d4-extract strings ./extracted-casc --language deDE
    """
    output = output_dir or Path("./strings")
    output.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold blue]Diablo IV String Extractor[/bold blue]")
    console.print(f"  Source: {game_dir}")
    console.print(f"  Output: {output}")
    console.print(f"  Language: {language}")
    console.print()

    try:
        parser = StringListParser()

        # Find .stl files
        stl_files = list(game_dir.rglob("*.stl"))
        if not stl_files:
            console.print("[yellow]No .stl files found. You may need to extract CASC first.[/yellow]")
            console.print("Run: d4-extract casc <game_dir> to extract raw files.")
            raise typer.Exit(0)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Parsing string files...", total=len(stl_files))
            parsed = 0
            failed = 0

            for stl_file in stl_files:
                try:
                    result = parser.parse(stl_file)
                    output_file = output / f"{stl_file.stem}.json"
                    parser.save_json(result, output_file)
                    parsed += 1
                except Exception as e:
                    console.print(f"[dim]Failed: {stl_file.name} - {e}[/dim]")
                    failed += 1
                progress.advance(task)

        console.print()
        console.print(f"[green]Parsed:[/green] {parsed} string files")
        if failed:
            console.print(f"[yellow]Failed:[/yellow] {failed} files")
        console.print(f"[blue]Output:[/blue] {output.absolute()}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Extraction cancelled.[/yellow]")
        raise typer.Exit(130)


@app.command()
def casc(
    game_dir: Path = typer.Argument(
        ...,
        help="Path to Diablo IV installation directory.",
        exists=True,
    ),
    output_dir: Optional[Path] = typer.Argument(
        None,
        help="Output directory for extracted files. Defaults to ./extracted",
    ),
    filter_pattern: str = typer.Option(
        "*",
        "--filter",
        "-f",
        help="Filter pattern for files to extract.",
    ),
) -> None:
    """
    Extract raw files from CASC storage using CASCConsole.

    This extracts the raw game files which can then be processed by other commands.
    Requires CASCConsole.exe in the tools/ directory.

    Examples:
        d4-extract casc "C:\\Program Files\\Diablo IV" ./extracted
        d4-extract casc /path/to/d4 --filter "*.stl"
    """
    output = output_dir or Path("./extracted")
    output.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold blue]Diablo IV CASC Extractor[/bold blue]")
    console.print(f"  Game directory: {game_dir}")
    console.print(f"  Output: {output}")
    console.print(f"  Filter: {filter_pattern}")
    console.print()

    casc_console = _find_tool("CASCConsole.exe")
    if not casc_console.exists():
        console.print("[red]Error:[/red] CASCConsole.exe not found.")
        console.print()
        console.print("Run setup first:")
        console.print("  d4-extract setup")
        raise typer.Exit(1)


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

    # Return user tools path as default
    return user_tools

    try:
        extractor = CASCExtractor(game_dir, casc_console_path=casc_console)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Extracting CASC files...", total=None)
            extracted = extractor.extract_all(output, filter_pattern=filter_pattern)
            progress.update(task, completed=True)

        console.print()
        console.print(f"[green]Extracted:[/green] {extracted} files")
        console.print(f"[blue]Output:[/blue] {output.absolute()}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Extraction cancelled.[/yellow]")
        raise typer.Exit(130)


@app.command()
def info(
    game_dir: Optional[Path] = typer.Argument(
        None,
        help="Path to Diablo IV installation directory. Auto-detected if not specified.",
    ),
) -> None:
    """
    Display information about Diablo IV installation and CASC storage.

    Auto-detects common installation paths if not specified.
    """
    if game_dir is None:
        game_dir = find_game_directory()
        if game_dir is None:
            console.print("[yellow]Could not auto-detect Diablo IV installation.[/yellow]")
            console.print()
            console.print("Please specify the path manually:")
            console.print("  d4-extract info \"C:\\Program Files\\Diablo IV\"")
            raise typer.Exit(1)
        console.print(f"[dim]Auto-detected: {game_dir}[/dim]")
        console.print()

    casc = CASCExtractor(game_dir)

    console.print(f"[bold blue]Diablo IV Installation Info[/bold blue]")
    console.print()
    console.print(f"  Path: {game_dir}")
    console.print(f"  Valid CASC: {'[green]Yes[/green]' if casc.is_valid() else '[red]No[/red]'}")

    if casc.is_valid():
        info = casc.get_info()
        console.print(f"  Build: {info.get('build', 'Unknown')}")
        console.print(f"  Data files: {info.get('data_files', 0)}")
        console.print(f"  Total size: {info.get('total_size_gb', 0):.2f} GB")


@app.command()
def setup() -> None:
    """
    Download required tools (CASCConsole.exe, texconv.exe).

    Downloads tools to ~/.d4-tools/ for use by the extractor.
    """
    import urllib.request
    import zipfile
    import io

    tools_dir = Path.home() / ".d4-tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    console.print("[bold blue]D4 Asset Extractor Setup[/bold blue]")
    console.print(f"  Tools directory: {tools_dir}")
    console.print()

    # CASCConsole (separate zip from CASCExplorer releases)
    casc_url = "https://github.com/WoW-Tools/CASCExplorer/releases/download/CASCExplorer-v1.0.240/CASCConsole.zip"
    casc_exe = tools_dir / "CASCConsole.exe"

    if casc_exe.exists():
        console.print("[green]✓[/green] CASCConsole.exe already installed")
    else:
        console.print("Downloading CASCExplorer...", end=" ")
        try:
            with urllib.request.urlopen(casc_url, timeout=60) as response:
                zip_data = response.read()
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                zf.extractall(tools_dir)
            console.print("[green]✓[/green]")
        except Exception as e:
            console.print(f"[red]✗[/red] {e}")

    # texconv
    texconv_url = "https://github.com/microsoft/DirectXTex/releases/download/oct2025/texconv.exe"
    texconv_exe = tools_dir / "texconv.exe"

    if texconv_exe.exists():
        console.print("[green]✓[/green] texconv.exe already installed")
    else:
        console.print("Downloading texconv.exe...", end=" ")
        try:
            with urllib.request.urlopen(texconv_url, timeout=60) as response:
                texconv_exe.write_bytes(response.read())
            console.print("[green]✓[/green]")
        except Exception as e:
            console.print(f"[red]✗[/red] {e}")

    console.print()

    # Verify
    all_good = True
    if not casc_exe.exists():
        console.print("[red]✗[/red] CASCConsole.exe not found")
        all_good = False
    if not texconv_exe.exists():
        console.print("[red]✗[/red] texconv.exe not found")
        all_good = False

    if all_good:
        console.print("[green]Setup complete![/green]")
        console.print()
        console.print("Next steps:")
        console.print('  d4-extract textures "C:\\Program Files\\Diablo IV" .\\icons --filter "2DUI*"')
    else:
        console.print()
        console.print("[yellow]Some tools failed to download. Try manually:[/yellow]")
        console.print(f"  CASCExplorer: https://github.com/WoW-Tools/CASCExplorer/releases")
        console.print(f"  texconv: https://github.com/microsoft/DirectXTex/releases")
        raise typer.Exit(1)


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
