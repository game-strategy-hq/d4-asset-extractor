#!/usr/bin/env python3
"""
Fetch D4 item icons from Wowhead's CDN.

Wowhead serves D4 textures at URLs like:
    https://wow.zamimg.com/d4/d4/texture/hash/{category}/{hash}.webp

This script finds the correct category by trying multiple options.
"""

import sys
import json
import re
import asyncio
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

# CDN URL pattern
CDN_BASE = "https://wow.zamimg.com/d4/d4/texture/hash"

# Known working categories (discovered through testing)
CATEGORIES = [115, 110, 120, 100, 105, 125, 130, 135, 140, 145, 150]


def fetch_icon_hashes_from_wowhead() -> list[int]:
    """Fetch icon hashes from Wowhead's unique items page."""
    url = "https://www.wowhead.com/diablo-4/items/quality:6"

    print(f"Fetching icon hashes from {url}...")

    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8")
    except Exception as e:
        print(f"Error fetching page: {e}")
        return []

    # Extract icon hashes
    pattern = r'"icon":(\d+)'
    matches = re.findall(pattern, html)
    hashes = list(set(int(h) for h in matches))

    print(f"Found {len(hashes)} unique icon hashes")
    return hashes


def try_download_icon(icon_hash: int, output_dir: Path) -> bool:
    """Try to download an icon by testing different categories."""
    for cat in CATEGORIES:
        url = f"{CDN_BASE}/{cat}/{icon_hash}.webp"

        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as response:
                data = response.read()

                # Check if it's a valid image (not a 404 HTML page)
                if len(data) > 500 and not data.startswith(b"<html"):
                    output_path = output_dir / f"{icon_hash}.webp"
                    output_path.write_bytes(data)
                    print(f"  OK: {icon_hash}.webp ({len(data)} bytes, cat {cat})")
                    return True
        except HTTPError:
            continue
        except Exception as e:
            continue

    return False


def main():
    output_dir = Path("sample-data/icons")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get icon hashes
    hashes = fetch_icon_hashes_from_wowhead()

    if not hashes:
        print("No hashes found, using defaults...")
        hashes = [
            2578341230, 2484882547, 1012726263, 2397813549,
            3684888856, 4044736160, 1763195273, 2650964165,
        ]

    # Limit to first N for testing
    max_icons = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    hashes = hashes[:max_icons]

    print(f"\nDownloading up to {len(hashes)} icons...")

    success = 0
    failed = 0

    for i, h in enumerate(hashes, 1):
        print(f"[{i}/{len(hashes)}] Trying hash {h}...")
        if try_download_icon(h, output_dir):
            success += 1
        else:
            failed += 1

    print(f"\nDone: {success} downloaded, {failed} failed")
    print(f"Icons saved to: {output_dir.absolute()}")

    # Create manifest
    manifest = {
        "source": "wowhead_cdn",
        "total_icons": success,
        "icon_hashes": [h for h in hashes if (output_dir / f"{h}.webp").exists()]
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"Manifest saved to: {manifest_path}")


if __name__ == "__main__":
    main()
