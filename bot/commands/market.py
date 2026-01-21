import time
import discord
from discord import app_commands

from ..utils import chunk_lines, is_verified_member
from .. import yata_api


def _fmt_ts(ts: int) -> str:
    # Discord timestamp formatting
    return f"<t:{int(ts)}:R>" if ts else "unknown"


def _classify(name: str) -> str:
    n = (name or "").lower()
    if "plushie" in n:
        return "plushie"
    if "orchid" in n or "flower" in n or n in {"dahlia", "heather", "crocus", "ceibo flower"}:
        return "flower"
    # simple drug keywords
    if n in {"xanax", "ecstasy", "cannabis", "ketamine", "pcp", "vicodin", "shrooms", "speed"}:
        return "drug"
    # tools-ish
    if n in {"bolt cutters", "zip ties", "card skimmer"}:
        return "tool"
    # crude weapon/armor heuristics
    if any(k in n for k in ["gun", "rifle", "pistol", "uzi", "ak-", "m249", "minigun", "grenade", "crossbow", "derringer", "desert eagle", "tavor", "enfield", "bushmaster", "ithaca", "lorcin"]):
        return "weapon"
    if any(k in n for k in ["vest", "helmet", "gloves", "jacket", "boots", "coat", "wetsuit", "bikini", "speedo"]):
        return "armor"
    return "other"


def register(tree: app_commands.CommandTree):
    market = app_commands.Group(name="market", description="Foreign stock market tools (YATA travel export).")

    @market.command(name="restocks", description="Show last update time per country (most recent first).")
    async def restocks(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not is_verified_member(interaction):
            return await interaction.followup.send("You must have the **Verified** role to use this command.")

        payload = await yata_api.get_travel_export_cached()
        stocks = payload.get("stocks") or {}

        rows = []
        for code, block in stocks.items():
            upd = int((block or {}).get("update") or 0)
            rows.append((upd, code))

        rows.sort(reverse=True)

        lines = []
        for upd, code in rows:
            lines.append(f"- **{yata_api.country_name(code)}** (`{code}`): updated {_fmt_ts(upd)}")

        msg = "\n".join(lines) if lines else "No stock data available."
        await interaction.followup.send("🧾 **Foreign stock restocks**\n" + msg)

    @market.command(name="travel", description="Show stock for a country (optionally filter).")
    @app_commands.describe(
        country="Country code (mex/cay/can/haw/uni/arg/swi/jap/chi/uae/sou)",
        in_stock_only="Show only items with quantity > 0 (default True)",
        category="Filter: plushie/flower/drug/weapon/armor/tool/other",
    )
    async def travel(
        interaction: discord.Interaction,
        country: str,
        in_stock_only: bool = True,
        category: str = "all",
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not is_verified_member(interaction):
            return await interaction.followup.send("You must have the **Verified** role to use this command.")

        code = (country or "").strip().lower()
        payload = await yata_api.get_travel_export_cached()
        block = (payload.get("stocks") or {}).get(code)

        if not block:
            return await interaction.followup.send(
                f"Unknown country `{code}`.\n"
                "Valid: mex, cay, can, haw, uni, arg, swi, jap, chi, uae, sou"
            )

        upd = int(block.get("update") or 0)
        items = block.get("stocks") or []

        cat = (category or "all").strip().lower()
        if cat == "all":
            cat = ""

        shown = []
        for it in items:
            q = int(it.get("quantity") or 0)
            if in_stock_only and q <= 0:
                continue
            name = str(it.get("name") or "")
            if cat and _classify(name) != cat:
                continue
            shown.append(it)

        # Sort: in-stock first, then qty desc, then cost asc
        shown.sort(key=lambda x: (-(int(x.get("quantity") or 0)), int(x.get("cost") or 0)))

        header = (
            f"🛒 **{yata_api.country_name(code)}** (`{code}`) — updated {_fmt_ts(upd)}\n"
            f"Filters: in_stock_only={in_stock_only}, category={(cat or 'all')}\n\n"
        )

        lines = []
        for it in shown[:80]:  # keep messages sane
            lines.append(
                f"- `{int(it.get('id') or 0)}` **{it.get('name')}** — qty **{int(it.get('quantity') or 0):,}**, cost **{int(it.get('cost') or 0):,}**"
            )

        if not lines:
            return await interaction.followup.send(header + "_No matching items._")

        # Split into multiple messages if needed
        parts = chunk_lines(header, lines, limit=1900)
        for p in parts:
            await interaction.followup.send(p)

    @market.command(name="find", description="Find an item across all countries by name or item id.")
    @app_commands.describe(query="Item name (partial) or numeric item id")
    async def find(interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not is_verified_member(interaction):
            return await interaction.followup.send("You must have the **Verified** role to use this command.")

        q = (query or "").strip()
        if not q:
            return await interaction.followup.send("Provide an item name or id.")

        q_lower = q.lower()
        q_id = None
        if q.isdigit():
            q_id = int(q)

        payload = await yata_api.get_travel_export_cached()
        stocks = payload.get("stocks") or {}

        matches = []
        for code, block in stocks.items():
            upd = int((block or {}).get("update") or 0)
            for it in (block or {}).get("stocks") or []:
                iid = int(it.get("id") or 0)
                name = str(it.get("name") or "")
                if q_id is not None:
                    if iid != q_id:
                        continue
                else:
                    if q_lower not in name.lower():
                        continue

                matches.append((code, upd, it))

        # Prefer in-stock, then lowest cost, then most recent country update
        def _sort_key(m):
            code, upd, it = m
            qty = int(it.get("quantity") or 0)
            cost = int(it.get("cost") or 0)
            return (-(qty > 0), cost, -upd)

        matches.sort(key=_sort_key)

        if not matches:
            return await interaction.followup.send(f"No matches for `{q}`.")

        header = f"🔎 **Market search:** `{q}`\n\n"
        lines = []
        for code, upd, it in matches[:40]:
            qty = int(it.get("quantity") or 0)
            cost = int(it.get("cost") or 0)
            lines.append(
                f"- **{it.get('name')}** (`{int(it.get('id') or 0)}`) in **{yata_api.country_name(code)}**: "
                f"qty **{qty:,}**, cost **{cost:,}** (updated {_fmt_ts(upd)})"
            )

        for p in chunk_lines(header, lines, limit=1900):
            await interaction.followup.send(p)

    @market.command(name="top", description="Show top in-stock items for a country (by quantity, then cost).")
    @app_commands.describe(country="Country code", limit="How many items to show (max 25)")
    async def top(interaction: discord.Interaction, country: str, limit: int = 10):
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not is_verified_member(interaction):
            return await interaction.followup.send("You must have the **Verified** role to use this command.")

        code = (country or "").strip().lower()
        limit = max(1, min(int(limit), 25))

        payload = await yata_api.get_travel_export_cached()
        block = (payload.get("stocks") or {}).get(code)
        if not block:
            return await interaction.followup.send(f"Unknown country `{code}`.")

        upd = int(block.get("update") or 0)
        items = [it for it in (block.get("stocks") or []) if int(it.get("quantity") or 0) > 0]
        items.sort(key=lambda x: (-(int(x.get("quantity") or 0)), int(x.get("cost") or 0)))

        lines = []
        for it in items[:limit]:
            lines.append(
                f"- `{int(it.get('id') or 0)}` **{it.get('name')}** — qty **{int(it.get('quantity') or 0):,}**, cost **{int(it.get('cost') or 0):,}**"
            )

        header = f"⭐ **Top items — {yata_api.country_name(code)}** (`{code}`), updated {_fmt_ts(upd)}\n\n"
        if not lines:
            return await interaction.followup.send(header + "_No in-stock items._")

        await interaction.followup.send(header + "\n".join(lines))
    @market.command(name="help", description="How to use /market + country codes and examples.")
    async def market_help(interaction: discord.Interaction):
        # Keep this ephemeral so it doesn’t spam channels
        await interaction.response.send_message(
            "**🛒 /market — Help**\n\n"
            "**What it is**\n"
            "- Uses YATA foreign stock export data to show travel shop stock (live, cached briefly).\n\n"
            "**Country codes**\n"
            "- `mex` Mexico\n"
            "- `cay` Cayman Islands\n"
            "- `can` Canada\n"
            "- `haw` Hawaii\n"
            "- `uni` United Kingdom\n"
            "- `arg` Argentina\n"
            "- `swi` Switzerland\n"
            "- `jap` Japan\n"
            "- `chi` China\n"
            "- `uae` UAE\n"
            "- `sou` South Africa\n\n"
            "**Categories (for /market travel)**\n"
            "- `plushie`, `flower`, `drug`, `weapon`, `armor`, `tool`, `other`, or `all`\n\n"
            "**Commands**\n"
            "- `/market restocks` → shows which countries updated most recently\n"
            "- `/market travel <country> [in_stock_only] [category]` → shows that country’s stock\n"
            "- `/market find <query>` → search item by name or numeric id across all countries\n"
            "- `/market top <country> [limit]` → top in-stock items for that country\n\n"
            "**Examples**\n"
            "- `/market restocks`\n"
            "- `/market travel mex`\n"
            "- `/market travel can in_stock_only:true category:drug`\n"
            "- `/market find xanax`\n"
            "- `/market find 206`\n"
            "- `/market top haw limit:10`\n",
            ephemeral=True,
        )


    tree.add_command(market)
