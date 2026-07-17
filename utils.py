"""
utils.py
--------
Shared helpers: colorful logging setup for Termux consoles, and
Discord message splitting so long Buggy rants don't get rejected.
"""

from __future__ import annotations

import logging
import sys

from config import DISCORD_MESSAGE_LIMIT

try:
    from colorama import Fore, Style, init as colorama_init

    colorama_init(autoreset=True)
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False


class ColorFormatter(logging.Formatter):
    """A lightweight formatter that adds color on terminals that
    support it (Termux does) and degrades gracefully if colorama
    isn't installed."""

    LEVEL_COLORS = {}
    if _HAS_COLOR:
        LEVEL_COLORS = {
            logging.DEBUG: Fore.CYAN,
            logging.INFO: Fore.GREEN,
            logging.WARNING: Fore.YELLOW,
            logging.ERROR: Fore.RED,
            logging.CRITICAL: Fore.MAGENTA + Style.BRIGHT,
        }

    def format(self, record: logging.LogRecord) -> str:
        base = f"[{self.formatTime(record, '%H:%M:%S')}] [{record.levelname}] {record.name}: {record.getMessage()}"
        if _HAS_COLOR:
            color = self.LEVEL_COLORS.get(record.levelno, "")
            return f"{color}{base}{Style.RESET_ALL}"
        return base


def setup_logging(level: int = logging.INFO) -> None:
    """Configures root logging with a Termux-friendly colored handler.
    Safe to call once at startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # Quiet down noisy third-party loggers a bit.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)


def split_message(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    """Splits a long message into Discord-safe chunks, preferring to
    break on paragraph/sentence/word boundaries so Buggy doesn't get
    cut off mid-word like some kind of amateur."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text

    while len(remaining) > limit:
        window = remaining[:limit]

        split_at = window.rfind("\n\n")
        if split_at == -1 or split_at < limit * 0.5:
            split_at = window.rfind("\n")
        if split_at == -1 or split_at < limit * 0.5:
            split_at = window.rfind(". ")
            if split_at != -1:
                split_at += 1  # keep the period with the chunk
        if split_at == -1 or split_at < limit * 0.5:
            split_at = window.rfind(" ")
        if split_at == -1:
            split_at = limit

        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks
