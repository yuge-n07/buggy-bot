"""
config.py
---------
Handles runtime configuration for Buggy D. GOAT.

On Railway (or any non-interactive environment), we read all secrets
from environment variables and never prompt the user.
If running interactively, we fall back to prompting (and saving .env).
"""

from __future__ import annotations

import getpass
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The model used for every AI response.
GEMINI_MODEL_NAME = "gemini-3.5-flash"

# How many recent channel messages to pull for conversation context.
CONTEXT_MESSAGE_COUNT = 15

# Discord's hard message length limit.
DISCORD_MESSAGE_LIMIT = 2000

ENV_FILE = Path(".env")


@dataclass
class RuntimeSecrets:
    discord_token: str
    gemini_keys: list[str] = field(default_factory=list)
    owner_id: int = 0
    test_guild_id: int | None = None


def is_interactive() -> bool:
    """Return True if we are running in an interactive terminal."""
    return sys.stdin.isatty()


def _load_from_env() -> dict[str, str]:
    """Loads key/value pairs from .env file if it exists."""
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


def _prompt_hidden(label: str, required: bool = True) -> str:
    """Prompt for a hidden value. Only used if interactive."""
    while True:
        try:
            value = getpass.getpass(f"{label}: ").strip()
        except Exception:
            print("(hidden input unavailable, input will be visible)")
            value = input(f"{label}: ").strip()

        if value or not required:
            return value
        print("  -> This value is required. Please try again.")


def _prompt_visible(label: str, required: bool = True) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value or not required:
            return value
        print("  -> This value is required. Please try again.")


def _write_env(secrets: RuntimeSecrets) -> None:
    """Writes secrets to .env file so they persist across restarts."""
    lines = [
        "# Discord Bot Token",
        f"DISCORD_TOKEN={secrets.discord_token}",
        "",
        "# Gemini API keys (up to 5)",
    ]
    for i, key in enumerate(secrets.gemini_keys, 1):
        lines.append(f"GEMINI_KEY_{i}={key}")
    lines.extend([
        "",
        "# Your Discord user ID (owner)",
        f"OWNER_ID={secrets.owner_id}",
    ])
    if secrets.test_guild_id is not None:
        lines.extend([
            "",
            "# Optional: guild ID for instant slash command sync during testing",
            f"TEST_GUILD_ID={secrets.test_guild_id}",
        ])
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    try:
        os.chmod(ENV_FILE, 0o600)
    except Exception:
        pass


def collect_runtime_secrets() -> RuntimeSecrets:
    """
    Collects runtime secrets.
    If interactive: load from .env or prompt, then save to .env.
    If non-interactive: read from environment variables only.
    """
    # First, try to load from .env (if it exists)
    env = _load_from_env()

    # If we are non‑interactive, we must read from environment variables.
    if not is_interactive():
        discord_token = os.environ.get("DISCORD_TOKEN")
        if not discord_token:
            # In non‑interactive, we must have the token set.
            print("ERROR: DISCORD_TOKEN environment variable is required in non‑interactive mode.")
            sys.exit(1)

        gemini_keys = []
        for i in range(1, 6):
            key = os.environ.get(f"GEMINI_KEY_{i}")
            if key:
                gemini_keys.append(key)
        if not gemini_keys:
            print("ERROR: At least one GEMINI_KEY_* environment variable is required in non‑interactive mode.")
            sys.exit(1)

        owner_id_str = os.environ.get("OWNER_ID")
        if not owner_id_str:
            print("ERROR: OWNER_ID environment variable is required in non‑interactive mode.")
            sys.exit(1)
        try:
            owner_id = int(owner_id_str)
        except ValueError:
            print("ERROR: OWNER_ID must be a number.")
            sys.exit(1)

        test_guild_id = None
        test_guild_str = os.environ.get("TEST_GUILD_ID")
        if test_guild_str:
            try:
                test_guild_id = int(test_guild_str)
            except ValueError:
                pass  # ignore invalid

        return RuntimeSecrets(
            discord_token=discord_token,
            gemini_keys=gemini_keys,
            owner_id=owner_id,
            test_guild_id=test_guild_id,
        )

    # Interactive mode: load from .env or prompt, then save .env
    discord_token = env.get("DISCORD_TOKEN")
    if not discord_token:
        discord_token = _prompt_hidden("Discord Bot Token")

    gemini_keys = []
    # Check for GEMINI_KEY_1 .. GEMINI_KEY_5 in env
    for i in range(1, 6):
        key = env.get(f"GEMINI_KEY_{i}")
        if key:
            gemini_keys.append(key)

    if not gemini_keys:
        print("\nEnter your Gemini API keys (used in round-robin rotation).")
        for i in range(1, 6):
            key = _prompt_hidden(f"Gemini API Key {i}", required=(i == 1))
            if key:
                gemini_keys.append(key)

    if not gemini_keys:
        print("\nAt least one Gemini API key is required. Exiting.")
        sys.exit(1)

    owner_id = env.get("OWNER_ID")
    if owner_id:
        try:
            owner_id = int(owner_id)
        except ValueError:
            print("Owner ID in .env is not numeric. Please re-enter.")
            owner_id = None
    if not owner_id:
        owner_id_raw = _prompt_visible("Bot Owner ID (your Discord user ID)")
        try:
            owner_id = int(owner_id_raw)
        except ValueError:
            print("Owner ID must be numeric. Exiting.")
            sys.exit(1)

    test_guild_id = env.get("TEST_GUILD_ID")
    if test_guild_id:
        try:
            test_guild_id = int(test_guild_id)
        except ValueError:
            print("Test Guild ID in .env is not numeric. Ignoring.")
            test_guild_id = None
    if test_guild_id is None:
        test_guild_raw = _prompt_visible(
            "Optional Test Guild ID (press Enter to skip)", required=False
        )
        test_guild_id = int(test_guild_raw) if test_guild_raw else None

    secrets = RuntimeSecrets(
        discord_token=discord_token,
        gemini_keys=gemini_keys,
        owner_id=owner_id,
        test_guild_id=test_guild_id,
    )

    # Save to .env so we don't ask again next time
    _write_env(secrets)
    print("\n✅ Secrets saved to .env – you won't be prompted again.\n")

    return secrets