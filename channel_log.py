"""
channel_log.py
---------------
/log - exports a channel's message history to a plain-text file the
requester can download. Permission-gated (Manage Messages) since a
full channel export can contain content people didn't expect to be
bundled up, and capped in size so it can't be used to accidentally
DoS the bot or produce an unmanageable file on a big channel.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("buggy.channel_log")

DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000


class ChannelLogCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="log", description="Export this channel's recent message history as a text file.")
    @app_commands.describe(limit=f"How many messages to fetch (default {DEFAULT_LIMIT}, max {MAX_LIMIT})")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def log(self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, MAX_LIMIT] = DEFAULT_LIMIT):
        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel
        lines: list[str] = [
            f"Channel log for #{getattr(channel, 'name', channel.id)} "
            f"(guild: {interaction.guild.name if interaction.guild else 'DM'})",
            f"Exported: {datetime.now(timezone.utc).isoformat()}",
            f"Requested by: {interaction.user} | Message limit: {limit}",
            "=" * 60,
            "",
        ]

        count = 0
        try:
            async for message in channel.history(limit=limit, oldest_first=True):
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
                content = message.content or "*(no text content - embed/attachment/system message)*"
                lines.append(f"[{timestamp}] {message.author}: {content}")
                if message.attachments:
                    for att in message.attachments:
                        lines.append(f"    [attachment] {att.filename}: {att.url}")
                count += 1
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to read this channel's history.", ephemeral=True
            )
            return
        except discord.HTTPException as exc:
            logger.error("Failed to fetch channel history: %s", exc)
            await interaction.followup.send(
                "Something went wrong pulling the channel history - try a smaller limit.",
                ephemeral=True,
            )
            return

        lines.append("")
        lines.append(f"-- End of log ({count} messages) --")

        buffer = io.BytesIO("\n".join(lines).encode("utf-8"))
        channel_label = getattr(channel, "name", str(channel.id))
        filename = f"log-{channel_label}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.txt"

        await interaction.followup.send(
            content=f"📜 Logged {count} messages from this channel.",
            file=discord.File(buffer, filename=filename),
            ephemeral=True,
        )

    @log.error
    async def log_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "You need Manage Messages permission to export the channel log.", ephemeral=True
            )
        elif isinstance(error, app_commands.NoPrivateMessage):
            await interaction.response.send_message(
                "Channel logging only works in an actual server channel.", ephemeral=True
            )
        else:
            logger.error("Unexpected /log error: %s", error)
            if not interaction.response.is_done():
                await interaction.response.send_message("Something went wrong running that.", ephemeral=True)


async def setup_channel_log(bot) -> None:
    await bot.add_cog(ChannelLogCog(bot))
