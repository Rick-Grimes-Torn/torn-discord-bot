from typing import List
import discord
from discord import app_commands

from ..utils import chunk_lines


def register(tree: app_commands.CommandTree):
    def _command_help_lines() -> List[str]:
        cmds = list(tree.get_commands())
        cmds.sort(key=lambda c: (c.name or "").lower())

        lines: List[str] = []
        for c in cmds:
            name = f"/{c.name}"
            desc = (c.description or "").strip() or "No description."
            lines.append(f"- **{name}** — {desc}")
        return lines

    @tree.command(name="help", description="Show available bot commands.")
    async def help_cmd(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            lines = _command_help_lines()
            if not lines:
                await interaction.followup.send("No commands found.")
                return

            header = "📜 **Available commands:**\n"
            for msg in chunk_lines(header, lines):
                await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send("⚠️ Error while building help list.")
            print("Error in /help:", repr(e))
