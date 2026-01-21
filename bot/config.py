import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TORN_API_KEY = os.getenv("TORN_API_KEY")
BOT_MASTER_KEY = os.getenv("BOT_MASTER_KEY")
FACTION_ID = int(os.getenv("FACTION_ID", "0"))
TORN_TIMEOUT_SECONDS = float(os.getenv("TORN_TIMEOUT_SECONDS", "25"))

TORN_BASE = "https://api.torn.com/v2"
DB_PATH = "botdata.sqlite3"

VERIFIED_ROLE_NAME = "Verified"
LEADERSHIP_ROLES = {"Negan Saviors", "Lieutenant Saviors", "Soldier"}

WAR_START_CACHE_TTL_SECONDS = 120
USER_STATS_CACHE_TTL_SECONDS = 60

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing in .env")
if not TORN_API_KEY:
    raise RuntimeError("TORN_API_KEY missing in .env")
if not BOT_MASTER_KEY:
    raise RuntimeError("BOT_MASTER_KEY missing in .env")
