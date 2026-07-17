"""
memory.py
---------
Higher-level memory API used by the AI prompt builder and commands.
Wraps database.py so the rest of the bot never writes raw SQL.
"""

from __future__ import annotations

import logging

from database import Database, rank_for_points

logger = logging.getLogger("buggy.memory")

REPUTATION_TIERS = [
    (-999, "Buggy considers them an outright traitor and blames them for everything."),
    (-3, "Buggy is suspicious of them and doesn't fully trust them."),
    (0, "Buggy is neutral toward them - just another crew member for now."),
    (6, "Buggy genuinely likes them and enjoys their company."),
    (15, "Buggy trusts them completely and treats them like a valued crewmate."),
]


def reputation_description(score: int) -> str:
    description = REPUTATION_TIERS[0][1]
    for threshold, text in REPUTATION_TIERS:
        if score >= threshold:
            description = text
    return description


class MemoryManager:
    def __init__(self, db: Database):
        self.db = db

    async def touch_user(self, user_id: int, username: str) -> None:
        await self.db.upsert_user(user_id, username)

    async def remember_compliment(self, user_id: int, guild_id: int | None, text: str) -> None:
        await self.db.add_fact(user_id, guild_id, "compliment", text)

    async def remember_insult(self, user_id: int, guild_id: int | None, text: str) -> None:
        await self.db.add_fact(user_id, guild_id, "insult", text)

    async def remember_fact(self, user_id: int, guild_id: int | None, text: str) -> None:
        await self.db.add_fact(user_id, guild_id, "fact", text)

    async def remember_joke(self, user_id: int, guild_id: int | None, text: str) -> None:
        await self.db.add_fact(user_id, guild_id, "joke", text)

    async def set_nickname(self, user_id: int, nickname: str) -> None:
        await self.db.set_nickname(user_id, nickname)

    async def set_relationship(self, user_id: int, relationship: str) -> None:
        await self.db.set_relationship(user_id, relationship)

    async def adjust_reputation(self, user_id: int, delta: int) -> int:
        return await self.db.adjust_reputation(user_id, delta)

    async def get_user_context(self, user_id: int) -> str:
        """Builds a short natural-language memory blurb for a user,
        to be injected into the Gemini prompt."""
        user = await self.db.get_user(user_id)
        facts = await self.db.get_facts(user_id, limit=8)

        if not user:
            return "Buggy has no memory of this person yet - they're a stranger."

        lines = []
        nickname = user["nickname"]
        relationship = user["relationship"]
        reputation = user["reputation"] if "reputation" in user.keys() else 0
        lines.append(
            f"Buggy calls this user '{nickname}'." if nickname else "Buggy hasn't given this user a nickname yet."
        )
        lines.append(f"Buggy's current relationship with them: {relationship}.")
        lines.append(reputation_description(reputation))

        if facts:
            fact_lines = [f"- ({f['fact_type']}) {f['content']}" for f in facts]
            lines.append("Things Buggy remembers about them:\n" + "\n".join(fact_lines))
        else:
            lines.append("Buggy doesn't remember anything specific about them yet.")

        return "\n".join(lines)

    async def get_channel_summary_context(self, channel_id: int) -> str:
        summaries = await self.db.get_recent_summaries(channel_id, limit=3)
        if not summaries:
            return ""
        lines = [f"- {s['summary']}" for s in reversed(summaries)]
        return "Recent conversation summaries in this channel:\n" + "\n".join(lines)

    async def save_channel_summary(
        self, guild_id: int | None, channel_id: int, summary: str
    ) -> None:
        await self.db.add_summary(guild_id, channel_id, summary)

    async def reset_user(self, user_id: int) -> None:
        await self.db.reset_user(user_id)

    async def clear_channel(self, channel_id: int) -> None:
        await self.db.clear_channel_history(channel_id)

    async def stats(self) -> dict:
        return await self.db.get_stats()

    # -- Crew -----------------------------------------------------------

    async def join_crew(self, user_id: int, guild_id: int) -> bool:
        return await self.db.join_crew(user_id, guild_id)

    async def crew_status(self, user_id: int, guild_id: int):
        return await self.db.get_crew_member(user_id, guild_id)

    async def add_crew_points(self, user_id: int, guild_id: int, points: int) -> tuple[int, str, bool]:
        """Adds points, auto-promotes rank if a new threshold is hit.
        Returns (new_points, new_rank, was_promoted)."""
        member = await self.db.get_crew_member(user_id, guild_id)
        if not member:
            return 0, "", False

        old_rank = member["rank"]
        new_points = await self.db.add_crew_points(user_id, guild_id, points)
        new_rank = rank_for_points(new_points)
        promoted = new_rank != old_rank
        if promoted:
            await self.db.set_crew_rank(user_id, guild_id, new_rank)
        return new_points, new_rank, promoted

    async def crew_roster(self, guild_id: int, limit: int = 10):
        return await self.db.get_crew_roster(guild_id, limit=limit)

    # -- Treasure ---------------------------------------------------------

    async def award_treasure(self, user_id: int, guild_id: int | None, item_name: str) -> None:
        await self.db.add_treasure(user_id, guild_id, item_name)

    async def treasure_list(self, user_id: int):
        return await self.db.get_treasure(user_id)

    # -- Ambient channels -------------------------------------------------

    async def enable_ambient(self, guild_id: int, channel_id: int) -> None:
        await self.db.enable_ambient(guild_id, channel_id)

    async def disable_ambient(self, guild_id: int, channel_id: int) -> None:
        await self.db.disable_ambient(guild_id, channel_id)

    async def ambient_channels(self):
        return await self.db.get_ambient_channels()

    async def touch_ambient_activity(self, guild_id: int, channel_id: int) -> None:
        await self.db.touch_ambient_activity(guild_id, channel_id)

    async def mark_ambient_entrance(self, guild_id: int, channel_id: int) -> None:
        await self.db.mark_ambient_entrance(guild_id, channel_id)

    async def mark_ambient_activity_post(self, guild_id: int, channel_id: int) -> None:
        await self.db.mark_ambient_activity_post(guild_id, channel_id)
