"""
events.py
---------
Discord event handlers: message listening, natural conversation
context gathering, typing indicators, and connection lifecycle logging.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time

import discord
from discord.ext import commands

from config import CONTEXT_MESSAGE_COUNT
from games import maybe_award_treasure
from personality import build_prompt
from utils import split_message

logger = logging.getLogger("buggy.events")

# Simple per-channel cooldown so Buggy doesn't spam every message.
COOLDOWN_SECONDS = 4.0

# Rough word-count heuristic for occasionally jumping into ongoing chat
# even without a direct mention (kept conservative on purpose).
RANDOM_REPLY_CHANCE = 0.0  # disabled by default; mention/reply driven only

PRAISE_WORDS = ["awesome", "amazing", "great captain", "love you", "best pirate", "cool buggy"]
INSULT_WORDS = ["stupid", "lame", "worst pirate", "hate you", "annoying", "weak"]
DANGER_WORDS = ["admiral", "marine", "attack", "threat", "kill you", "danger", "run for"]
EXPOSED_WORDS = ["gotcha", "caught you", "you're lying", "busted", "exposed"]

# Only announce a passive treasure find part of the time, so it stays
# a rare surprise rather than a running commentary on every message.
TREASURE_ANNOUNCE_CHANCE = 0.6

# Explicit game-related terms that justify the extra cost/latency of a
# Google Search-grounded Gemini call. Deliberately NOT matching every
# character name by itself - "who's Luffy" is ambiguous (anime vs
# game), so we only ground when the message also smells like OPBR.
OPBR_KEYWORDS = [
    "opbr", "bounty rush", "banner", "gacha", "medal", "tier list",
    "meta", "current event", "pull rates", "pull for", "new character",
    "new unit", "best build", "who's good", "whos good", "s tier",
    "reroll", "recruit gauge", "rarity", "leader skill",
]


class BuggyEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_reply_at: dict[int, float] = {}

    # -- Connection lifecycle -------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(
            "Logged in as %s (id=%s) - present in %d guild(s)",
            self.bot.user,
            self.bot.user.id,
            len(self.bot.guilds),
        )
        logger.info("Gemini keys loaded: %d", self.bot.gemini_keys.total_keys)
        await self.bot.change_presence(
            activity=discord.Game(name="being the greatest pirate ever | !help")
        )

    @commands.Cog.listener()
    async def on_disconnect(self):
        logger.warning("Disconnected from Discord - will auto-reconnect")

    @commands.Cog.listener()
    async def on_resumed(self):
        logger.info("Connection to Discord resumed")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        logger.info("Joined guild: %s (id=%s)", guild.name, guild.id)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("You forgot something! Even I don't forget things this often.")
            return
        logger.error("Command error in #%s: %s", getattr(ctx.channel, "name", "DM"), error)
        await ctx.send("Something went wrong, but don't worry - it definitely wasn't my fault.")

    # -- Message handling -------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Never respond to other bots (including ourselves).
        if message.author.bot:
            return

        # Let the command framework handle prefix commands first.
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            await self.bot.process_commands(message)
            return

        # Background hooks that run on every ordinary chat message,
        # regardless of whether Buggy was addressed directly.
        handled_as_riddle = await self._handle_passive(message)
        if handled_as_riddle:
            return

        if not self._should_respond(message):
            return

        if not self._check_cooldown(message.channel.id):
            return

        await self._handle_conversation(message)

    async def _handle_passive(self, message: discord.Message) -> bool:
        """Ambient activity tracking, passive treasure discovery, and
        emoji-riddle answer checking. Returns True if the message was
        consumed as a riddle answer (caller should stop processing)."""
        if message.guild:
            try:
                await self.bot.memory.touch_ambient_activity(message.guild.id, message.channel.id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Ambient activity touch failed: %s", exc)

        games_cog = self.bot.get_cog("GamesCog")
        if games_cog and games_cog.check_riddle_answer(message.channel.id, message.content):
            try:
                await message.channel.send(
                    f"🧩 {message.author.mention} solved it! Buggy is impressed. Suspiciously impressed."
                )
                if message.guild:
                    await self.bot.memory.add_crew_points(message.author.id, message.guild.id, 3)
            except discord.HTTPException:
                pass
            return True

        guild_id = message.guild.id if message.guild else None
        try:
            treasure_line = await maybe_award_treasure(self.bot, message.author.id, guild_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Treasure roll failed: %s", exc)
            treasure_line = None

        if treasure_line and random.random() < TREASURE_ANNOUNCE_CHANCE:
            try:
                await message.channel.send(treasure_line)
            except discord.HTTPException:
                pass

        return False

    def _should_respond(self, message: discord.Message) -> bool:
        # Always respond in DMs.
        if isinstance(message.channel, discord.DMChannel):
            return True

        # Respond when directly mentioned.
        if self.bot.user in message.mentions:
            return True

        # Respond when replying to one of our own messages.
        if message.reference and message.reference.resolved:
            resolved = message.reference.resolved
            if isinstance(resolved, discord.Message) and resolved.author.id == self.bot.user.id:
                return True

        return False

    def _check_cooldown(self, channel_id: int) -> bool:
        now = time.monotonic()
        last = self._last_reply_at.get(channel_id, 0.0)
        if now - last < COOLDOWN_SECONDS:
            return False
        self._last_reply_at[channel_id] = now
        return True

    async def _handle_conversation(self, message: discord.Message):
        channel = message.channel
        guild_name = message.guild.name if message.guild else "Direct Message"
        channel_name = getattr(channel, "name", "dm")

        clean_content = self._strip_mentions(message)
        signals = self._compute_signals(clean_content)

        # Remember the user and log basic facts before generating.
        await self.bot.memory.touch_user(message.author.id, str(message.author))
        await self._extract_and_store_signals(message.author.id, message.guild, clean_content, signals)

        try:
            async with channel.typing():
                history_lines = await self._gather_history(channel, message)
                user_memory = await self.bot.memory.get_user_context(message.author.id)
                channel_summary = await self.bot.memory.get_channel_summary_context(channel.id)

                prompt = build_prompt(
                    server_name=guild_name,
                    channel_name=channel_name,
                    recent_messages=history_lines,
                    triggering_user=message.author.display_name,
                    triggering_message=clean_content,
                    user_memory=user_memory,
                    channel_summary=channel_summary,
                )

                use_search = self._is_opbr_query(clean_content)
                reply = await self.bot.gemini.generate(prompt, use_search=use_search)

            for chunk in split_message(reply):
                await message.channel.send(chunk)

            gif = self.bot.emotions.decide_gif(channel.id, reply, signals=signals)
            if gif:
                try:
                    await message.channel.send(gif.url)
                except discord.HTTPException:
                    pass

            # Periodically compress history into a summary to keep
            # long-term memory bounded (roughly every 20 messages).
            if len(history_lines) >= CONTEXT_MESSAGE_COUNT:
                transcript = "\n".join(history_lines)
                summary = await self.bot.gemini.summarize(transcript)
                await self.bot.memory.save_channel_summary(
                    message.guild.id if message.guild else None, channel.id, summary
                )

        except discord.Forbidden:
            logger.warning("Missing permissions to respond in #%s", channel_name)
        except discord.HTTPException as exc:
            logger.error("Discord HTTP error while responding: %s", exc)
        except Exception as exc:  # noqa: BLE001 - never crash the listener
            logger.error("Unexpected error handling message: %s", exc, exc_info=True)

    async def _gather_history(
        self, channel: discord.abc.Messageable, current: discord.Message
    ) -> list[str]:
        lines: list[str] = []
        try:
            async for msg in channel.history(limit=CONTEXT_MESSAGE_COUNT, before=current):
                if not msg.content:
                    continue
                lines.append(f"{msg.author.display_name}: {msg.content}")
        except discord.Forbidden:
            logger.warning("Cannot read history in this channel - proceeding without it")
        lines.reverse()
        return lines

    @staticmethod
    def _strip_mentions(message: discord.Message) -> str:
        content = message.content
        content = re.sub(r"<@!?\d+>", "", content).strip()
        return content or "(no text - just pinged Buggy)"

    def _is_opbr_query(self, content: str) -> bool:
        """Whether this message looks like a One Piece Bounty Rush
        (game) question worth grounding with live Google Search, vs
        ordinary in-character chat. Deliberately keyword-only - no
        dependency on the OPBR medal dataset here."""
        lowered = content.lower()
        return any(keyword in lowered for keyword in OPBR_KEYWORDS)

    def _compute_signals(self, content: str) -> dict:
        lowered = content.lower()
        return {
            "praised": any(w in lowered for w in PRAISE_WORDS),
            "insulted": any(w in lowered for w in INSULT_WORDS),
            "danger_mentioned": any(w in lowered for w in DANGER_WORDS),
            "shanks_mentioned": "shanks" in lowered,
            "exposed": any(w in lowered for w in EXPOSED_WORDS),
        }

    async def _extract_and_store_signals(
        self, user_id: int, guild: discord.Guild | None, content: str, signals: dict
    ) -> None:
        """Very lightweight heuristic memory extraction - looks for
        obvious praise/insults to store as facts and nudge reputation.
        Real nuance is left to Gemini; this just seeds a few durable
        memory hooks."""
        guild_id = guild.id if guild else None

        if signals.get("praised"):
            asyncio.create_task(
                self.bot.memory.remember_compliment(user_id, guild_id, content[:200])
            )
            asyncio.create_task(self.bot.memory.adjust_reputation(user_id, 1))
        elif signals.get("insulted"):
            asyncio.create_task(
                self.bot.memory.remember_insult(user_id, guild_id, content[:200])
            )
            asyncio.create_task(self.bot.memory.adjust_reputation(user_id, -1))


async def setup_events(bot) -> None:
    await bot.add_cog(BuggyEvents(bot))
