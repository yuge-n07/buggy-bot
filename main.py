"""
main.py
-------
Entry point for Buggy D. GOAT. Collects runtime secrets (never saved
to disk), then starts the bot with auto-reconnect and graceful
shutdown handling.

Run with:  python main.py
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from bot import BuggyBot
from config import collect_runtime_secrets
from utils import setup_logging

logger = logging.getLogger("buggy.main")


async def run_bot() -> None:
    secrets = collect_runtime_secrets()
    bot = BuggyBot(secrets)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _request_shutdown(*_args):
        logger.info("Shutdown signal received...")
        stop_event.set()

    # Termux/Linux support SIGINT and SIGTERM; Windows only SIGINT.
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, _request_shutdown)
            except NotImplementedError:
                # Some environments (e.g. certain Termux setups) don't
                # support add_signal_handler - fall back below.
                pass

    async def _wait_and_close():
        await stop_event.wait()
        await bot.close()

    watcher_task = asyncio.create_task(_wait_and_close())

    try:
        # discord.py auto-reconnects on transient disconnects by
        # default (reconnect=True). This only returns on a fatal
        # error or an explicit close().
        await bot.start(secrets.discord_token, reconnect=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("Fatal error while running the bot: %s", exc, exc_info=True)
    finally:
        stop_event.set()
        watcher_task.cancel()
        if not bot.is_closed():
            await bot.close()


def main() -> None:
    setup_logging(level=logging.INFO)
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Goodbye! (Buggy will be back, obviously)")
        sys.exit(0)


if __name__ == "__main__":
    main()
