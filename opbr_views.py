"""
opbr_views.py
-------------
Discord UI components for the /medals command.
"""

from __future__ import annotations

import logging

import discord

from opbr import get_opbr_data, MedalSetResult

logger = logging.getLogger("buggy.opbr_views")


class MedalSetView(discord.ui.View):
    def __init__(
        self,
        result: MedalSetResult,
        traits: list[str],
        tag_traits: list[str],
        timeout: float = 180.0,
    ):
        super().__init__(timeout=timeout)
        self.result = result
        self.traits = traits
        self.tag_traits = tag_traits
        self.medals = result.medals

    @discord.ui.button(label="❌ I don't have this medal", style=discord.ButtonStyle.danger)
    async def missing_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        options = [
            discord.SelectOption(
                label=f"Medal {i+1}: {m.name}",
                value=str(i),
                description=m.unique_trait[:50] if m.unique_trait else "No trait",
            )
            for i, m in enumerate(self.medals)
        ]
        select = discord.ui.Select(
            placeholder="Choose the medal you don't have",
            options=options,
            custom_id="missing_select",
        )
        select.callback = self._missing_select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message(
            "Which medal are you missing?", view=view, ephemeral=True
        )

    async def _missing_select_callback(self, interaction: discord.Interaction):
        selected_value = interaction.data["values"][0]
        replace_idx = int(selected_value)

        data = get_opbr_data()
        new_medal = data.find_replacement(
            self.medals,
            replace_idx,
            self.traits,
            self.tag_traits,
        )

        if not new_medal:
            await interaction.response.send_message(
                "❌ No suitable replacement found. Try different traits or tag traits.",
                ephemeral=True,
            )
            return

        self.medals[replace_idx] = new_medal
        new_result = MedalSetResult(
            medals=self.medals,
            traits=self.traits,
            tag_traits=self.tag_traits,
            score=0,
        )
        data._compute_bonuses(new_result)

        from opbr_commands import _build_embeds
        embeds = _build_embeds(new_result)
        await interaction.response.edit_message(embeds=embeds, view=self)
        await interaction.delete_original_response()

    @discord.ui.button(label="🔄 Change this medal", style=discord.ButtonStyle.primary)
    async def change_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        options = [
            discord.SelectOption(
                label=f"Medal {i+1}: {m.name}",
                value=str(i),
                description=m.unique_trait[:50] if m.unique_trait else "No trait",
            )
            for i, m in enumerate(self.medals)
        ]
        select = discord.ui.Select(
            placeholder="Choose which medal to change",
            options=options,
            custom_id="change_select",
        )
        select.callback = self._change_select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message(
            "Which medal would you like to change?", view=view, ephemeral=True
        )

    async def _change_select_callback(self, interaction: discord.Interaction):
        selected_value = interaction.data["values"][0]
        replace_idx = int(selected_value)

        data = get_opbr_data()
        new_medal = data.find_replacement(
            self.medals,
            replace_idx,
            self.traits,
            self.tag_traits,
        )

        if not new_medal:
            await interaction.response.send_message(
                "❌ No alternative replacement found. Try different traits or tag traits.",
                ephemeral=True,
            )
            return

        self.medals[replace_idx] = new_medal
        new_result = MedalSetResult(
            medals=self.medals,
            traits=self.traits,
            tag_traits=self.tag_traits,
            score=0,
        )
        data._compute_bonuses(new_result)

        from opbr_commands import _build_embeds
        embeds = _build_embeds(new_result)
        await interaction.response.edit_message(embeds=embeds, view=self)
        await interaction.delete_original_response()