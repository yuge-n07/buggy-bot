"""
ambient.py
----------
Makes Buggy feel alive even when nobody is talking to him directly:
rare random "entrances" and idle daily-activity flavor lines, posted
only in channels an admin has opted in via !ambient.

Deliberately does NOT call Gemini for these - they're simple canned
lines rotated for variety, keeping this feature cheap and reliable.
"""

from __future__ import annotations

import logging
import random
import time

import discord
from discord.ext import commands, tasks

logger = logging.getLogger("buggy.ambient")

TICK_MINUTES = 15

# Rough target: entrances roughly once every several hours per active
# channel. With a 15-minute tick, ~1/16 chance per tick averages to
# about once every 4 hours when conditions are met.
ENTRANCE_CHANCE_PER_TICK = 0.06
ENTRANCE_MIN_GAP_SECONDS = 3 * 60 * 60       # don't re-trigger within 3h
ENTRANCE_REQUIRES_ACTIVITY_WITHIN = 2 * 60 * 60  # channel must be "alive"
ENTRANCE_QUIET_WINDOW = 90  # skip if a message landed in the last 90s

ACTIVITY_CHANCE_PER_TICK = 0.08
ACTIVITY_MIN_GAP_SECONDS = 2 * 60 * 60
ACTIVITY_REQUIRES_ACTIVITY_WITHIN = 6 * 60 * 60
ACTIVITY_QUIET_WINDOW = 90

ENTRANCE_LINES = [
    "I RETURNED!! Did you all miss the greatest pirate alive?!",
    "WHO STOLE MY TREASURE?! I know it was one of you!",
    "I leave for FIVE MINUTES and this server is STILL not worshipping me enough!",
    "*bursts through the door* Miss me? Of course you did.",
    "Buggy the Clown has arrived! No need to applaud. Okay, a little applause.",
    "Did someone say my name? No? Well, you SHOULD have.",
]

DAILY_ACTIVITY_LINES = [
    "Ugh, I'm STARVING. Being this legendary burns a lot of calories.",
    "You won't BELIEVE what I found. Okay fine, it's probably not treasure. Probably.",
    "So there I was, single-handedly holding off an Admiral, and-- wait, where'd everyone go?",
    "I deserve WAY more respect around here. Just saying.",
    "Recruiting new pirates! Requirements: unconditional loyalty and admiration for me.",
    "My crew is USELESS today. Absolutely useless. Not naming names. It's everyone.",
    "Just won a fight against a Sea King. It fled in terror. Definitely happened.",
]


class AmbientCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ambient_tick.start()

    def cog_unload(self):
        self.ambient_tick.cancel()

    # -- Configuration command --------------------------------------------

    @commands.command(name="ambient")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def ambient_toggle(self, ctx: commands.Context):
        """Toggles ambient behavior (random entrances, daily activity
        lines) for the current channel. Requires Manage Server."""
        guild_id = ctx.guild.id
        channel_id = ctx.channel.id

        channels = await self.bot.memory.ambient_channels()
        already_on = any(
            c["guild_id"] == guild_id and c["channel_id"] == channel_id for c in channels
        )

        if already_on:
            await self.bot.memory.disable_ambient(guild_id, channel_id)
            await ctx.send("Fine, fine, I'll stop randomly showing up here. Ungrateful. 🤡")
        else:
            await self.bot.memory.enable_ambient(guild_id, channel_id)
            await ctx.send(
                "Ooooh, this channel gets the HONOR of my spontaneous appearances now. "
                "You're welcome. 🎪"
            )

    @ambient_toggle.error
    async def ambient_toggle_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Only server managers get to decide where I grace with my presence!")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("Can't do that in a DM - pick a real server channel.")

    # -- Background loop ----------------------------------------------------

    @tasks.loop(minutes=TICK_MINUTES)
    async def ambient_tick(self):
        try:
            channels = await self.bot.memory.ambient_channels()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load ambient channels: %s", exc)
            return

        now = time.time()
        for row in channels:
            guild_id, channel_id = row["guild_id"], row["channel_id"]
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue

            last_activity = row["last_activity_at"] or 0
            last_entrance = row["last_entrance_at"] or 0
            last_activity_post = row["last_activity_post_at"] or 0

            channel_is_alive = (now - last_activity) <= ENTRANCE_REQUIRES_ACTIVITY_WITHIN
            not_too_recent = (now - last_activity) >= ENTRANCE_QUIET_WINDOW
            entrance_cooldown_clear = (now - last_entrance) >= ENTRANCE_MIN_GAP_SECONDS

            if (
                channel_is_alive
                and not_too_recent
                and entrance_cooldown_clear
                and random.random() < ENTRANCE_CHANCE_PER_TICK
            ):
                try:
                    await channel.send(random.choice(ENTRANCE_LINES))
                    await self.bot.memory.mark_ambient_entrance(guild_id, channel_id)
                    logger.info("Posted a random entrance in channel %d", channel_id)
                    continue  # don't also post a daily-activity line this tick
                except discord.HTTPException as exc:
                    logger.warning("Failed to post ambient entrance: %s", exc)

            activity_channel_alive = (now - last_activity) <= ACTIVITY_REQUIRES_ACTIVITY_WITHIN
            activity_not_too_recent = (now - last_activity) >= ACTIVITY_QUIET_WINDOW
            activity_cooldown_clear = (now - last_activity_post) >= ACTIVITY_MIN_GAP_SECONDS

            if (
                activity_channel_alive
                and activity_not_too_recent
                and activity_cooldown_clear
                and random.random() < ACTIVITY_CHANCE_PER_TICK
            ):
                try:
                    await channel.send(random.choice(DAILY_ACTIVITY_LINES))
                    await self.bot.memory.mark_ambient_activity_post(guild_id, channel_id)
                    logger.info("Posted a daily-activity line in channel %d", channel_id)
                except discord.HTTPException as exc:
                    logger.warning("Failed to post ambient activity line: %s", exc)

    @ambient_tick.before_loop
    async def before_ambient_tick(self):
        await self.bot.wait_until_ready()


async def setup_ambient(bot) -> None:
    await bot.add_cog(AmbientCog(bot))
