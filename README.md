# 🤡 Buggy D. GOAT - Discord AI Bot

A production-ready Discord bot that roleplays as **Buggy the Clown** from *One Piece* —
dramatic, egotistical, chaotic, cowardly-when-it-counts, and always convinced he's the
future Pirate King. Built specifically to run smoothly on **Termux (Android)**, with no
Docker, no systemd, and low resource usage.

Powered by Google's **Gemini 3.5 Flash** with a 5-key rotation system so you never get
stuck on a single rate limit.

---

## Features

- Full async architecture (`discord.py` + `aiosqlite`)
- Reads the last 10-20 channel messages for natural, in-context replies
- Per-user memory: nicknames, running jokes, compliments/insults, relationship status, reputation
- 5-key Gemini rotation with automatic failover, cooldowns, and exponential backoff
- Auto-reconnect on Discord disconnects, graceful `Ctrl+C` shutdown
- Works in servers, DMs, and threads
- Secrets are entered at runtime and **never written to disk**
- **Emotion-driven reaction GIFs** - Buggy only reacts with a GIF when it genuinely fits the moment, with per-channel cooldowns so it never feels spammy
- **Ambient presence** - rare random entrances and idle "daily activity" flavor lines in channels you opt in with `!ambient`
- **Mini-games** - dice duels, coin flips, number guessing, One Piece trivia, pirate duels, rock-paper-scissors, and emoji riddles, all via slash commands/buttons (zero AI calls)
- **Crew & treasure systems** - members can `/joincrew`, earn cosmetic ranks, and passively stumble onto silly treasure while chatting

---

## 1. Termux Installation

Install Termux from F-Droid (recommended) or GitHub releases (the Play Store version is
outdated and not recommended).

```bash
pkg update -y
pkg upgrade -y
pkg install python git -y
```

Clone or copy this project onto your device, then move into the folder:

```bash
cd buggy-bot
```

## 2. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs `discord.py`, `google-genai`, `python-dotenv`, `aiosqlite`, `aiofiles`,
`orjson`, and `colorama`. All lightweight, pure-Python-friendly packages that install
cleanly under Termux.

## 3. Run the Bot

```bash
python main.py
```

On startup you'll be prompted (with hidden input where possible) for:

- Discord Bot Token
- Gemini API Key 1 (required)
- Gemini API Key 2-5 (optional but recommended for rotation)
- Bot Owner ID (your Discord user ID, for owner-only commands)
- Optional Test Guild ID

None of these are saved to disk. You'll re-enter them every time you start the bot.
If you want a faster restart loop during setup, keep a private note of them somewhere
safe outside this project.

## 4. Creating a Discord Bot Token

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**, give it a name (e.g. "Buggy D. GOAT")
3. Go to the **Bot** tab -> **Reset Token** -> copy the token
4. Under **Privileged Gateway Intents**, enable:
   - `MESSAGE CONTENT INTENT`
   - `SERVER MEMBERS INTENT`
5. Go to **OAuth2 -> URL Generator**, select the `bot` scope, and permissions:
   `Send Messages`, `Read Message History`, `Read Messages/View Channels`,
   `Use External Emojis`, `Add Reactions`
6. Use the generated URL to invite the bot to your server

## 5. Getting Gemini API Keys

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Create up to 5 API keys (separate projects give you separate quotas, which is the
   whole point of the rotation system)
3. Paste them in one at a time when `main.py` asks

## 6. Keeping the Bot Alive in Termux

Termux will kill background processes if the app is closed unless you take a couple of
extra steps:

- Run `termux-wake-lock` before starting the bot to prevent Android from sleeping the
  process (requires Termux:API or is often built in, depending on your Termux version)
- Disable battery optimization for Termux in Android system settings
- To keep it running after closing the terminal app, use a terminal multiplexer:

```bash
pkg install tmux -y
tmux new -s buggy
python main.py
# detach with Ctrl+B then D - the bot keeps running
# reattach later with: tmux attach -t buggy
```

---

## Commands

| Command | Description |
|---|---|
| `!ping` | Check latency |
| `!help` | List all commands |
| `!about` | Buggy introduces himself |
| `!buggy` | Random Buggy wisdom |
| `!stats` | Uptime, memory stats, Gemini key health |
| `!persona` | Reminder there's only one Buggy |
| `!context` | See the channel's stored conversation summary |
| `!memory [@user]` | See what Buggy remembers about you (or someone else) |
| `!resetmemory` / `!forget` | Wipe Buggy's memory of you |
| `!clearhistory` | Owner-only: wipe a channel's conversation memory |
| `!reload` | Owner-only: reload signal |
| `!ambient` | Toggle random entrances/idle chatter in this channel (Manage Server) |

**Slash commands (games - no AI usage):**

| Command | Description |
|---|---|
| `/coinflip` | Flip a coin |
| `/diceduel @user` | Roll dice against another member |
| `/duel @user` | A dramatic pirate duel |
| `/rps` | Rock-paper-scissors against Buggy, via buttons |
| `/trivia` | One Piece trivia, first correct answer wins |
| `/guess start` / `/guess number` | Number-guessing game |
| `/emojiguess` | Solve Buggy's emoji riddle in chat |
| `/joincrew` | Join Buggy's crew |
| `/crew` | Check your crew rank and points |
| `/treasure` | See treasure you've found while chatting |
| `/medals <character>` | Best medal set for an OPBR character, with traits and pair/trio bonuses |

Buggy also responds naturally when **mentioned**, **replied to**, or **DMed** —
no command needed.

---

## OPBR Medal Helper

`/medals <character>` looks up that character's signature medals from a bundled
dataset and finds the 3-medal combo that triggers the most pair/trio tag bonuses,
showing each medal's icon and unique trait plus the bonuses unlocked.

This data comes from a one-time extraction of [Ace Kyle's OPBR Medal Set
Builder](https://ace-kyle.github.io/OPBR-medal-set-builder/) (a fan tool - not an
official API, and not affiliated with Bandai Namco). That site has no public API;
its data lives embedded in a minified JS bundle, so `data/opbr_data.json` is a
static snapshot rather than a live feed.

**To refresh the dataset** when the site adds new medals/characters:
1. Open the site, DevTools > Network, reload, find `assets/main-<hash>.js`
2. Download that file
3. Run: `python3 scripts/extract_opbr_data.py path/to/main-<hash>.js`

This overwrites `data/opbr_data.json`. Do this occasionally by hand - please don't
script automated polling against their site, it's someone's fan project.

---

## Emotion & GIF System

Every reply Buggy generates is scanned for its emotional tone (overconfident, dramatic,
terrified, shocked, celebrating, and more) using lightweight keyword/context heuristics -
no extra Gemini call. Most replies get no GIF at all; only when an emotion clearly fits
does Buggy occasionally attach one of his reaction GIFs, and a per-channel cooldown keeps
it from repeating too often. This keeps GIFs feeling like a genuine reaction instead of
a gimmick.

## Ambient Presence

Run `!ambient` in any channel (requires Manage Server) to let Buggy occasionally drop in
on his own - rare "I RETURNED!" style entrances and idle complaints/boasts - roughly a
few times a day, and only in channels that have been active recently. Run `!ambient`
again in the same channel to turn it back off.

---

## Project Structure

```
main.py          - entry point, secret collection, graceful shutdown
bot.py           - BuggyBot class wiring everything together
config.py        - runtime secret prompts + constants
rotation.py      - 5-key Gemini round-robin rotation manager
gemini.py        - Gemini API calls with retries/backoff
memory.py        - high-level memory API
database.py      - aiosqlite schema and queries
personality.py   - Buggy's system prompt + prompt assembly
commands.py      - all !commands
events.py        - message listening, context gathering, lifecycle events
emotions.py      - emotion classification + GIF decision pipeline
gifs.py          - GIF library, tagged by emotion, with cooldown management
ambient.py       - random entrances + idle daily-activity background loop
games.py         - mini-games (slash commands, buttons, views)
opbr.py          - OPBR medal dataset loader + best-set solver
opbr_commands.py - /medals slash command
utils.py         - logging setup, message splitting
data/opbr_data.json    - bundled OPBR medal/character dataset snapshot
scripts/extract_opbr_data.py - regenerates data/opbr_data.json from the site's JS bundle
requirements.txt
README.md
```

---

## Troubleshooting

**Bot won't start / `ModuleNotFoundError`**
Re-run `pip install -r requirements.txt`. On some Termux setups you may need
`pkg install rust binutils` first for packages that build from source.

**"Missing Access" or bot doesn't respond in a channel**
Check the bot has `View Channel`, `Send Messages`, and `Read Message History`
permissions in that channel, and that `MESSAGE CONTENT INTENT` is enabled in the
Developer Portal.

**All Gemini keys show `INVALID` or `COOLDOWN` in `!stats`**
Double check the keys were typed correctly at startup (they're hidden input, so typos
are easy). Wait a minute for cooldowns to clear, or generate fresh keys from AI Studio.

**Bot disconnects when I lock my phone**
See the "Keeping the Bot Alive in Termux" section above — use `tmux` plus disabling
battery optimization for Termux.

**Getting `discord.errors.PrivilegedIntentsRequired`**
Enable `MESSAGE CONTENT INTENT` and `SERVER MEMBERS INTENT` in the Developer Portal
under your bot's settings, then restart.
