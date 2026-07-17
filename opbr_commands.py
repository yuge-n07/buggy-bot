"""
opbr_commands.py
----------------
The /medalset command – trait-driven set optimizer (no tags).
The /medal command – medal autocomplete with character name + emoji.
The /add command – add a new character to the dataset (admin only).
Now includes an "Export Image" button that uses Node.js + Puppeteer,
and a "Export (Transparent)" button using Pillow.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from pathlib import Path
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from opbr import MedalSetResult, SOURCE_URL, TRAIT_NAMES, AFFECT_TYPE_TO_TRAIT, get_opbr_data, DATA_PATH, _opbr_data

logger = logging.getLogger("buggy.opbr_commands")

EMBED_COLOR = 0xCC9D50
RESULT_VIEW_TIMEOUT = 300

TraitLiteral = Literal[tuple(TRAIT_NAMES)]  # type: ignore[valid-type]


def _build_embeds(result: MedalSetResult) -> list[discord.Embed]:
    summary_lines = [
        f"**Required traits:** {', '.join(result.trait_names)}",
    ]
    trio_bonuses = [b for b in result.tag_bonuses if b.kind == "trio"]
    pair_bonuses = [b for b in result.tag_bonuses if b.kind == "pair"]

    if trio_bonuses:
        summary_lines.append("**Trio bonuses (all 3 medals share a tag):**")
        for b in trio_bonuses:
            summary_lines.append(f"🔺 **{b.tag_name}** - {b.detail}")
    if pair_bonuses:
        summary_lines.append("**Pair bonuses (2 medals share a tag):**")
        for b in pair_bonuses:
            summary_lines.append(f"🔹 **{b.tag_name}** - {b.detail}")
    if not trio_bonuses and not pair_bonuses:
        summary_lines.append("No tag synergy triggers with this combo.")

    summary = discord.Embed(
        title="🏅 Best Medal Set",
        description="\n".join(summary_lines),
        color=EMBED_COLOR,
    )
    summary.add_field(name="Score", value=f"{result.score:.1f}", inline=False)

    medal_embeds = []
    for i, medal in enumerate(result.medals):
        embed = discord.Embed(
            title=f"{medal.name}  (covers: {result.trait_names[i]})",
            description=medal.unique_trait or "*(no unique trait listed)*",
            color=EMBED_COLOR,
        )
        embed.set_thumbnail(url=medal.icon_url)
        medal_embeds.append(embed)

    return [summary, *medal_embeds]


class SearchSession:
    def __init__(self, user_id: int, trait_conditions: list[tuple[str, int | None, int | None]],
                 result: MedalSetResult, fixed_medal_id: int | None = None):
        self.user_id = user_id
        self.trait_conditions = trait_conditions
        self.result = result
        self.fixed_medal_id = fixed_medal_id
        self.excluded_ids: set[int] = set()


class MedalResultView(discord.ui.View):
    def __init__(self, session: SearchSession):
        super().__init__(timeout=RESULT_VIEW_TIMEOUT)
        self.session = session

        for i, medal in enumerate(session.result.medals):
            if session.fixed_medal_id is not None and medal.medal_id == session.fixed_medal_id:
                continue
            button = discord.ui.Button(
                label=f"Change Medal {i+1}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"change_{i}",
            )
            button.callback = self._make_callback(i)
            self.add_item(button)

        # Export button (Puppeteer)
        self.export_button = discord.ui.Button(
            label="📸 Export Image",
            style=discord.ButtonStyle.success,
            custom_id="export_image",
        )
        self.export_button.callback = self._export_callback
        self.add_item(self.export_button)

        # Transparent export button (Pillow)
        self.custom_export = discord.ui.Button(
            label="📸 Export (Transparent)",
            style=discord.ButtonStyle.primary,
            custom_id="export_custom",
        )
        self.custom_export.callback = self._export_custom_callback
        self.add_item(self.custom_export)

    def _make_callback(self, slot_index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.session.user_id:
                await interaction.response.send_message("This isn't your search - run /medals yourself!", ephemeral=True)
                return

            await interaction.response.defer()

            session = self.session
            session.excluded_ids.add(session.result.medals[slot_index].medal_id)

            data = get_opbr_data()
            fixed_medals = [data.medals_by_id[m.medal_id] for m in session.result.medals]
            result = data.find_replacement(
                session.trait_conditions, slot_index, fixed_medals,
                exclude_ids=session.excluded_ids,
            )

            if isinstance(result, str):
                await interaction.edit_original_response(
                    content=f"Bah! {result} No more alternatives for that slot.", embeds=[], view=None
                )
                return

            session.result = result
            embeds = _build_embeds(result)
            new_view = MedalResultView(session)
            await interaction.edit_original_response(content="Here's the updated set:", embeds=embeds, view=new_view)

        return callback

    async def _export_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message("This isn't your search - run /medals yourself!", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            medal_ids = [m.medal_id for m in self.session.result.medals]
            script_path = Path(__file__).parent / "capture_medal_set.js"
            medal_ids_json = json.dumps(medal_ids)

            process = await asyncio.create_subprocess_exec(
                "node", str(script_path), medal_ids_json,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"Node script failed: {stderr.decode()}")
                await interaction.followup.send("❌ Failed to generate image. Check logs.", ephemeral=True)
                return

            output_path = stdout.decode().strip()
            if not output_path or not Path(output_path).exists():
                await interaction.followup.send("❌ Image not generated.", ephemeral=True)
                return

            file = discord.File(output_path, filename="medal_set.png")
            await interaction.followup.send(file=file)

        except Exception as e:
            logger.error(f"Export image error: {e}", exc_info=True)
            await interaction.followup.send("❌ Failed to generate image. Check logs.", ephemeral=True)

    async def _export_custom_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.session.user_id:
            await interaction.response.send_message("This isn't your search - run /medals yourself!", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            from medal_image import generate_medal_set_image
            data = get_opbr_data()
            tag_map = {int(tid): t["name"] for tid, t in data.tags.items()}
            # generate_medal_set_image does blocking network calls (icon
            # downloads via requests) - run it off the event loop so it
            # doesn't freeze the whole bot for other users while it works.
            img = await asyncio.to_thread(generate_medal_set_image, self.session.result, tag_map)
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            file = discord.File(buffer, filename="medal_set_transparent.png")
            await interaction.followup.send(file=file)
        except Exception as e:
            logger.error(f"Custom export error: {e}", exc_info=True)
            await interaction.followup.send("❌ Failed to generate image.", ephemeral=True)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ---------- Build view with prefixed unique values and truncation ----------
class BuildView(discord.ui.View):
    def __init__(self, user_id: int, medal_name: str, fixed_medal_id: int,
                 default_trait: str, default_condition: str, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.medal_name = medal_name
        self.fixed_medal_id = fixed_medal_id
        self.default_trait = default_trait if default_trait else "Any"
        self.default_condition = default_condition if default_condition else "Any Condition"

        self.trait2_value = "Any"
        self.cond2_value = "Any Condition"
        self.trait3_value = "Any"
        self.cond3_value = "Any Condition"

        data = get_opbr_data()
        all_conditions = self._get_unique_conditions(data)

        # Trait2 dropdown
        trait2_options = ["Any"] + [t for t in TRAIT_NAMES if t != "Any"]
        self.trait2_select = discord.ui.Select(
            placeholder="Trait 2 (optional)",
            options=[discord.SelectOption(label=opt, value=opt) for opt in trait2_options[:25]],
            min_values=1, max_values=1,
        )
        self.trait2_select.callback = self._trait2_callback
        self.add_item(self.trait2_select)

        # Condition2 dropdown (prefix values with "c2_")
        self.cond2_select = self._make_condition_select("Condition 2", all_conditions, "c2")
        self.add_item(self.cond2_select)

        # Trait3 dropdown
        trait3_options = ["Any"] + [t for t in TRAIT_NAMES if t != "Any"]
        self.trait3_select = discord.ui.Select(
            placeholder="Trait 3 (optional)",
            options=[discord.SelectOption(label=opt, value=opt) for opt in trait3_options[:25]],
            min_values=1, max_values=1,
        )
        self.trait3_select.callback = self._trait3_callback
        self.add_item(self.trait3_select)

        # Condition3 dropdown (prefix values with "c3_")
        self.cond3_select = self._make_condition_select("Condition 3", all_conditions, "c3")
        self.add_item(self.cond3_select)

        # Build button
        self.build_button = discord.ui.Button(label="🏗️ Build Set", style=discord.ButtonStyle.success)
        self.build_button.callback = self._build_callback
        self.add_item(self.build_button)

    def _get_unique_conditions(self, data) -> list[str]:
        all_conds = ["Any Condition"] + data.get_condition_options()
        seen = set()
        unique = []
        for c in all_conds:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def _make_condition_select(self, placeholder: str, options: list[str], prefix: str) -> discord.ui.Select:
        truncated = []
        for opt in options[:25]:
            label = opt[:97] + "…" if len(opt) > 100 else opt
            raw_value = f"{prefix}_{opt}"
            value = raw_value[:100]
            truncated.append((label, value))
        select = discord.ui.Select(
            placeholder=placeholder,
            options=[discord.SelectOption(label=label, value=value) for label, value in truncated],
            min_values=1, max_values=1,
        )
        return select

    def _update_condition_select(self, select: discord.ui.Select, trait_value: str, prefix: str):
        try:
            data = get_opbr_data()
            if trait_value == "Any":
                options = self._get_unique_conditions(data)
            else:
                conds = ["Any Condition"] + data.get_conditions_for_trait(trait_value)
                seen = set()
                unique = []
                for c in conds:
                    if c not in seen:
                        seen.add(c)
                        unique.append(c)
                options = unique

            truncated = []
            for opt in options[:25]:
                label = opt[:97] + "…" if len(opt) > 100 else opt
                raw_value = f"{prefix}_{opt}"
                value = raw_value[:100]
                truncated.append((label, value))

            select.options = [discord.SelectOption(label=label, value=value) for label, value in truncated]
        except Exception as e:
            logger.error("Error updating condition select: %s", e, exc_info=True)

    async def _trait2_callback(self, interaction: discord.Interaction):
        try:
            self.trait2_value = interaction.data["values"][0]
            self._update_condition_select(self.cond2_select, self.trait2_value, "c2")
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error("Trait2 callback error: %s", e, exc_info=True)
            await interaction.response.send_message("Something went wrong updating the condition dropdown.", ephemeral=True)

    async def _cond2_callback(self, interaction: discord.Interaction):
        try:
            raw = interaction.data["values"][0]
            if raw.startswith("c2_"):
                self.cond2_value = raw[3:]
            else:
                self.cond2_value = raw
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error("Cond2 callback error: %s", e, exc_info=True)

    async def _trait3_callback(self, interaction: discord.Interaction):
        try:
            self.trait3_value = interaction.data["values"][0]
            self._update_condition_select(self.cond3_select, self.trait3_value, "c3")
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error("Trait3 callback error: %s", e, exc_info=True)
            await interaction.response.send_message("Something went wrong updating the condition dropdown.", ephemeral=True)

    async def _cond3_callback(self, interaction: discord.Interaction):
        try:
            raw = interaction.data["values"][0]
            if raw.startswith("c3_"):
                self.cond3_value = raw[3:]
            else:
                self.cond3_value = raw
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error("Cond3 callback error: %s", e, exc_info=True)

    async def _build_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your search - run /medals yourself!", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        data = get_opbr_data()

        t2 = self.trait2_value if self.trait2_value != "Any" else None
        c2 = self.cond2_value if self.cond2_value != "Any Condition" else None
        t3 = self.trait3_value if self.trait3_value != "Any" else None
        c3 = self.cond3_value if self.cond3_value != "Any Condition" else None

        result = data.resolve_traits(
            self.default_trait, self.default_condition,
            t2, c2,
            t3, c3,
        )
        if isinstance(result, str):
            await interaction.followup.send(f"❌ {result}", ephemeral=True)
            return
        trait_conditions = result

        result = data.find_best_set(
            trait_conditions,
            fixed_medal_id=self.fixed_medal_id,
        )

        if isinstance(result, str):
            await interaction.followup.send(f"❌ {result}", ephemeral=True)
            return

        session = SearchSession(interaction.user.id, trait_conditions, result, fixed_medal_id=self.fixed_medal_id)
        embeds = _build_embeds(result)
        intro = f"Even *I*, the great Buggy, respect good medal-fu. Here's the best setup I could dig up with **{self.medal_name}** fixed:"
        await interaction.followup.send(content=intro, embeds=embeds, view=MedalResultView(session))

    def get_embed(self) -> discord.Embed:
        data = get_opbr_data()
        medal = data.medals_by_id.get(self.fixed_medal_id)
        if not medal:
            return discord.Embed(title="Error", description="Fixed medal not found.")

        embed = discord.Embed(
            title=f"Building Set Around: {medal['name']}",
            description=(
                f"**Trait 1 (fixed):** {self.default_trait}\n"
                f"**Condition 1 (fixed):** {self.default_condition}\n\n"
                f"**Trait 2 (selected):** {self.trait2_value}\n"
                f"**Condition 2:** {self.cond2_value}\n\n"
                f"**Trait 3 (selected):** {self.trait3_value}\n"
                f"**Condition 3:** {self.cond3_value}\n\n"
                "Adjust the dropdowns above, then click **Build Set**."
            ),
            color=EMBED_COLOR,
        )
        embed.set_thumbnail(url=data.medal_icon_url(medal))
        return embed


class OPBRCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._load_error: str | None = None
        try:
            get_opbr_data()
        except Exception as exc:
            self._load_error = str(exc)
            logger.error("OPBR dataset failed to load: %s", exc, exc_info=True)

    # Autocomplete for conditions (used in /medalset)
    async def condition_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        try:
            if self._load_error:
                return [app_commands.Choice(name="Any Condition", value="Any Condition")]

            options_data = interaction.data.get("options", [])
            focused_param = None
            values = {}

            for opt in options_data:
                name = opt.get("name")
                value = opt.get("value")
                if opt.get("focused"):
                    focused_param = name
                if name and value is not None:
                    values[name] = value

            trait_name = "Any"
            if focused_param == "condition1":
                trait_name = values.get("trait1", "Any")
            elif focused_param == "condition2":
                trait_name = values.get("trait2", "Any")
            elif focused_param == "condition3":
                trait_name = values.get("trait3", "Any")
            else:
                trait_name = values.get("trait1", "Any")

            data = get_opbr_data()
            if hasattr(data, "get_conditions_for_trait"):
                options = data.get_conditions_for_trait(trait_name)
            else:
                options = data.get_condition_options()

            if not options:
                options = ["Any Condition"]

            seen = set()
            unique_options = []
            for opt in options:
                if opt not in seen:
                    seen.add(opt)
                    unique_options.append(opt)

            if not current:
                filtered = unique_options[:25]
            else:
                filtered = [opt for opt in unique_options if current.lower() in opt.lower()]
                if not filtered:
                    filtered = ["Any Condition"] if "Any Condition" in unique_options else unique_options[:5]

            choices = []
            for opt in filtered[:25]:
                if not opt or not isinstance(opt, str):
                    continue
                name = opt[:97] + "..." if len(opt) > 100 else opt
                value = opt[:100]
                choices.append(app_commands.Choice(name=name, value=value))

            if not choices:
                choices = [app_commands.Choice(name="Any Condition", value="Any Condition")]

            return choices

        except Exception as exc:
            logger.error("Condition autocomplete error: %s", exc, exc_info=True)
            return [app_commands.Choice(name="Any Condition", value="Any Condition")]

    async def medal_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        try:
            if self._load_error:
                return []

            data = get_opbr_data()
            current_lower = current.strip().lower()

            medal_to_char = {}
            for char in data.characters:
                char_name = char.get("name", "")
                for mid in char.get("medal_ids", []):
                    if mid not in medal_to_char:
                        medal_to_char[mid] = char_name

            matches = []
            for medal in data.all_medals:
                mid = medal.get("medal_id")
                name = medal.get("name", "")
                if not mid or not name:
                    continue
                char_name = medal_to_char.get(mid, "Unknown")
                is_event = medal.get("is_event", False)
                emoji = "🔮" if is_event else "🏅"
                display_name = f"{char_name}: {name} {emoji}"
                if not current_lower or current_lower in display_name.lower():
                    if len(display_name) > 100:
                        display_name = display_name[:97] + "..."
                    matches.append((display_name, str(mid)))
                    if len(matches) >= 25:
                        break

            matches.sort(key=lambda x: x[0])
            return [app_commands.Choice(name=dn, value=mid_str) for dn, mid_str in matches]

        except Exception as exc:
            logger.error("Medal autocomplete error: %s", exc, exc_info=True)
            return []

    # ---------- /medalset command ----------
    @app_commands.command(
        name="medalset",
        description="Best OPBR medal set for 3 traits (trait1+cond1 required) + optional trait2/cond2 & trait3/cond3."
    )
    @app_commands.describe(
        trait1="Required trait 1",
        condition1="Condition for trait 1 (required)",
        trait2="Optional trait 2",
        condition2="Condition for trait 2 (optional, only if trait2 provided)",
        trait3="Optional trait 3",
        condition3="Condition for trait 3 (optional, only if trait3 provided)",
    )
    @app_commands.autocomplete(
        condition1=condition_autocomplete,
        condition2=condition_autocomplete,
        condition3=condition_autocomplete,
    )
    async def medalset(
        self,
        interaction: discord.Interaction,
        trait1: TraitLiteral,
        condition1: str,
        trait2: Optional[TraitLiteral] = None,
        condition2: Optional[str] = None,
        trait3: Optional[TraitLiteral] = None,
        condition3: Optional[str] = None,
    ):
        if self._load_error:
            await interaction.response.send_message(
                f"My medal database didn't load properly: {self._load_error}. Poke my owner about it. 🤡",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        data = get_opbr_data()

        traits_or_error = data.resolve_traits(
            trait1, condition1,
            trait2, condition2,
            trait3, condition3,
        )
        if isinstance(traits_or_error, str):
            await interaction.followup.send(f"Bah! {traits_or_error}", ephemeral=True)
            return
        trait_conditions = traits_or_error

        result = data.find_best_set(trait_conditions)

        if isinstance(result, str):
            await interaction.followup.send(f"Bah! {result}", ephemeral=True)
            return

        session = SearchSession(interaction.user.id, trait_conditions, result)
        embeds = _build_embeds(result)
        intro = "Even *I*, the great Buggy, respect good medal-fu. Here's the best setup I could dig up:"
        await interaction.followup.send(content=intro, embeds=embeds, view=MedalResultView(session))

    # ---------- /medal command ----------
    @app_commands.command(name="medal", description="Pick a medal, then build a set around it.")
    @app_commands.describe(medal="Medal name (autocomplete with character and emoji)")
    @app_commands.autocomplete(medal=medal_autocomplete)
    async def medal(self, interaction: discord.Interaction, medal: str):
        if self._load_error:
            await interaction.response.send_message(
                f"My medal database didn't load properly: {self._load_error}. Poke my owner about it. 🤡",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        data = get_opbr_data()

        try:
            medal_id = int(medal)
        except ValueError:
            await interaction.followup.send(f"❌ Invalid medal selection.", ephemeral=True)
            return

        matched_medal = data.medals_by_id.get(medal_id)
        if not matched_medal:
            await interaction.followup.send(f"❌ Could not find a medal with ID {medal_id}.", ephemeral=True)
            return

        medal_name = matched_medal["name"]

        default_trait = ""
        default_condition = "Any Condition"
        ability_id = matched_medal.get("ability_id")
        if ability_id:
            ability = data.abilities.get(str(ability_id))
            if ability:
                affect_type = ability.get("affect_type")
                trait_name = AFFECT_TYPE_TO_TRAIT.get(affect_type, "")
                default_trait = trait_name if trait_name else "Any"
                cond_type = ability.get("cond_type")
                for (atype, ctype), name in data._cond_map.items():
                    if atype == affect_type and ctype == cond_type:
                        default_condition = name
                        break
                if not default_condition:
                    default_condition = "Any Condition"

        build_view = BuildView(interaction.user.id, medal_name, medal_id, default_trait, default_condition)
        embed = build_view.get_embed()
        await interaction.followup.send(
            content=f"Building set around **{medal_name}**. Choose your additional traits:",
            embed=embed,
            view=build_view,
            ephemeral=True,
        )

    # ---------- /add command (admin only) ----------
    @app_commands.command(name="add", description="[Admin] Add a new character to the dataset.")
    @app_commands.describe(
        name="Character name (e.g., St. Ethanbaron V. Nusjuro)",
        aliases="Comma-separated aliases (e.g., nusjuro, ethanbaron)",
        medal_ids="Comma-separated medal IDs (e.g., 310110348, 310110347)",
    )
    @app_commands.default_permissions(administrator=True)
    async def add_character(
        self,
        interaction: discord.Interaction,
        name: str,
        aliases: str,
        medal_ids: str,
    ):
        if self._load_error:
            await interaction.response.send_message(
                f"My medal database didn't load properly: {self._load_error}. Poke my owner about it. 🤡",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        medal_id_list = []
        for part in medal_ids.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                mid = int(part)
                medal_id_list.append(mid)
            except ValueError:
                await interaction.followup.send(f"❌ `{part}` is not a valid medal ID.", ephemeral=True)
                return

        if not medal_id_list:
            await interaction.followup.send("❌ At least one medal ID is required.", ephemeral=True)
            return

        data = get_opbr_data()
        missing = []
        for mid in medal_id_list:
            if mid not in data.medals_by_id:
                missing.append(str(mid))
        if missing:
            await interaction.followup.send(f"❌ Medal IDs not found: {', '.join(missing)}. Please check and try again.", ephemeral=True)
            return

        alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
        if name.lower() not in [a.lower() for a in alias_list]:
            alias_list.append(name)

        existing = any(c.get("name", "").lower() == name.lower() for c in data.characters)
        if existing:
            await interaction.followup.send(f"❌ Character **{name}** already exists in the dataset.", ephemeral=True)
            return

        max_id = max((c.get("person_id", 0) for c in data.characters), default=0)
        new_id = max_id + 1

        new_char = {
            "person_id": new_id,
            "name": name,
            "aliases": alias_list,
            "medal_ids": medal_id_list,
        }

        data.characters.append(new_char)

        try:
            with open(DATA_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "medals": list(data.medals_by_id.values()),
                    "tags": data.tags,
                    "abilities": data.abilities,
                    "characters": data.characters,
                }, f, separators=(",", ":"), ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save dataset: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Failed to save dataset: {e}", ephemeral=True)
            return

        global _opbr_data
        _opbr_data = None

        await interaction.followup.send(
            f"✅ Character **{name}** (person_id: {new_id}) added with {len(medal_id_list)} medal(s) and {len(alias_list)} alias(es).\n"
            f"The dataset has been reloaded.",
            ephemeral=True,
        )


async def setup_opbr(bot) -> None:
    await bot.add_cog(OPBRCommands(bot))