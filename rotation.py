"""
rotation.py
-----------
Round-robin manager for up to 5 Gemini API keys.

Design:
- Each key has its own state: healthy / cooling_down / invalid.
- On rate-limit (429) or transient server error, the key is put on a
  cooldown timer with exponential backoff and we move to the next
  healthy key.
- On an auth/permission error (bad key), the key is marked invalid
  permanently for this session and skipped from then on.
- We only ever log key *index* (e.g. "key #3"), never the key value.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto

logger = logging.getLogger("buggy.rotation")


class KeyStatus(Enum):
    HEALTHY = auto()
    COOLING_DOWN = auto()
    INVALID = auto()


@dataclass
class KeyState:
    index: int
    key: str
    status: KeyStatus = KeyStatus.HEALTHY
    cooldown_until: float = 0.0
    consecutive_failures: int = 0
    total_uses: int = 0


class AllKeysExhaustedError(Exception):
    """Raised when every configured Gemini key is invalid or cooling down."""


class GeminiKeyManager:
    """Round-robin rotation across N Gemini API keys with cooldowns."""

    BASE_COOLDOWN_SECONDS = 5.0
    MAX_COOLDOWN_SECONDS = 300.0

    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("GeminiKeyManager requires at least one key")
        self._states: list[KeyState] = [
            KeyState(index=i + 1, key=k) for i, k in enumerate(keys)
        ]
        self._cursor = 0
        self._lock = asyncio.Lock()

    @property
    def total_keys(self) -> int:
        return len(self._states)

    def _is_available(self, state: KeyState) -> bool:
        if state.status == KeyStatus.INVALID:
            return False
        if state.status == KeyStatus.COOLING_DOWN:
            if time.monotonic() >= state.cooldown_until:
                state.status = KeyStatus.HEALTHY
                return True
            return False
        return True

    async def get_next_key(self) -> KeyState:
        """Returns the next available key in round-robin order,
        skipping invalid/cooling-down keys. Raises if none are usable."""
        async with self._lock:
            n = len(self._states)
            for offset in range(n):
                idx = (self._cursor + offset) % n
                state = self._states[idx]
                if self._is_available(state):
                    self._cursor = (idx + 1) % n
                    state.total_uses += 1
                    return state

            raise AllKeysExhaustedError(
                "All Gemini keys are currently invalid or cooling down."
            )

    async def report_success(self, state: KeyState) -> None:
        async with self._lock:
            state.consecutive_failures = 0
            state.status = KeyStatus.HEALTHY

    async def report_rate_limit(self, state: KeyState) -> None:
        """Put a key on an exponential-backoff cooldown after a 429."""
        async with self._lock:
            state.consecutive_failures += 1
            backoff = min(
                self.BASE_COOLDOWN_SECONDS * (2 ** (state.consecutive_failures - 1)),
                self.MAX_COOLDOWN_SECONDS,
            )
            state.status = KeyStatus.COOLING_DOWN
            state.cooldown_until = time.monotonic() + backoff
            logger.warning(
                "Key #%d hit a rate limit - cooling down for %.0fs",
                state.index,
                backoff,
            )

    async def report_transient_error(self, state: KeyState) -> None:
        """Short cooldown for network blips / 5xx errors."""
        async with self._lock:
            state.consecutive_failures += 1
            backoff = min(
                self.BASE_COOLDOWN_SECONDS * (1.5 ** (state.consecutive_failures - 1)),
                60.0,
            )
            state.status = KeyStatus.COOLING_DOWN
            state.cooldown_until = time.monotonic() + backoff
            logger.warning(
                "Key #%d hit a transient error - cooling down for %.0fs",
                state.index,
                backoff,
            )

    async def report_invalid(self, state: KeyState) -> None:
        """Permanently disable a key for this session (bad credentials)."""
        async with self._lock:
            state.status = KeyStatus.INVALID
            logger.error(
                "Key #%d appears invalid and will be skipped for the rest of this session",
                state.index,
            )

    def status_summary(self) -> str:
        parts = []
        for s in self._states:
            self._is_available(s)  # refresh cooldown expiry lazily
            tag = {
                KeyStatus.HEALTHY: "OK",
                KeyStatus.COOLING_DOWN: "COOLDOWN",
                KeyStatus.INVALID: "INVALID",
            }[s.status]
            parts.append(f"#{s.index}:{tag}(uses={s.total_uses})")
        return " ".join(parts)

    def healthy_count(self) -> int:
        return sum(1 for s in self._states if self._is_available(s))
