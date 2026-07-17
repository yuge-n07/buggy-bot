"""
gifs.py
-------
Buggy's reaction GIF library, tagged by emotion (and a few extra
context tags for niche cases), plus a cooldown-aware picker so GIFs
stay a special occurrence rather than spam.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

logger = logging.getLogger("buggy.gifs")


@dataclass
class GifEntry:
    name: str
    url: str
    emotions: list[str]
    tags: list[str] = field(default_factory=list)
    rare: bool = False  # only used for special occasions, weighted down


GIF_LIBRARY: list[GifEntry] = [
    GifEntry(
        "Buggy Silly Dance",
        "https://tenor.com/b5JX4BItBwa.gif",
        emotions=["celebrating", "overconfident", "smug"],
        tags=["small_win", "bragging"],
    ),
    GifEntry(
        "Buggy & Luffy Clapping",
        "https://tenor.com/t1dQTzo34N.gif",
        emotions=["celebrating", "smug"],
        tags=["congratulating", "sarcastic_applause", "user_success"],
    ),
    GifEntry(
        "Buggy Shocked",
        "https://tenor.com/bGCY8.gif",
        emotions=["shocked"],
        tags=["plot_twist", "cursed_message", "unexpected_reveal"],
    ),
    GifEntry(
        "Buggy Crying Happy",
        "https://tenor.com/tNX7dw2bLqI.gif",
        emotions=["crying_happy"],
        tags=["praised", "buggy_wins", "emotional_moment"],
    ),
    GifEntry(
        "Aura Walk",
        "https://tenor.com/fUXddgmPRUw.gif",
        emotions=["dramatic", "overconfident"],
        tags=["dramatic_entrance", "declaring_victory"],
    ),
    GifEntry(
        "Behind Akainu",
        "https://tenor.com/rbaJVTCq6Sz.gif",
        emotions=["terrified", "smug"],
        tags=["fake_tough", "intimidating"],
    ),
    GifEntry(
        "Buggy & Luffy Cheering",
        "https://tenor.com/ov8pjymqbrU.gif",
        emotions=["celebrating", "excited"],
        tags=["server_celebration", "birthday", "level_up", "achievement"],
    ),
    GifEntry(
        "Sake Drink",
        "https://tenor.com/h1XbPwVWRrG.gif",
        emotions=["celebrating"],
        tags=["relaxing", "late_night", "casual_chat"],
    ),
    GifEntry(
        "Knife Lick",
        "https://tenor.com/bvDZ2.gif",
        emotions=["evil_plotting"],
        tags=["playful_villain", "fake_revenge"],
    ),
    GifEntry(
        "Realization",
        "https://tenor.com/rIfKkKYb4Au.gif",
        emotions=["embarrassed", "confused"],
        tags=["sudden_understanding", "exposed"],
    ),
    GifEntry(
        "Genius Jester Introduction",
        "https://tenor.com/bdhPKFIbxaf.gif",
        emotions=["dramatic"],
        tags=["new_server", "major_announcement", "special_entrance"],
        rare=True,
    ),
    GifEntry(
        "Happy Drinking",
        "https://tenor.com/gnsMo34ulZl.gif",
        emotions=["celebrating", "excited"],
        tags=["community_celebration", "movie_night", "game_night", "relaxed"],
    ),
    GifEntry(
        "Serious Talking",
        "https://tenor.com/v66Tiq7lhYi.gif",
        emotions=["dramatic"],
        tags=["giving_advice", "serious_discussion", "motivating"],
    ),
    GifEntry(
        "Snow Walk",
        "https://tenor.com/bVFTe3WHQhz.gif",
        emotions=["embarrassed", "dramatic"],
        tags=["dramatic_exit", "lost_argument", "announcing_break"],
    ),
    GifEntry(
        "Sweating",
        "https://tenor.com/sDNIkp9Amf0.gif",
        emotions=["terrified", "suspicious", "embarrassed"],
        tags=["shanks_mentioned", "caught_lying", "threatened", "panic"],
    ),
]

_EMOTION_INDEX: dict[str, list[GifEntry]] = {}
for _entry in GIF_LIBRARY:
    for _emo in _entry.emotions:
        _EMOTION_INDEX.setdefault(_emo, []).append(_entry)


class GifCooldownManager:
    """Keeps GIF usage rare and varied per channel.

    Rules:
    - At least MIN_GAP_SECONDS between any two GIFs in the same channel.
    - A specific GIF won't repeat in a channel until RECENT_WINDOW other
      GIFs have been sent (or enough time has passed).
    """

    MIN_GAP_SECONDS = 5 * 60  # at least 5 minutes between GIFs in a channel
    RECENT_WINDOW = 5  # don't repeat a GIF within the last 5 sent

    def __init__(self):
        self._last_sent_at: dict[int, float] = {}
        self._recent_urls: dict[int, list[str]] = {}

    def can_send_any(self, channel_id: int) -> bool:
        last = self._last_sent_at.get(channel_id, 0.0)
        return (time.monotonic() - last) >= self.MIN_GAP_SECONDS

    def _is_recent(self, channel_id: int, url: str) -> bool:
        recent = self._recent_urls.get(channel_id, [])
        return url in recent

    def record(self, channel_id: int, url: str) -> None:
        self._last_sent_at[channel_id] = time.monotonic()
        recent = self._recent_urls.setdefault(channel_id, [])
        recent.append(url)
        if len(recent) > self.RECENT_WINDOW:
            recent.pop(0)

    def pick(
        self,
        channel_id: int,
        emotion: str | None,
        tags: list[str] | None = None,
        allow_rare: bool = False,
    ) -> GifEntry | None:
        """Returns a suitable GIF for this emotion/context, or None if
        nothing fits, the cooldown hasn't cleared, or nothing is
        appropriate right now."""
        if not emotion:
            return None
        if not self.can_send_any(channel_id):
            return None

        candidates = list(_EMOTION_INDEX.get(emotion, []))
        if not candidates:
            return None

        if tags:
            tag_matches = [c for c in candidates if set(c.tags) & set(tags)]
            if tag_matches:
                candidates = tag_matches

        if not allow_rare:
            non_rare = [c for c in candidates if not c.rare]
            if non_rare:
                candidates = non_rare

        fresh = [c for c in candidates if not self._is_recent(channel_id, c.url)]
        pool = fresh if fresh else candidates

        choice = random.choice(pool)
        self.record(channel_id, choice.url)
        logger.debug("Picked GIF '%s' for emotion=%s in channel %d", choice.name, emotion, channel_id)
        return choice
