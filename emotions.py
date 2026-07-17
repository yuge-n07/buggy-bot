"""
emotions.py
-----------
Decides Buggy's emotional state for a given exchange and, through the
GifCooldownManager, decides whether a reaction GIF genuinely earns its
place. Deliberately keyword/signal-based rather than another Gemini
call - keeps AI usage reserved for actual conversation per spec, and
keeps the decision fast and deterministic.
"""

from __future__ import annotations

import logging
import random
import re

from gifs import GifCooldownManager, GifEntry

logger = logging.getLogger("buggy.emotions")

# Keyword banks scored against Buggy's own reply text. These aren't
# exhaustive dictionaries - just enough signal to catch the obvious
# emotional beats of a given reply.
EMOTION_KEYWORDS: dict[str, list[str]] = {
    "overconfident": ["greatest", "genius", "obviously", "of course i", "told you", "legendary", "unmatched"],
    "dramatic": ["behold", "witness", "declare", "at last", "the future pirate king", "mark my words"],
    "terrified": ["retreat", "run", "danger", "w-wait", "n-no", "please no", "not that", "scary"],
    "shocked": ["what?!", "no way", "impossible", "unbelievable", "you're kidding"],
    "celebrating": ["victory", "we did it", "i won", "celebrate", "party", "success"],
    "crying_happy": ["you really mean it", "i'm touched", "finally someone", "sniff", "tears of joy"],
    "evil_plotting": ["muahaha", "revenge", "my genius plan", "little do they know", "evil"],
    "annoyed": ["ugh", "seriously?", "how dare you", "annoying"],
    "smug": ["heh", "as expected", "told you so", "predictable"],
    "embarrassed": ["okay fine", "you got me", "don't tell anyone", "that's... not", "in my defense"],
    "suspicious": ["hmm", "wait a second", "something's fishy", "i don't trust", "suspicious"],
    "confused": ["huh?", "wait, what", "i don't get it", "come again?"],
    "competitive": ["i'll beat you", "no one beats buggy", "challenge accepted", "bring it on"],
    "greedy": ["treasure", "berries", "gimme", "that's mine", "all mine"],
    "excited": ["let's go", "yes yes yes", "can't wait", "so pumped", "amazing news"],
}

# Extra signal boosts from conversational context (computed by the
# caller and passed in as a dict of booleans/strings).
SIGNAL_BOOSTS: dict[str, list[str]] = {
    "praised": ["crying_happy", "smug", "overconfident"],
    "insulted": ["annoyed", "embarrassed"],
    "danger_mentioned": ["terrified"],
    "shanks_mentioned": ["terrified", "suspicious"],
    "exposed": ["embarrassed", "confused"],
    "achievement": ["celebrating", "excited"],
    "user_success": ["celebrating"],
}

ATTACH_BASE_CHANCE = 0.35  # only ~1 in 3 detected-emotion replies get a GIF
MIN_SCORE_TO_CONSIDER = 1.0


class EmotionManager:
    def __init__(self):
        self.gif_cooldowns = GifCooldownManager()

    def classify(
        self, reply_text: str, signals: dict[str, bool] | None = None
    ) -> tuple[str | None, float]:
        """Scores each emotion against the reply text + context signals.
        Returns (best_emotion_or_None, intensity 0-1)."""
        signals = signals or {}
        lowered = reply_text.lower()

        scores: dict[str, float] = {emo: 0.0 for emo in EMOTION_KEYWORDS}

        for emotion, words in EMOTION_KEYWORDS.items():
            for w in words:
                if w in lowered:
                    scores[emotion] += 1.0

        # ALL-CAPS shouting and lots of exclamation marks lean dramatic/excited.
        caps_words = re.findall(r"\b[A-Z]{4,}\b", reply_text)
        if len(caps_words) >= 2:
            scores["dramatic"] += 0.5
            scores["excited"] += 0.5

        if reply_text.count("!") >= 3:
            scores["excited"] += 0.5

        for signal_name, boosted_emotions in SIGNAL_BOOSTS.items():
            if signals.get(signal_name):
                for emo in boosted_emotions:
                    scores[emo] += 1.5

        best_emotion = max(scores, key=lambda e: scores[e])
        best_score = scores[best_emotion]

        if best_score < MIN_SCORE_TO_CONSIDER:
            return None, 0.0

        intensity = min(best_score / 4.0, 1.0)
        return best_emotion, intensity

    def decide_gif(
        self,
        channel_id: int,
        reply_text: str,
        signals: dict[str, bool] | None = None,
        force_tags: list[str] | None = None,
        allow_rare: bool = False,
    ) -> GifEntry | None:
        """Full pipeline: classify emotion, roll the dice on whether a
        GIF is warranted, and pick one respecting cooldowns. Most of
        the time this returns None - that's the point."""
        emotion, intensity = self.classify(reply_text, signals)
        if not emotion:
            return None

        chance = ATTACH_BASE_CHANCE * (0.5 + intensity)  # scale with intensity
        if random.random() > chance:
            return None

        tags = force_tags or []
        return self.gif_cooldowns.pick(channel_id, emotion, tags=tags, allow_rare=allow_rare)
