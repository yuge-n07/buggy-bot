"""
commands.py
-----------
All prefix commands ("!command") for Buggy D. GOAT.
"""

from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from utils import split_message

logger = logging.getLogger("buggy.commands")


def _is_owner(bot: "BuggyBot", user_id: int) -> bool:
    return user_id == bot.owner_id


class BuggyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    # -- General commands ------------------------------------------------

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(
            f"PAH HA HA! Buggy is FASTER than your reflexes! `{latency_ms}ms` "
            f"and I didn't even break a sweat! 🤡"
        )

    @commands.command(name="help")
    async def help_cmd(self, ctx: commands.Context):
        text = (
            "**🤡 BUGGY D. GOAT - COMMAND LIST (as decreed by the future Pirate King) 🤡**\n"
            "`!ping` - test if I'm still gloriously alive\n"
            "`!about` - learn about my GREATNESS\n"
            "`!buggy` - a random dose of Buggy wisdom\n"
            "`!stats` - my totally legitimate stats\n"
            "`!persona` - reminder of who's talking to you (me, obviously)\n"
            "`!context` - see what I've been paying attention to\n"
            "`!memory` - what I remember about you\n"
            "`!resetmemory` - wipe my memory of you (rude, but fine)\n"
            "`!forget` - alias for resetmemory\n"
            "`!clearhistory` - clear this channel's conversation memory (owner only)\n"
            "`!reload` - reload my systems (owner only)\n"
            "`!ambient` - toggle my random entrances/idle chatter in this channel (Manage Server)\n"
            "Or just @ mention me or reply to my messages - I'm always listening "
            "for admiration!\n\n"
            "**🎮 Slash Commands (games):**\n"
            "`/coinflip` `/diceduel` `/duel` `/rps` `/trivia` `/guess start` `/guess number` "
            "`/emojiguess` `/joincrew` `/crew` `/treasure`"
        )
        await ctx.send(text)

    @commands.command(name="about")
    async def about(self, ctx: commands.Context):
        await ctx.send(
            "I am BUGGY D. GOAT - the GREATEST pirate to ever sail the seas, "
            "future Pirate King, master of the Bara Bara no Mi, and TOTALLY "
            "not afraid of anything! I run on pure charisma and questionable "
            "life choices. 🃏⚔️"
        )

    @commands.command(name="buggy")
    async def buggy_wisdom(self, ctx: commands.Context):
        import random

        lines = [
            "Remember: if it goes wrong, it was ALWAYS part of the plan!",
            "The secret to leadership? Volume. Just be LOUD about it!",
            "I once scared off a Sea King just by introducing myself. Probably.",
            "You know who's stronger than me? NOBODY. Next question.",
            "A true captain never runs away. He 'tactically repositions.'",
        ]
        await ctx.send(f"🤡 {random.choice(lines)}")

    @commands.command(name="stats")
    async def stats(self, ctx: commands.Context):
        uptime = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)
        db_stats = await self.bot.memory.stats()
        key_status = self.bot.gemini_keys.status_summary()
        await ctx.send(
            "**🤡 Buggy's Totally Legitimate Stats 🤡**\n"
            f"Uptime: `{hours}h {minutes}m {seconds}s` (I never sleep, I'm too great)\n"
            f"Servers I grace with my presence: `{len(self.bot.guilds)}`\n"
            f"Remembered subjects: `{db_stats['users']}`\n"
            f"Facts hoarded: `{db_stats['facts']}`\n"
            f"Gemini key status: `{key_status}`"
        )

    @commands.command(name="persona")
    async def persona(self, ctx: commands.Context):
        await ctx.send(
            "There is no 'persona.' There is only BUGGY. I don't wear a mask - "
            "I AM the show. 🎪"
        )

    @commands.command(name="context")
    async def context_cmd(self, ctx: commands.Context):
        summary = await self.bot.memory.get_channel_summary_context(ctx.channel.id)
        if not summary:
            await ctx.send("I haven't summarized anything here yet. Keep talking!")
        else:
            for chunk in split_message(summary):
                await ctx.send(chunk)

    @commands.command(name="memory")
    async def memory_cmd(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        blurb = await self.bot.memory.get_user_context(target.id)
        for chunk in split_message(f"**What I remember about {target.display_name}:**\n{blurb}"):
            await ctx.send(chunk)

    @commands.command(name="resetmemory", aliases=["forget"])
    async def resetmemory(self, ctx: commands.Context):
        await self.bot.memory.reset_user(ctx.author.id)
        await ctx.send(
            f"Ugh, FINE, {ctx.author.display_name}. Buggy's memory of you is "
            f"WIPED. We're starting over. Try not to disappoint me this time. 🤡"
        )

    # -- Owner-only commands ------------------------------------------------

    @commands.command(name="clearhistory")
    async def clearhistory(self, ctx: commands.Context):
        if not _is_owner(self.bot, ctx.author.id):
            await ctx.send("Pfft, only MY owner gets to boss me around. Nice try.")
            return
        await self.bot.memory.clear_channel(ctx.channel.id)
        await ctx.send("This channel's conversation memory has been wiped clean. 🧹")

    @commands.command(name="reload")
    async def reload(self, ctx: commands.Context):
        if not _is_owner(self.bot, ctx.author.id):
            await ctx.send("Pfft, only MY owner gets to boss me around. Nice try.")
            return
        await ctx.send("Reloading systems... *dramatic clown music* ...done! Still amazing. 🎪")
        logger.info("Reload command triggered by owner")


async def setup_commands(bot) -> None:
    await bot.add_cog(BuggyCommands(bot))
