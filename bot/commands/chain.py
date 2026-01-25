import discord
from discord import app_commands

from ..chain_watcher import is_chain_controller
from .. import db
from .. import torn_api
from ..db import chain_optin_clear_guild


def _fmt_user(user_id: int | None) -> str:
    return f"<@{user_id}>" if user_id else "Unknown"


def _fmt_channel(guild: discord.Guild, channel_id: int | None) -> str:
    if not channel_id:
        return "Not set"
    ch = guild.get_channel(channel_id)
    return ch.mention if ch else f"(missing) `{channel_id}`"


def register(client: discord.Client, tree: app_commands.CommandTree):
    chain = app_commands.Group(name="chain", description="Chain watcher commands")

    @chain.command(name="start", description="Start watching the faction chain timer (leadership only).")
    async def start(interaction: discord.Interaction):

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Guild-only command.", ephemeral=True)

        if not is_chain_controller(interaction.user):
            return await interaction.response.send_message("Only leadership can use this command.", ephemeral=True)

        # Ensure the bot can actually talk in this channel
        me = interaction.guild.me
        if me and isinstance(interaction.channel, discord.abc.GuildChannel):
            perms = interaction.channel.permissions_for(me)
            if not (perms.view_channel and perms.send_messages):
                return await interaction.response.send_message(
                    "I don't have permission to view/send messages in this channel.",
                    ephemeral=True,
                )

        await client.chain_watcher.start(interaction.guild, interaction.channel, interaction.user.id)
        client.roster_monitor.start()


        # PUBLIC announcement
        snap = client.chain_watcher.get_status_snapshot(interaction.guild.id)
        await interaction.response.send_message(
            f"⛓️ **Chain watcher started** by {interaction.user.mention}\n"
            f"I’ll alert **{snap['ping_role_name']}** members when the chain timer drops to **{snap['alert_seconds']}s** or less."
        )

    @chain.command(name="stop", description="Stop watching the faction chain timer (leadership only).")
    async def stop(interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Guild-only command.", ephemeral=True)

        if not is_chain_controller(interaction.user):
            return await interaction.response.send_message("Only leadership can use this command.", ephemeral=True)

        await client.chain_watcher.stop(interaction.guild.id)
        await client.roster_monitor.stop()


        # Reset /pingme opt-ins for this guild whenever monitoring stops
        cleared = chain_optin_clear_guild(client.db_conn, interaction.guild.id)

        # PUBLIC announcement
        await interaction.response.send_message(
            f"🛑 **Chain watcher stopped** by {interaction.user.mention}\n"
            f"🧹 Cleared **{cleared:,}** `/pingme` opt-ins (re-opt in next time if you want offline pings)."
        )

    @chain.command(name="pingme", description="Opt-in to chain pings even if you're offline (resets on /chain stop).")
    async def pingme(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Guild-only command.", ephemeral=True)

        db.chain_optin_add(client.db_conn, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(
            "✅ You will be pinged when the chain timer is low.\n"
            "ℹ️ This opt-in resets when leadership runs `/chain stop`.",
            ephemeral=True,
        )

    @chain.command(name="list", description="Show who is opted-in to chain pings.")
    async def list_optins(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Guild-only command.",
                ephemeral=True,
            )

        opted_in_ids = db.chain_optin_list(client.db_conn, interaction.guild.id)

        if not opted_in_ids:
            return await interaction.response.send_message(
                "📣 **Chain ping opt-ins:** (none yet)\n"
                "Use `/chain pingme` to opt in."
            )

        mentions = [f"<@{uid}>" for uid in opted_in_ids]

        header = f"📣 **Chain ping opt-ins** ({len(mentions)}):\n"
        messages = []
        current = header

        for m in mentions:
            add = m + " "
            if len(current) + len(add) > 1900:
                messages.append(current.rstrip())
                current = ""
            current += add

        if current.strip():
            messages.append(current.rstrip())

        await interaction.response.send_message(messages[0])
        for extra in messages[1:]:
            await interaction.followup.send(extra)

    @chain.command(name="noping", description="Opt-out of chain pings.")
    async def noping(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Guild-only command.", ephemeral=True)

        db.chain_optin_remove(client.db_conn, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message("✅ Removed from chain pings.", ephemeral=True)

    @chain.command(name="status", description="Show chain watcher status + current chain timeout.")
    async def status(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Guild-only command.", ephemeral=True)

        # PUBLIC output; defer without ephemeral
        await interaction.response.defer(thinking=True)

        snap = client.chain_watcher.get_status_snapshot(interaction.guild.id)

        # Try reading current chain status live (safe + fast)
        chain_line = "Chain: (unavailable)"
        try:
            payload = await torn_api.fetch_faction_chain()
            chain_obj = torn_api.parse_active_chain(payload)
            if not chain_obj:
                chain_line = "Chain: **No active chain detected**"
            else:
                chain_line = f"Chain: **Active** — id `{chain_obj.get('id')}`, timeout **{chain_obj.get('timeout')}s**"
        except Exception as e:
            chain_line = f"Chain: ⚠️ error reading Torn chain ({type(e).__name__})"

        msg = (
            "⛓️ **Chain Watcher Status**\n"
            f"- Running: **{snap['running']}**\n"
            f"- Channel: {_fmt_channel(interaction.guild, snap['channel_id'])}\n"
            f"- Started by: {_fmt_user(snap['started_by'])}\n"
            f"- Alert threshold: **{snap['alert_seconds']}s**\n"
            f"- Poll interval: **{snap['poll_seconds']}s**\n"
            f"- Ping role: **{snap['ping_role_name']}**\n"
            f"- Control roles: {', '.join(snap['control_roles'])}\n"
            f"- Armed: **{snap['alert_armed']}**\n"
            f"- Last chain id: `{snap['last_chain_id']}`\n"
            f"- {chain_line}\n"
        )

        await interaction.followup.send(msg)

    tree.add_command(chain)
