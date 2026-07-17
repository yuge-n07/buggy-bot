"""
database.py
-----------
aiosqlite-backed persistence layer. Stores per-user and per-guild
memory so Buggy remembers running jokes, nicknames, and how he feels
about you. This is the only thing that touches disk - never secrets,
just memory/personality data.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import aiosqlite

logger = logging.getLogger("buggy.database")

DB_PATH = Path("buggy_memory.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    nickname TEXT,
    relationship TEXT DEFAULT 'stranger',
    reputation INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS user_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    guild_id INTEGER,
    fact_type TEXT NOT NULL,      -- 'compliment' | 'insult' | 'fact' | 'joke' | 'preference'
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ambient_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    enabled_at REAL NOT NULL,
    last_activity_at REAL NOT NULL DEFAULT 0,
    last_entrance_at REAL NOT NULL DEFAULT 0,
    last_activity_post_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS crew_members (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    rank TEXT NOT NULL DEFAULT 'Cabin Boy',
    points INTEGER NOT NULL DEFAULT 0,
    joined_at REAL NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS treasure_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    guild_id INTEGER,
    item_name TEXT NOT NULL,
    found_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_user ON user_facts(user_id);
CREATE INDEX IF NOT EXISTS idx_summaries_channel ON conversation_summaries(channel_id);
CREATE INDEX IF NOT EXISTS idx_treasure_user ON treasure_log(user_id);
"""

# Keep memory bounded per spec ("limit stored context").
MAX_FACTS_PER_USER = 25
MAX_SUMMARIES_PER_CHANNEL = 10
MAX_TREASURE_SHOWN = 10

# Crew ranks in ascending order - points thresholds decide promotion.
CREW_RANKS: list[tuple[int, str]] = [
    (0, "Cabin Boy"),
    (10, "Professional Cannon Fodder"),
    (25, "Treasure Carrier"),
    (50, "Vice Clown"),
    (100, "Supreme Clown Officer"),
    (200, "Future Pirate Legend"),
]


def rank_for_points(points: int) -> str:
    """Returns the highest crew rank earned for a given points total."""
    rank = CREW_RANKS[0][1]
    for threshold, name in CREW_RANKS:
        if points >= threshold:
            rank = name
    return rank


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("Database connected at %s", self.path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            logger.info("Database connection closed")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected - call connect() first")
        return self._conn

    # -- Users -----------------------------------------------------

    async def upsert_user(self, user_id: int, username: str) -> None:
        now = time.time()
        await self.conn.execute(
            """
            INSERT INTO users (user_id, username, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                updated_at = excluded.updated_at
            """,
            (user_id, username, now, now),
        )
        await self.conn.commit()

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        return await cursor.fetchone()

    async def set_nickname(self, user_id: int, nickname: str) -> None:
        await self.conn.execute(
            "UPDATE users SET nickname = ?, updated_at = ? WHERE user_id = ?",
            (nickname, time.time(), user_id),
        )
        await self.conn.commit()

    async def set_relationship(self, user_id: int, relationship: str) -> None:
        await self.conn.execute(
            "UPDATE users SET relationship = ?, updated_at = ? WHERE user_id = ?",
            (relationship, time.time(), user_id),
        )
        await self.conn.commit()

    async def adjust_reputation(self, user_id: int, delta: int) -> int:
        """Nudges a user's reputation score and returns the new value."""
        await self.conn.execute(
            "UPDATE users SET reputation = reputation + ?, updated_at = ? WHERE user_id = ?",
            (delta, time.time(), user_id),
        )
        await self.conn.commit()
        cursor = await self.conn.execute(
            "SELECT reputation FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row["reputation"] if row else 0

    # -- Facts / running jokes / compliments / insults --------------

    async def add_fact(
        self, user_id: int, guild_id: int | None, fact_type: str, content: str
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO user_facts (user_id, guild_id, fact_type, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, guild_id, fact_type, content, time.time()),
        )
        await self.conn.commit()
        await self._trim_facts(user_id)

    async def _trim_facts(self, user_id: int) -> None:
        """Keeps only the most recent MAX_FACTS_PER_USER rows per user."""
        await self.conn.execute(
            """
            DELETE FROM user_facts
            WHERE user_id = ? AND id NOT IN (
                SELECT id FROM user_facts
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            )
            """,
            (user_id, user_id, MAX_FACTS_PER_USER),
        )
        await self.conn.commit()

    async def get_facts(self, user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM user_facts
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return await cursor.fetchall()

    async def clear_facts(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM user_facts WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    async def reset_user(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM user_facts WHERE user_id = ?", (user_id,))
        await self.conn.execute(
            "UPDATE users SET nickname = NULL, relationship = 'stranger', updated_at = ? WHERE user_id = ?",
            (time.time(), user_id),
        )
        await self.conn.commit()

    # -- Conversation summaries --------------------------------------

    async def add_summary(
        self, guild_id: int | None, channel_id: int, summary: str
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO conversation_summaries (guild_id, channel_id, summary, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (guild_id, channel_id, summary, time.time()),
        )
        await self.conn.commit()
        await self._trim_summaries(channel_id)

    async def _trim_summaries(self, channel_id: int) -> None:
        await self.conn.execute(
            """
            DELETE FROM conversation_summaries
            WHERE channel_id = ? AND id NOT IN (
                SELECT id FROM conversation_summaries
                WHERE channel_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            )
            """,
            (channel_id, channel_id, MAX_SUMMARIES_PER_CHANNEL),
        )
        await self.conn.commit()

    async def get_recent_summaries(
        self, channel_id: int, limit: int = 3
    ) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM conversation_summaries
            WHERE channel_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (channel_id, limit),
        )
        return await cursor.fetchall()

    async def clear_channel_history(self, channel_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM conversation_summaries WHERE channel_id = ?", (channel_id,)
        )
        await self.conn.commit()

    # -- Crew ---------------------------------------------------------

    async def join_crew(self, user_id: int, guild_id: int) -> bool:
        """Returns True if this created a new membership, False if
        they were already in the crew."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM crew_members WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        if await cursor.fetchone():
            return False
        await self.conn.execute(
            """
            INSERT INTO crew_members (user_id, guild_id, rank, points, joined_at)
            VALUES (?, ?, 'Cabin Boy', 0, ?)
            """,
            (user_id, guild_id, time.time()),
        )
        await self.conn.commit()
        return True

    async def get_crew_member(self, user_id: int, guild_id: int) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(
            "SELECT * FROM crew_members WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        return await cursor.fetchone()

    async def add_crew_points(self, user_id: int, guild_id: int, points: int) -> int:
        """Adds points for a crew member and returns their new total.
        No-op (returns 0) if they haven't joined the crew."""
        cursor = await self.conn.execute(
            "SELECT points FROM crew_members WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        row = await cursor.fetchone()
        if not row:
            return 0
        new_total = row["points"] + points
        await self.conn.execute(
            "UPDATE crew_members SET points = ? WHERE user_id = ? AND guild_id = ?",
            (new_total, user_id, guild_id),
        )
        await self.conn.commit()
        return new_total

    async def set_crew_rank(self, user_id: int, guild_id: int, rank: str) -> None:
        await self.conn.execute(
            "UPDATE crew_members SET rank = ? WHERE user_id = ? AND guild_id = ?",
            (rank, user_id, guild_id),
        )
        await self.conn.commit()

    async def get_crew_roster(self, guild_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM crew_members WHERE guild_id = ?
            ORDER BY points DESC LIMIT ?
            """,
            (guild_id, limit),
        )
        return await cursor.fetchall()

    # -- Treasure -------------------------------------------------------

    async def add_treasure(self, user_id: int, guild_id: int | None, item_name: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO treasure_log (user_id, guild_id, item_name, found_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, guild_id, item_name, time.time()),
        )
        await self.conn.commit()

    async def get_treasure(self, user_id: int, limit: int = MAX_TREASURE_SHOWN) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM treasure_log WHERE user_id = ?
            ORDER BY found_at DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return await cursor.fetchall()

    # -- Ambient channels -------------------------------------------------

    async def enable_ambient(self, guild_id: int, channel_id: int) -> None:
        await self.conn.execute(
            """
            INSERT INTO ambient_channels (guild_id, channel_id, enabled_at, last_activity_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET enabled_at = excluded.enabled_at
            """,
            (guild_id, channel_id, time.time(), time.time()),
        )
        await self.conn.commit()

    async def disable_ambient(self, guild_id: int, channel_id: int) -> None:
        await self.conn.execute(
            "DELETE FROM ambient_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        await self.conn.commit()

    async def get_ambient_channels(self) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute("SELECT * FROM ambient_channels")
        return await cursor.fetchall()

    async def touch_ambient_activity(self, guild_id: int, channel_id: int) -> None:
        await self.conn.execute(
            """
            UPDATE ambient_channels SET last_activity_at = ?
            WHERE guild_id = ? AND channel_id = ?
            """,
            (time.time(), guild_id, channel_id),
        )
        await self.conn.commit()

    async def mark_ambient_entrance(self, guild_id: int, channel_id: int) -> None:
        await self.conn.execute(
            """
            UPDATE ambient_channels SET last_entrance_at = ?
            WHERE guild_id = ? AND channel_id = ?
            """,
            (time.time(), guild_id, channel_id),
        )
        await self.conn.commit()

    async def mark_ambient_activity_post(self, guild_id: int, channel_id: int) -> None:
        await self.conn.execute(
            """
            UPDATE ambient_channels SET last_activity_post_at = ?
            WHERE guild_id = ? AND channel_id = ?
            """,
            (time.time(), guild_id, channel_id),
        )
        await self.conn.commit()

    # -- Stats --------------------------------------------------------

    async def get_stats(self) -> dict:
        cursor = await self.conn.execute("SELECT COUNT(*) as c FROM users")
        user_count = (await cursor.fetchone())["c"]
        cursor = await self.conn.execute("SELECT COUNT(*) as c FROM user_facts")
        fact_count = (await cursor.fetchone())["c"]
        cursor = await self.conn.execute(
            "SELECT COUNT(*) as c FROM conversation_summaries"
        )
        summary_count = (await cursor.fetchone())["c"]
        return {
            "users": user_count,
            "facts": fact_count,
            "summaries": summary_count,
        }
