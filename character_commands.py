"""
character_commands.py
---------------------
Commands for displaying character data from opbrhelper.com.
Uses the scraped opbr_characters.json and portrait URLs.
If portrait URL is missing, fetches it on the fly and updates the JSON.
Autocomplete shows: "Name (Subtitle)".
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
import requests
from urllib.parse import urljoin

logger = logging.getLogger("buggy.character_commands")

DATA_PATH = Path(__file__).parent / "opbr_characters.json"
EMBED_COLOR = 0xCC9D50
BASE_URL = "https://opbrhelper.com"


class CharacterCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.characters = []
        self._character_options = []  # list of (display_name, value_name)
        self._load_data()

    def _load_data(self):
        if not DATA_PATH.exists():
            logger.warning("opbr_characters.json not found, character commands disabled.")
            return
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                self.characters = json.load(f)
            # Build autocomplete options: "Name (Subtitle)" -> value = name
            self._character_options = []
            for c in self.characters:
                name = c["name"]
                subtitle = c.get("subtitle", "")
                display = f"{name} ({subtitle})" if subtitle else name
                self._character_options.append((display, name))
            logger.info(f"Loaded {len(self.characters)} characters from opbr_characters.json")
        except Exception as e:
            logger.error(f"Failed to load character data: {e}")
            self.characters = []

    def _save_data(self):
        try:
            with open(DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(self.characters, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save character data: {e}")

    def _extract_portrait_url(self, page_url: str) -> str | None:
        """Scrape the portrait URL from a character's detail page."""
        try:
            resp = requests.get(page_url, timeout=10)
            resp.raise_for_status()
            html = resp.text

            # Look for <link rel="preload" as="image" imagesrcset="...">
            match = re.search(
                r'<link rel="preload" as="image"[^>]*imagesrcset="([^"]*)"',
                html,
                re.IGNORECASE
            )
            if match:
                srcset = match.group(1)
                entries = [e.strip() for e in srcset.split(',') if e.strip()]
                if entries:
                    last_entry = entries[-1]
                    parts = last_entry.split()
                    if parts:
                        img_url = parts[0].replace('&amp;', '&')
                        if img_url.startswith('/'):
                            img_url = urljoin(BASE_URL, img_url)
                        return img_url

            # Fallback: og:image
            og_match = re.search(r'<meta property="og:image" content="([^"]*)"', html)
            if og_match:
                img_url = og_match.group(1)
                if img_url.startswith('/'):
                    img_url = urljoin(BASE_URL, img_url)
                return img_url

            return None
        except Exception as e:
            logger.error(f"Failed to fetch portrait for {page_url}: {e}")
            return None

    async def character_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            if not self._character_options:
                return []
            current_lower = current.lower().strip()
            matches = []
            for display, value in self._character_options:
                if not current_lower or current_lower in display.lower() or current_lower in value.lower():
                    matches.append((display, value))
                    if len(matches) >= 25:
                        break
            return [app_commands.Choice(name=display, value=value) for display, value in matches]
        except Exception as e:
            logger.error(f"Character autocomplete error: {e}", exc_info=True)
            return []

    @app_commands.command(
        name="character",
        description="Show detailed info for an OPBR character."
    )
    @app_commands.describe(name="Character name (autocomplete)")
    @app_commands.autocomplete(name=character_autocomplete)
    async def character(self, interaction: discord.Interaction, name: str):
        try:
            await interaction.response.defer()

            if not self.characters:
                await interaction.followup.send(
                    "Character database not loaded. Please run the scrape script first.",
                    ephemeral=True
                )
                return

            # Find the character
            char = None
            for c in self.characters:
                if c["name"].lower() == name.lower():
                    char = c
                    break
            if not char:
                await interaction.followup.send(
                    f"❌ Character **{name}** not found in the database.",
                    ephemeral=True
                )
                return

            # If portrait_url is missing, try to fetch it now
            if not char.get("portrait_url"):
                logger.info(f"Portrait URL missing for {char['name']}, fetching now...")
                page_url = char.get("page_url")
                if page_url:
                    portrait_url = await asyncio.to_thread(self._extract_portrait_url, page_url)
                    if portrait_url:
                        char["portrait_url"] = portrait_url
                        self._save_data()
                        logger.info(f"Added portrait URL for {char['name']}")
                    else:
                        logger.warning(f"Could not fetch portrait for {char['name']}")

            # Build embed
            embed = discord.Embed(
                title=f"{char['name']}",
                description=char.get("subtitle", ""),
                color=EMBED_COLOR,
            )

            # Add fields
            if char.get("rarity"):
                embed.add_field(name="Rarity", value=char["rarity"], inline=True)
            if char.get("stars"):
                embed.add_field(name="Stars", value=char["stars"], inline=True)
            if char.get("color"):
                embed.add_field(name="Color", value=char["color"], inline=True)
            if char.get("class"):
                embed.add_field(name="Class", value=char["class"], inline=True)
            if char.get("tags"):
                embed.add_field(name="Tags", value=", ".join(char["tags"]), inline=False)

            # Use portrait URL if available
            portrait_url = char.get("portrait_url")
            if portrait_url:
                embed.set_image(url=portrait_url)
            else:
                embed.set_footer(text="Portrait not available. Run the portrait scraper to fetch images.")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Character command error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred while fetching character data.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "An error occurred while fetching character data.",
                    ephemeral=True
                )


async def setup_character(bot):
    await bot.add_cog(CharacterCommands(bot))
