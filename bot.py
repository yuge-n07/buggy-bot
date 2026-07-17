"""
bot.py
------
Defines the BuggyBot class - a discord.py Bot subclass that wires
together the database, memory manager, Gemini service, commands, and
event listeners.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from ambient import setup_ambient
from channel_log import setup_channel_log
from character_commands import setup_character
from commands import setup_commands
from config import RuntimeSecrets
from database import Database
from emotions import EmotionManager
from events import setup_events
from games import setup_games
from gemini import GeminiService
from memory import MemoryManager
from opbr_commands import setup_opbr
from rotation import GeminiKeyManager

logger = logging.getLogger("buggy.bot")


class BuggyBot(commands.Bot):
    def __init__(self, secrets: RuntimeSecrets, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,  # we provide our own !help
            **kwargs,
        )

        self.secrets = secrets
        self.owner_id = secrets.owner_id
        self.test_guild_id = secrets.test_guild_id

        self.db = Database()
        self.memory = MemoryManager(self.db)
        self.gemini_keys = GeminiKeyManager(secrets.gemini_keys)
        self.gemini = GeminiService(self.gemini_keys)
        self.emotions = EmotionManager()

    async def on_message(self, message: discord.Message) -> None:
        # Intentionally a no-op override. commands.Bot's default
        # on_message calls process_commands() automatically, which
        # would double-fire alongside BuggyEvents' on_message listener
        # (Cog listeners are always additive, not replacements). All
        # message handling - including process_commands() - happens
        # inside events.BuggyEvents.on_message instead.
        pass

    async def setup_hook(self) -> None:
        await self.db.connect()
        await setup_commands(self)
        await setup_events(self)
        await setup_ambient(self)
        await setup_games(self)
        await setup_opbr(self)
        await setup_channel_log(self)
        await setup_character(self)   # <-- new line

        # Sync slash commands (games). If a test guild was provided at
        # startup, sync there too for instant propagation while testing -
        # global syncs can take up to an hour to show up everywhere.
        try:
            if self.test_guild_id:
                guild_obj = discord.Object(id=self.test_guild_id)
                self.tree.copy_global_to(guild=guild_obj)
                await self.tree.sync(guild=guild_obj)
                logger.info("Slash commands synced to test guild %d", self.test_guild_id)
            await self.tree.sync()
            logger.info("Slash commands synced globally")
        except discord.HTTPException as exc:
            logger.warning("Slash command sync failed: %s", exc)

        logger.info("Setup complete - Buggy is ready to make his entrance")

    async def close(self) -> None:
        logger.info("Shutting down gracefully...")
        try:
            await self.db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error closing database: %s", exc)
        await super().close()
