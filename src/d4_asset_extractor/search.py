"""
Image similarity search for extracted Diablo IV sprites.

Uses perceptual hashing (dHash) to find visually similar images.
Useful for identifying items from screenshots or finding related assets.

References:
    - imagehash library: https://github.com/JohannesBuchner/imagehash
    - di-asset-extractor search: Similar implementation for Diablo Immortal
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from PIL import Image
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

try:
    import imagehash
except ImportError:
    imagehash = None  # type: ignore

console = Console()

# Index file for caching hashes
INDEX_FILENAME = ".sprite-index.json"
INDEX_VERSION = 1


@dataclass
class SearchResult:
    """A single search result with similarity info."""
    path: Path
    distance: int
    hash_value: str

    @property
    def similarity_percent(self) -> float:
        """Convert hamming distance to similarity percentage (64-bit hash)."""
        return max(0, (64 - self.distance) / 64 * 100)


class SpriteIndex:
    """
    Index of sprite hashes for fast similarity search.

    Caches perceptual hashes of all sprites in a directory
    for efficient repeated searches.

    Attributes:
        sprites_dir: Directory containing sprite images
        index_path: Path to the index cache file
    """

    def __init__(self, sprites_dir: Path) -> None:
        self.sprites_dir = Path(sprites_dir)
        self.index_path = self.sprites_dir / INDEX_FILENAME
        self._hashes: dict[str, str] = {}
        self._loaded = False

    def load_or_build(self, force_rebuild: bool = False) -> int:
        """
        Load existing index or build a new one.

        Args:
            force_rebuild: If True, always rebuild even if index exists

        Returns:
            Number of sprites indexed
        """
        if not force_rebuild and self._try_load_index():
            return len(self._hashes)

        return self._build_index()

    def _try_load_index(self) -> bool:
        """Try to load existing index from disk."""
        if not self.index_path.exists():
            return False

        try:
            with open(self.index_path) as f:
                data = json.load(f)

            # Check version
            if data.get("version") != INDEX_VERSION:
                return False

            # Check if sprites directory hasn't changed significantly
            current_count = len(list(self.sprites_dir.glob("*.png")))
            indexed_count = len(data.get("hashes", {}))

            # Rebuild if count differs by more than 10%
            if abs(current_count - indexed_count) > indexed_count * 0.1:
                return False

            self._hashes = data.get("hashes", {})
            self._loaded = True
            return True

        except (json.JSONDecodeError, KeyError):
            return False

    def _build_index(self) -> int:
        """Build a new index by hashing all sprites."""
        if imagehash is None:
            raise ImportError(
                "imagehash library required for search. "
                "Install with: pip install imagehash"
            )

        self._hashes = {}

        # Find all image files
        extensions = ["*.png", "*.jpg", "*.jpeg", "*.webp"]
        image_files = []
        for ext in extensions:
            image_files.extend(self.sprites_dir.glob(ext))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Building sprite index...", total=len(image_files))

            for image_path in image_files:
                try:
                    img = Image.open(image_path)
                    # Use difference hash (dHash) - good for shape matching
                    hash_value = str(imagehash.dhash(img))
                    self._hashes[str(image_path.relative_to(self.sprites_dir))] = hash_value
                except Exception:
                    pass  # Skip invalid images
                progress.advance(task)

        # Save index
        self._save_index()
        self._loaded = True

        return len(self._hashes)

    def _save_index(self) -> None:
        """Save index to disk."""
        data = {
            "version": INDEX_VERSION,
            "sprites_dir": str(self.sprites_dir),
            "hashes": self._hashes,
        }

        with open(self.index_path, "w") as f:
            json.dump(data, f)

    def search(self, query_image: Path, top_n: int = 10) -> list[SearchResult]:
        """
        Search for sprites similar to the query image.

        Args:
            query_image: Path to the image to search for
            top_n: Number of results to return

        Returns:
            List of SearchResult sorted by similarity (most similar first)
        """
        if imagehash is None:
            raise ImportError(
                "imagehash library required for search. "
                "Install with: pip install imagehash"
            )

        if not self._loaded:
            self.load_or_build()

        # Hash the query image
        query_img = Image.open(query_image)
        query_hash = imagehash.dhash(query_img)

        # Compare to all indexed sprites
        results = []
        for rel_path, hash_str in self._hashes.items():
            sprite_hash = imagehash.hex_to_hash(hash_str)
            distance = query_hash - sprite_hash
            results.append(SearchResult(
                path=self.sprites_dir / rel_path,
                distance=distance,
                hash_value=hash_str,
            ))

        # Sort by distance (lower = more similar)
        results.sort(key=lambda r: r.distance)

        return results[:top_n]


def search_sprites(
    query_image: Path,
    sprites_dir: Path,
    top_n: int = 10,
    rebuild_index: bool = False,
    copy_results: bool = True,
) -> list[SearchResult]:
    """
    Search for sprites similar to a query image.

    Args:
        query_image: Path to the image to search for
        sprites_dir: Directory containing extracted sprites
        top_n: Number of results to return
        rebuild_index: Force rebuild of the sprite index
        copy_results: Copy matching sprites to search-results/ directory

    Returns:
        List of search results
    """
    index = SpriteIndex(sprites_dir)
    index.load_or_build(force_rebuild=rebuild_index)

    results = index.search(query_image, top_n=top_n)

    if copy_results and results:
        results_dir = Path("search-results")
        results_dir.mkdir(exist_ok=True)

        import shutil
        for i, result in enumerate(results):
            dest = results_dir / f"{i:02d}_{result.path.name}"
            shutil.copy(result.path, dest)

    return results


# CLI App
app = typer.Typer(
    name="d4-search",
    help="Search for similar sprites in extracted Diablo IV assets.",
    add_completion=False,
)


@app.command()
def search(
    query_image: Path = typer.Argument(
        ...,
        help="Image to search for (screenshot, icon, etc.)",
        exists=True,
    ),
    sprites_dir: Path = typer.Argument(
        Path("./textures"),
        help="Directory containing extracted sprites",
    ),
    top: int = typer.Option(
        10,
        "--top",
        "-n",
        help="Number of results to show",
    ),
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        "-r",
        help="Force rebuild of sprite index",
    ),
    no_copy: bool = typer.Option(
        False,
        "--no-copy",
        help="Don't copy results to search-results/ directory",
    ),
) -> None:
    """
    Find sprites visually similar to a query image.

    Uses perceptual hashing to find matches even with slight differences
    in size, color, or compression artifacts.

    Examples:
        d4-search screenshot.png ./textures --top 20
        d4-search item_icon.png ./extracted/2DUI --rebuild
    """
    if imagehash is None:
        console.print("[red]Error:[/red] imagehash library not installed.")
        console.print("Install with: pip install imagehash")
        raise typer.Exit(1)

    if not sprites_dir.exists():
        console.print(f"[red]Error:[/red] Sprites directory not found: {sprites_dir}")
        raise typer.Exit(1)

    console.print(f"[bold blue]Diablo IV Sprite Search[/bold blue]")
    console.print(f"  Query: {query_image}")
    console.print(f"  Sprites: {sprites_dir}")
    console.print()

    try:
        results = search_sprites(
            query_image=query_image,
            sprites_dir=sprites_dir,
            top_n=top,
            rebuild_index=rebuild,
            copy_results=not no_copy,
        )

        if not results:
            console.print("[yellow]No matching sprites found.[/yellow]")
            raise typer.Exit(0)

        # Display results table
        table = Table(title=f"Top {len(results)} Matches")
        table.add_column("Rank", style="dim", width=4)
        table.add_column("Similarity", justify="right")
        table.add_column("File")

        for i, result in enumerate(results, 1):
            similarity = f"{result.similarity_percent:.1f}%"
            color = "green" if result.similarity_percent > 80 else (
                "yellow" if result.similarity_percent > 60 else "dim"
            )
            table.add_row(
                str(i),
                f"[{color}]{similarity}[/{color}]",
                result.path.name,
            )

        console.print(table)

        if not no_copy:
            console.print()
            console.print(f"[blue]Results copied to:[/blue] ./search-results/")

    except KeyboardInterrupt:
        console.print("\n[yellow]Search cancelled.[/yellow]")
        raise typer.Exit(130)


def main() -> None:
    """Main entry point for d4-search CLI."""
    app()


if __name__ == "__main__":
    main()
