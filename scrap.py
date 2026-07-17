#!/usr/bin/env python3
"""
Scrape character data from https://opbrhelper.com/characters
Extracts: name, subtitle, rarity, stars, color, class, tags, image URL, and page link.
"""

import re
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urljoin

BASE_URL = "https://opbrhelper.com"
CHARACTERS_URL = urljoin(BASE_URL, "/characters")

# Known rarity keywords
RARITY_KEYWORDS = ["Extreme", "Bounty Festival", "Step-Up", "Free 3 Stars", "Event"]


def scrape_characters():
    print(f"Fetching {CHARACTERS_URL}...")
    resp = requests.get(CHARACTERS_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    characters = []
    # Each character card is an <a> tag with class containing "rounded-3xl"
    cards = soup.find_all("a", class_=re.compile(r"rounded-3xl"))

    for card in cards:
        href = card.get("href")
        if not href or not href.startswith("/characters/"):
            continue

        # Name
        name_tag = card.find("h2")
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)

        # Subtitle (e.g., "Winner Island", "The Five Elders")
        subtitle_tag = card.find("p", class_="text-sm")
        subtitle = subtitle_tag.get_text(strip=True) if subtitle_tag else ""

        # Rarity badge – find span with text matching known rarities
        rarity = ""
        rarity_spans = card.find_all("span", class_="rounded-full")
        for span in rarity_spans:
            text = span.get_text(strip=True)
            if any(kw in text for kw in RARITY_KEYWORDS):
                rarity = text
                break

        # Stars, Color, Class from the flex-wrap divs
        stars = ""
        color = ""
        char_class = ""
        tags = []
        meta_spans = card.find_all("span", class_="rounded-full")
        for span in meta_spans:
            text = span.get_text(strip=True)
            if "★" in text:
                stars = text
            elif text in ["Red", "Blue", "Green", "Dark", "Light"]:
                color = text
            elif text in ["Attacker", "Defender", "Runner"]:
                char_class = text
            elif span.get("class") and "bg-slate-800" in span.get("class", []):
                tags.append(text)

        # Image URL (badge image, not portrait)
        img_tag = card.find("img")
        img_url = ""
        if img_tag:
            src = img_tag.get("src") or img_tag.get("srcset", "").split()[0]
            if src:
                img_url = urljoin(BASE_URL, src)

        char_data = {
            "name": name,
            "subtitle": subtitle,
            "rarity": rarity,
            "stars": stars,
            "color": color,
            "class": char_class,
            "tags": tags,
            "image_url": img_url,
            "page_url": urljoin(BASE_URL, href),
            "portrait_url": None,  # will be filled later
        }
        characters.append(char_data)
        print(f"✓ {name} ({subtitle}) - {rarity}")

    return characters


def save_json(characters, filename="opbr_characters.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(characters, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(characters)} characters to {filename}")


if __name__ == "__main__":
    print("Scraping OPBR Helper characters...")
    chars = scrape_characters()
    print(f"\nFound {len(chars)} characters.\n")
    save_json(chars)
