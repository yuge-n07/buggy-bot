"""
gemini.py
---------
Wraps the google-genai client with the 5-key rotation manager,
automatic retries, and exponential backoff. This is the only place
that talks to Gemini.
"""

from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import errors as genai_errors

from config import GEMINI_MODEL_NAME
from rotation import AllKeysExhaustedError, GeminiKeyManager, KeyState

logger = logging.getLogger("buggy.gemini")

MAX_ATTEMPTS_PER_REQUEST = 5
FALLBACK_REPLY = (
    "*Buggy's severed hand fumbles the microphone* "
    "W-WAIT, technical difficulties?! That's... that's part of my GENIUS "
    "plan to build suspense! Try again in a second, peasant!"
)


class GeminiService:
    def __init__(self, key_manager: GeminiKeyManager):
        self.key_manager = key_manager
        self._clients: dict[int, genai.Client] = {}

    def _client_for(self, state: KeyState) -> genai.Client:
        if state.index not in self._clients:
            self._clients[state.index] = genai.Client(api_key=state.key)
        return self._clients[state.index]

    async def generate(self, prompt: str, use_search: bool = False) -> str:
        """
        Generates a response, rotating through keys and retrying on
        transient failures. The `use_search` parameter is ignored for now
        (Google Search grounding is not implemented).
        """
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS_PER_REQUEST + 1):
            try:
                state = await self.key_manager.get_next_key()
            except AllKeysExhaustedError as exc:
                logger.error("No Gemini keys available: %s", exc)
                return FALLBACK_REPLY

            client = self._client_for(state)

            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=GEMINI_MODEL_NAME,
                    contents=prompt,
                )
                await self.key_manager.report_success(state)
                text = getattr(response, "text", None)
                if not text:
                    logger.warning("Key #%d returned an empty response", state.index)
                    continue
                return text.strip()

            except genai_errors.ClientError as exc:
                status = getattr(exc, "code", None)
                if status == 429:
                    await self.key_manager.report_rate_limit(state)
                elif status in (401, 403):
                    await self.key_manager.report_invalid(state)
                else:
                    logger.warning("Key #%d client error: %s", state.index, exc)
                    await self.key_manager.report_transient_error(state)
                last_error = exc

            except genai_errors.ServerError as exc:
                logger.warning("Key #%d server error: %s", state.index, exc)
                await self.key_manager.report_transient_error(state)
                last_error = exc

            except Exception as exc:  # noqa: BLE001
                logger.warning("Key #%d unexpected error: %s", state.index, exc)
                await self.key_manager.report_transient_error(state)
                last_error = exc

            await asyncio.sleep(min(1.0 * attempt, 5.0))

        logger.error(
            "All %d attempts failed. Last error: %s. Key status: %s",
            MAX_ATTEMPTS_PER_REQUEST,
            last_error,
            self.key_manager.status_summary(),
        )
        return FALLBACK_REPLY

    async def summarize(self, transcript: str) -> str:
        """Asks Gemini for a short summary of older conversation."""
        prompt = (
            "Summarize the following Discord conversation in 2-3 short, "
            "neutral sentences for use as background memory later. Do not "
            "roleplay, do not add commentary, just summarize the key "
            f"topics and events:\n\n{transcript}"
        )
        try:
            state = await self.key_manager.get_next_key()
        except AllKeysExhaustedError:
            return transcript[:400]

        client = self._client_for(state)
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL_NAME,
                contents=prompt,
            )
            await self.key_manager.report_success(state)
            return (response.text or transcript[:400]).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Summary generation failed: %s", exc)
            await self.key_manager.report_transient_error(state)
            return transcript[:400]