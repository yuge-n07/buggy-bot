"""
games.py
--------
Lightweight, deterministic social mini-games. None of these call
Gemini - they're pure Discord interactions (slash commands, buttons,
views) so they stay fast and free of API usage, per spec.
"""

from __future__ import annotations

import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("buggy.games")

TREASURE_ITEMS = [
    "a suspiciously shiny Fake Berry",
    "a Legendary Clown Nose",
    "an Ancient Map (leads nowhere)",
    "a Broken Treasure Chest (empty, obviously)",
    "the ridiculous title 'Admiral of Nonsense'",
    "a single gold coin that's probably chocolate",
    "a wanted poster (of Buggy, badly drawn)",
    "a rubber duck claiming to be a Devil Fruit",
]

TRIVIA_BANK = [
    {
        "question": "What is the name of Buggy's signature Devil Fruit power?",
        "choices": ["Bara Bara no Mi", "Gomu Gomu no Mi", "Mera Mera no Mi", "Suna Suna no Mi"],
        "correct": 0,
    },
    {
        "question": "Buggy sailed under which legendary captain as a cabin boy?",
        "choices": ["Whitebeard", "Roger", "Shanks", "Garp"],
        "correct": 1,
    },
    {
        "question": "What color is Buggy's iconic nose?",
        "choices": ["Blue", "Green", "Red", "Purple"],
        "correct": 2,
    },
    {
        "question": "Which organization did Buggy end up leading after Marineford?",
        "choices": ["Revolutionary Army", "Cross Guild", "Baroque Works", "CP9"],
        "correct": 1,
    },
    {
        "question": "What does Buggy call his crew members, generally?",
        "choices": ["The Elite", "Cannon fodder", "Legends", "Nobles"],
        "correct": 1,
    },
]

EMOJI_RIDDLES = [
    ("🤡🏴‍☠️👑", "buggy"),
    ("💰🗺️❓", "treasure"),
    ("⚔️🍖🏝️", "onepiece"),
    ("🍊🐒👒", "luffy"),
    ("🍷⚔️👹", "shanks"),
]

GAME_TIMEOUT_SECONDS = 30


def _reward_flavor(item: str) -> str:
    return f"You dig around and find... {item}! Buggy already claims it's rightfully his. 🏴‍☠️"


class RPSView(discord.ui.View):
    def __init__(self, player: discord.User):
        super().__init__(timeout=GAME_TIMEOUT_SECONDS)
        self.player = player
        self.result: str | None = None

    async def _resolve(self, interaction: discord.Interaction, player_choice: str):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your duel, hands off!", ephemeral=True)
            return

        buggy_choice = random.choice(["rock", "paper", "scissors"])
        outcome = self._judge(player_choice, buggy_choice)

        lines = {
            "win": f"You picked **{player_choice}**, I picked **{buggy_choice}**... "
                   f"YOU WIN?! Impossible! I DEMAND a rematch! 😤",
            "lose": f"You picked **{player_choice}**, I picked **{buggy_choice}**. "
                    f"HAH! Buggy wins again, as EXPECTED! 🤡",
            "tie": f"We both picked **{player_choice}**! A tie?! Even my ties are legendary!",
        }

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=lines[outcome], view=self)
        self.stop()

    @staticmethod
    def _judge(player: str, buggy: str) -> str:
        if player == buggy:
            return "tie"
        beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        return "win" if beats[player] == buggy else "lose"

    @discord.ui.button(label="Rock", emoji="🪨", style=discord.ButtonStyle.secondary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "rock")

    @discord.ui.button(label="Paper", emoji="📄", style=discord.ButtonStyle.secondary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "paper")

    @discord.ui.button(label="Scissors", emoji="✂️", style=discord.ButtonStyle.secondary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, "scissors")


class TriviaView(discord.ui.View):
    def __init__(self, bot, guild_id: int | None, question: dict):
        super().__init__(timeout=GAME_TIMEOUT_SECONDS)
        self.bot = bot
        self.guild_id = guild_id
        self.question = question
        self.answered = False

        for i, choice in enumerate(question["choices"]):
            self.add_item(self._make_button(i, choice))

    def _make_button(self, index: int, label: str) -> discord.ui.Button:
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)

        async def callback(interaction: discord.Interaction):
            if self.answered:
                await interaction.response.send_message("Too slow - someone already answered!", ephemeral=True)
                return

            correct = index == self.question["correct"]
            if correct:
                self.answered = True
                for child in self.children:
                    child.disabled = True
                text = (
                    f"🎉 {interaction.user.display_name} got it right! The answer was "
                    f"**{self.question['choices'][self.question['correct']]}**. "
                    f"Of course, Buggy definitely knew that too."
                )
                await interaction.response.edit_message(content=text, view=self)

                if self.guild_id:
                    _, new_rank, promoted = await self.bot.memory.add_crew_points(
                        interaction.user.id, self.guild_id, 3
                    )
                    if promoted:
                        await interaction.followup.send(
                            f"🏴‍☠️ {interaction.user.mention} was promoted to **{new_rank}**!"
                        )
                self.stop()
            else:
                await interaction.response.send_message(
                    f"Nope, **{label}** isn't it. Try again... if you dare.", ephemeral=True
                )

        button.callback = callback
        return button

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class ChallengeView(discord.ui.View):
    """A single-message duel/dice-duel display - resolves instantly
    but shown as a themed view for presentation."""

    def __init__(self):
        super().__init__(timeout=1)


class GuessGame:
    def __init__(self, target: int, max_number: int, started_by: int):
        self.target = target
        self.max_number = max_number
        self.started_by = started_by
        self.attempts = 0
        self.created_at = time.monotonic()


class GamesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_guess_games: dict[int, GuessGame] = {}
        self.active_riddles: dict[int, tuple[str, float]] = {}  # channel_id -> (answer, expires_at)

    # -- Coin flip ----------------------------------------------------------

    @app_commands.command(name="coinflip", description="Flip a coin, Buggy-style.")
    async def coinflip(self, interaction: discord.Interaction):
        result = random.choice(["Heads", "Tails"])
        flavor = random.choice([
            "of course it landed exactly how I predicted!",
            "the coin trembled before the GREATNESS of this moment.",
            "I definitely didn't rig that. Definitely.",
        ])
        await interaction.response.send_message(f"🪙 **{result}!** ...{flavor}")

    # -- Dice duel ------------------------------------------------------------

    @app_commands.command(name="diceduel", description="Roll dice against another pirate.")
    @app_commands.describe(opponent="Who are you challenging?")
    async def diceduel(self, interaction: discord.Interaction, opponent: discord.Member):
        if opponent.bot:
            await interaction.response.send_message("You can't duel a bot, genius. Pick a real crewmate.", ephemeral=True)
            return
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("Dueling yourself? Bold, but no.", ephemeral=True)
            return

        challenger_roll = random.randint(1, 6)
        opponent_roll = random.randint(1, 6)

        if challenger_roll == opponent_roll:
            outcome = "A TIE?! Even the dice fear picking a winner against my crew!"
        elif challenger_roll > opponent_roll:
            outcome = f"{interaction.user.display_name} wins! (Buggy watched and takes partial credit.)"
        else:
            outcome = f"{opponent.display_name} wins! An UPSET! Buggy demands a recount!"

        await interaction.response.send_message(
            f"🎲 **Dice Duel!** {interaction.user.display_name} rolled **{challenger_roll}**, "
            f"{opponent.display_name} rolled **{opponent_roll}**.\n{outcome}"
        )

        if interaction.guild:
            winner = interaction.user if challenger_roll >= opponent_roll else opponent
            await self.bot.memory.add_crew_points(winner.id, interaction.guild.id, 2)

    # -- Pirate duel ------------------------------------------------------------

    @app_commands.command(name="duel", description="Challenge another pirate to a dramatic duel.")
    @app_commands.describe(opponent="Who are you challenging?")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member):
        if opponent.bot:
            await interaction.response.send_message("Bots don't duel. Try a real pirate.", ephemeral=True)
            return
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("You can't duel yourself. Well, I mean, YOU could try.", ephemeral=True)
            return

        winner = random.choice([interaction.user, opponent])
        loser = opponent if winner.id == interaction.user.id else interaction.user

        flavor = random.choice([
            f"⚔️ In a CLASH worthy of legend, {winner.display_name} defeats {loser.display_name}! "
            f"Buggy watched from a safe distance, obviously as the referee.",
            f"⚔️ {winner.display_name} strikes true! {loser.display_name} goes down dramatically. "
            f"Buggy declares it 'the greatest duel he's ever almost participated in.'",
            f"⚔️ Chaos erupts! When the dust settles, {winner.display_name} is left standing over "
            f"{loser.display_name}. Buggy takes full credit for training them.",
        ])
        await interaction.response.send_message(flavor)

        if interaction.guild:
            await self.bot.memory.add_crew_points(winner.id, interaction.guild.id, 2)

    # -- Rock Paper Scissors ----------------------------------------------------

    @app_commands.command(name="rps", description="Rock, Paper, Scissors against Buggy himself.")
    async def rps(self, interaction: discord.Interaction):
        view = RPSView(interaction.user)
        await interaction.response.send_message(
            "Pick your weapon, coward! Er - I mean, worthy challenger!", view=view
        )

    # -- Trivia -----------------------------------------------------------------

    @app_commands.command(name="trivia", description="One Piece trivia - first correct answer wins.")
    async def trivia(self, interaction: discord.Interaction):
        question = random.choice(TRIVIA_BANK)
        guild_id = interaction.guild.id if interaction.guild else None
        view = TriviaView(self.bot, guild_id, question)
        await interaction.response.send_message(f"❓ **{question['question']}**", view=view)

    # -- Guess the number ---------------------------------------------------------

    guess_group = app_commands.Group(name="guess", description="Guess the number Buggy is thinking of.")

    @guess_group.command(name="start", description="Start a number-guessing game in this channel.")
    @app_commands.describe(max_number="Upper bound of the range (default 100).")
    async def guess_start(self, interaction: discord.Interaction, max_number: app_commands.Range[int, 10, 1000] = 100):
        channel_id = interaction.channel_id
        if channel_id in self.active_guess_games:
            await interaction.response.send_message(
                "There's already a guessing game running here! Use `/guess number` to play.", ephemeral=True
            )
            return

        target = random.randint(1, max_number)
        self.active_guess_games[channel_id] = GuessGame(target, max_number, interaction.user.id)
        await interaction.response.send_message(
            f"🎯 Buggy is thinking of a number between **1** and **{max_number}**! "
            f"Use `/guess number` to guess. Whoever gets it first is TEMPORARILY worthy of respect."
        )

    @guess_group.command(name="number", description="Submit a guess for the active number-guessing game.")
    async def guess_number(self, interaction: discord.Interaction, number: int):
        channel_id = interaction.channel_id
        game = self.active_guess_games.get(channel_id)
        if not game:
            await interaction.response.send_message(
                "No game running here - start one with `/guess start` first!", ephemeral=True
            )
            return

        game.attempts += 1
        if number == game.target:
            del self.active_guess_games[channel_id]
            await interaction.response.send_message(
                f"🎯 **{interaction.user.display_name} GUESSED IT!** The number was **{game.target}**! "
                f"Buggy is impressed, which is rare and you should feel honored."
            )
            if interaction.guild:
                await self.bot.memory.add_crew_points(interaction.user.id, interaction.guild.id, 3)
        elif number < game.target:
            await interaction.response.send_message("Higher! Buggy's number is bigger than that.", ephemeral=True)
        else:
            await interaction.response.send_message("Lower! Not even close, honestly.", ephemeral=True)

    # -- Emoji guessing -----------------------------------------------------------

    @app_commands.command(name="emojiguess", description="Guess the phrase from Buggy's emoji riddle.")
    async def emojiguess(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id in self.active_riddles:
            await interaction.response.send_message(
                "There's already a riddle active here - answer it in chat first!", ephemeral=True
            )
            return

        emoji_str, answer = random.choice(EMOJI_RIDDLES)
        self.active_riddles[channel_id] = (answer, time.monotonic() + 60)
        await interaction.response.send_message(
            f"🧩 Guess what this means: {emoji_str}\n"
            f"Just type your answer in chat - no command needed. You have 60 seconds!"
        )

    def check_riddle_answer(self, channel_id: int, content: str) -> bool:
        """Called from events.py before AI dispatch. Returns True if
        this message resolved an active riddle (caller should not
        forward the message to Gemini in that case)."""
        entry = self.active_riddles.get(channel_id)
        if not entry:
            return False
        answer, expires_at = entry
        if time.monotonic() > expires_at:
            del self.active_riddles[channel_id]
            return False
        normalized = content.strip().lower().replace(" ", "")
        if normalized == answer:
            del self.active_riddles[channel_id]
            return True
        return False

    # -- Crew ---------------------------------------------------------------------

    @app_commands.command(name="joincrew", description="Join Buggy's crew!")
    async def joincrew(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Join my crew from inside an actual server, not a DM.", ephemeral=True)
            return

        joined = await self.bot.memory.join_crew(interaction.user.id, interaction.guild.id)
        if joined:
            await interaction.response.send_message(
                f"🏴‍☠️ Welcome aboard, {interaction.user.display_name}! You start as a **Cabin Boy**. "
                f"Try not to embarrass me."
            )
        else:
            await interaction.response.send_message("You're already part of my crew! Did you forget? Rude.", ephemeral=True)

    @app_commands.command(name="crew", description="Check your rank in Buggy's crew.")
    async def crew_status(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Crew ranks only exist inside a server.", ephemeral=True)
            return

        status = await self.bot.memory.crew_status(interaction.user.id, interaction.guild.id)
        if not status:
            await interaction.response.send_message(
                "You haven't joined my crew yet! Use `/joincrew` to sign up.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"🏴‍☠️ **{interaction.user.display_name}**\n"
            f"Rank: **{status['rank']}**\n"
            f"Points: **{status['points']}**"
        )

    # -- Treasure -------------------------------------------------------------------

    @app_commands.command(name="treasure", description="See what treasure you've found so far.")
    async def treasure(self, interaction: discord.Interaction):
        items = await self.bot.memory.treasure_list(interaction.user.id)
        if not items:
            await interaction.response.send_message(
                "You haven't found any treasure yet. Keep chatting - Buggy's watching. (He's not really watching.)",
                ephemeral=True,
            )
            return
        lines = [f"- {row['item_name']}" for row in items]
        await interaction.response.send_message(
            "💰 **Your Treasure Chest** (Buggy insists it's technically all his):\n" + "\n".join(lines),
            ephemeral=True,
        )


async def maybe_award_treasure(bot, user_id: int, guild_id: int | None, chance: float = 0.02) -> str | None:
    """Deterministic passive treasure roll called from events.py on
    ordinary chat messages. Returns a flavor line if treasure was
    found, else None. No Gemini call involved."""
    if random.random() > chance:
        return None
    item = random.choice(TREASURE_ITEMS)
    await bot.memory.award_treasure(user_id, guild_id, item)
    return _reward_flavor(item)


async def setup_games(bot) -> None:
    await bot.add_cog(GamesCog(bot))
