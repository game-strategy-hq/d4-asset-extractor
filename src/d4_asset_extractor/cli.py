"""
Diablo IV Asset Extractor CLI.

Simple, opinionated extraction - reads directly from CASC, outputs to ./output/
"""

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from d4_asset_extractor import __version__
from d4_asset_extractor.texconv import TexconvConfig

app = typer.Typer(
    name="d4-extract",
    help="Extract Diablo IV textures from CASC storage. Pure Python, no external tools.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

# Default output structure
OUTPUT_DIR = Path("./output")


def version_callback(value: bool) -> None:
    if value:
        console.print(f"d4-asset-extractor v{__version__}")
        raise typer.Exit()


@app.command()
def extract(
    game_dir: Path = typer.Argument(
        ...,
        help="Path to Diablo IV installation.",
        exists=True,
    ),
    filter_pattern: str = typer.Option(
        "2DUI*",
        "--filter",
        "-f",
        help="Filter pattern (e.g., '2DUI*', 'Items*', '*').",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Limit textures (for testing).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-V",
        help="Show details.",
    ),
    no_texconv: bool = typer.Option(
        False,
        "--no-texconv",
        help="Disable texconv, use Python decoders only.",
    ),
) -> None:
    """
    Extract textures from D4 game files.

    Output: ./output/textures/<name>.png
    """
    from d4_asset_extractor.texture_extractor import TextureExtractor

    output = OUTPUT_DIR / "textures"
    output.mkdir(parents=True, exist_ok=True)

    texconv_config = TexconvConfig() if not no_texconv else None

    console.print("[bold blue]D4 Asset Extractor[/bold blue]")
    console.print(f"  Game: {game_dir}")
    console.print(f"  Filter: {filter_pattern}")
    console.print()

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Loading...", total=None)
            extractor = TextureExtractor(game_dir, texconv_config=texconv_config)
            progress.update(task, completed=True, total=1)

        console.print(f"  Version: {extractor.version}")
        console.print(f"  Textures: {len(extractor.texture_index):,}")
        if not no_texconv:
            status = "[green]available[/green]" if extractor.texconv_available else "[yellow]not found[/yellow]"
            console.print(f"  texconv: {status}")
        console.print()

        # Write version info
        info_file = OUTPUT_DIR / "version.txt"
        info_file.write_text(f"Diablo IV {extractor.version}\n")

        textures = extractor.list_textures(filter_pattern)

        if not textures:
            console.print(f"[yellow]No textures matching '{filter_pattern}'[/yellow]")
            raise typer.Exit(0)

        if limit:
            textures = textures[:limit]

        console.print(f"Extracting {len(textures):,} textures...")

        # Track results
        extracted = 0
        skipped = 0
        failures: dict[str, int] = {}  # reason -> count

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("", total=len(textures))

            for sno_id, name in textures:
                output_path = output / f"{name}.png"

                if output_path.exists():
                    skipped += 1
                    progress.advance(task)
                    continue

                try:
                    if extractor.extract_texture_to_file(sno_id, output_path):
                        extracted += 1
                        if verbose:
                            console.print(f"  [green]✓[/green] {name}")
                    else:
                        reason = "decode_failed"
                        failures[reason] = failures.get(reason, 0) + 1
                        if verbose:
                            console.print(f"  [red]✗[/red] {name}")
                except Exception as e:
                    # Categorize the failure
                    err_name = type(e).__name__
                    reason = err_name.replace("Error", "").lower()
                    failures[reason] = failures.get(reason, 0) + 1
                    if verbose:
                        console.print(f"  [yellow]✗[/yellow] {name} ({reason})")

                progress.advance(task)

        # Summary
        console.print()
        console.print(f"[green]Extracted:[/green] {extracted}")
        if skipped:
            console.print(f"[dim]Skipped (existing):[/dim] {skipped}")
        if failures:
            total_failed = sum(failures.values())
            console.print(f"[yellow]Failed:[/yellow] {total_failed}")
            for reason, count in sorted(failures.items(), key=lambda x: -x[1]):
                console.print(f"  [dim]{reason}:[/dim] {count}")
        console.print()
        console.print(f"[blue]Output:[/blue] {output.absolute()}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def info(
    game_dir: Path = typer.Argument(
        ...,
        help="Path to Diablo IV installation.",
        exists=True,
    ),
) -> None:
    """Show game info."""
    from d4_asset_extractor.casc_reader import D4CASCReader

    try:
        reader = D4CASCReader(game_dir)

        console.print(f"[bold]Diablo IV[/bold]")
        console.print(f"  Version: {reader.version}")
        console.print(f"  Build: {reader.build_uid}")
        console.print(f"  Files: {len(reader.file_table):,}")

        data_files = list(reader.data_path.glob("data.*"))
        total_size = sum(f.stat().st_size for f in data_files)
        console.print(f"  Size: {total_size / (1024**3):.1f} GB")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command(name="list")
def list_textures(
    game_dir: Path = typer.Argument(
        ...,
        help="Path to Diablo IV installation.",
        exists=True,
    ),
    filter_pattern: str = typer.Option(
        "2DUI*",
        "--filter",
        "-f",
        help="Filter pattern.",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-l",
        help="Max to show.",
    ),
) -> None:
    """List available textures."""
    from d4_asset_extractor.texture_extractor import TextureExtractor

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Loading...", total=None)
            extractor = TextureExtractor(game_dir)
            progress.update(task, completed=True, total=1)

        textures = extractor.list_textures(filter_pattern)

        console.print(f"[bold]{len(textures):,} textures matching '{filter_pattern}'[/bold]")
        console.print()

        for sno_id, name in textures[:limit]:
            tex_info = extractor.get_texture_info(sno_id)
            if tex_info:
                console.print(f"  {name}  [dim]{tex_info.width}x{tex_info.height}[/dim]")
            else:
                console.print(f"  {name}")

        if len(textures) > limit:
            console.print(f"\n  [dim]... {len(textures) - limit} more[/dim]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def icons(
    game_dir: Path = typer.Argument(
        ...,
        help="Path to Diablo IV installation.",
        exists=True,
    ),
    filter_pattern: str = typer.Option(
        "2DUI*",
        "--filter",
        "-f",
        help="Filter pattern for texture atlases.",
    ),
    min_size: int = typer.Option(
        16,
        "--min-size",
        help="Minimum icon dimension.",
    ),
    max_size: int = typer.Option(
        256,
        "--max-size",
        help="Maximum icon dimension.",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Limit atlases to process (for testing).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-V",
        help="Show details.",
    ),
    no_texconv: bool = typer.Option(
        False,
        "--no-texconv",
        help="Disable texconv, use Python decoders only.",
    ),
) -> None:
    """
    Extract individual icons from texture atlases.

    Output: ./output/icons/<atlas_name>/<index>_WxH.png
    """
    from d4_asset_extractor.texture_extractor import TextureExtractor

    output = OUTPUT_DIR / "icons"
    output.mkdir(parents=True, exist_ok=True)

    texconv_config = TexconvConfig() if not no_texconv else None

    console.print("[bold blue]D4 Icon Extractor[/bold blue]")
    console.print(f"  Game: {game_dir}")
    console.print(f"  Filter: {filter_pattern}")
    console.print(f"  Size range: {min_size}-{max_size}px")
    console.print()

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Loading...", total=None)
            extractor = TextureExtractor(game_dir, texconv_config=texconv_config)
            progress.update(task, completed=True, total=1)

        # Show texconv status
        if not no_texconv:
            if extractor.texconv_available:
                console.print("[green]texconv:[/green] available")
            else:
                console.print("[yellow]texconv:[/yellow] not found (using Python decoders)")
        console.print()

        textures = extractor.list_textures(filter_pattern)

        if not textures:
            console.print(f"[yellow]No textures matching '{filter_pattern}'[/yellow]")
            raise typer.Exit(0)

        if limit:
            textures = textures[:limit]

        console.print(f"Processing {len(textures):,} texture atlases...")

        total_icons = 0
        atlases_with_icons = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("", total=len(textures))

            for sno_id, name in textures:
                saved = extractor.slice_texture(
                    sno_id, output, min_size=min_size, max_size=max_size
                )

                if saved:
                    atlases_with_icons += 1
                    total_icons += len(saved)
                    if verbose:
                        console.print(f"  [green]✓[/green] {name}: {len(saved)} icons")

                progress.advance(task)

        console.print()
        console.print(f"[green]Atlases processed:[/green] {atlases_with_icons}")
        console.print(f"[green]Icons extracted:[/green] {total_icons}")
        console.print()
        console.print(f"[blue]Output:[/blue] {output.absolute()}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.callback()
def callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version.",
    ),
) -> None:
    """Extract textures from Diablo IV game files."""
    pass


def main_entry() -> None:
    app()


if __name__ == "__main__":
    main_entry()
