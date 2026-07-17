#!/usr/bin/env python3
"""
test_icons.py
-------------
Standalone script to test medal icon URLs from the OPBR dataset.
Run this to see if the icons are reachable and what URL pattern works.
"""

import json
import sys
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

DATA_PATH = Path(__file__).resolve().parent / "data" / "opbr_data.json"

# Try both .webp and .png – we'll test which one works.
ICON_BASE = "https://ace-kyle.github.io/OPBR-medal-set-builder/img/medals/"
EXTENSIONS = [".webp", ".png"]

def test_url(url):
    try:
        with urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except (URLError, Exception):
        return False

def main():
    if not DATA_PATH.exists():
        print(f"❌ Data file not found at {DATA_PATH}")
        return

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    medals = data.get("medals", [])
    if not medals:
        print("❌ No medals found in dataset")
        return

    print(f"✅ Loaded {len(medals)} medals. Testing first 5...\n")

    for medal in medals[:5]:
        medal_id = medal.get("medal_id")
        name = medal.get("name", "Unknown")
        icon_name = medal.get("icon_name")
        if not icon_name:
            icon_name = f"img_icon_medal_{medal_id}"

        print(f"Medal: {name}")
        print(f"  icon_name: {icon_name}")
        for ext in EXTENSIONS:
            url = f"{ICON_BASE}{icon_name}{ext}"
            ok = test_url(url)
            status = "✅ REACHABLE" if ok else "❌ NOT FOUND"
            print(f"  {ext}: {url} -> {status}")
        print()

    print("\nRecommendation:")
    print("  - If .webp works, keep ICON_EXT = '.webp' in opbr.py")
    print("  - If .png works, change ICON_EXT = '.png'")
    print("  - You can also set environment variable OPBR_ICON_BASE_URL to a different base URL.")

if __name__ == "__main__":
    main()
