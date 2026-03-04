#!/usr/bin/env python3
"""
Aggressively fetch D4 item icons from Wowhead's CDN.
Tries all category values from 50-300 to find valid icons.
"""

import sys
import json
import re
import concurrent.futures
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import time

CDN_BASE = "https://wow.zamimg.com/d4/d4/texture/hash"

# Wide range of categories based on testing
CATEGORIES = list(range(50, 301, 5))


def fetch_icons_from_wowhead():
    """Fetch all icon hashes from multiple Wowhead pages."""
    all_icons = {}

    urls = [
        "https://www.wowhead.com/diablo-4/items/quality:6",  # Unique
        "https://www.wowhead.com/diablo-4/items/quality:5",  # Legendary
    ]

    for url in urls:
        print(f"Fetching from {url}...")
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=30) as response:
                html = response.read().decode("utf-8")

            # Extract icon and name pairs
            items = re.findall(r'"icon":(\d+)[^}]*"name":"([^"]+)"', html)
            for icon, name in items:
                all_icons[int(icon)] = name

        except Exception as e:
            print(f"  Error: {e}")

    print(f"Found {len(all_icons)} unique icons")
    return all_icons


def try_download(args):
    """Try to download an icon with a specific category."""
    icon_hash, cat = args
    url = f"{CDN_BASE}/{cat}/{icon_hash}.webp"

    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=5) as response:
            data = response.read()
            if len(data) > 500 and not data.startswith(b"<html"):
                return (icon_hash, cat, data)
    except:
        pass
    return None


def download_icon(icon_hash: int, output_dir: Path) -> tuple[bool, int]:
    """Download an icon by trying all categories in parallel."""

    # Try categories in parallel
    args_list = [(icon_hash, cat) for cat in CATEGORIES]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(try_download, args) for args in args_list]

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                icon_hash, cat, data = result
                output_path = output_dir / f"{icon_hash}.webp"
                output_path.write_bytes(data)
                return (True, cat)

    return (False, 0)


def main():
    output_dir = Path("sample-data/icons")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get icons
    icons = fetch_icons_from_wowhead()

    # Limit count
    max_icons = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    icon_list = list(icons.items())[:max_icons]

    print(f"\nDownloading up to {len(icon_list)} icons...")

    success_list = []
    failed_list = []

    for i, (icon_hash, name) in enumerate(icon_list, 1):
        # Skip if already downloaded
        if (output_dir / f"{icon_hash}.webp").exists():
            print(f"[{i}/{len(icon_list)}] Skip {name} (already exists)")
            success_list.append((icon_hash, name, -1))
            continue

        print(f"[{i}/{len(icon_list)}] {name}...", end=" ", flush=True)

        ok, cat = download_icon(icon_hash, output_dir)
        if ok:
            print(f"OK (cat {cat})")
            success_list.append((icon_hash, name, cat))
        else:
            print("FAIL")
            failed_list.append((icon_hash, name))

        # Small delay to be nice
        time.sleep(0.1)

    print(f"\n{'='*50}")
    print(f"Downloaded: {len(success_list)}")
    print(f"Failed: {len(failed_list)}")
    print(f"Output: {output_dir.absolute()}")

    # Save manifest
    manifest = {
        "source": "wowhead_cdn",
        "downloaded": len(success_list),
        "failed": len(failed_list),
        "icons": [
            {"hash": h, "name": n, "category": c}
            for h, n, c in success_list if c != -1
        ],
        "failed_icons": [
            {"hash": h, "name": n}
            for h, n in failed_list
        ]
    }

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Manifest saved")


if __name__ == "__main__":
    main()
