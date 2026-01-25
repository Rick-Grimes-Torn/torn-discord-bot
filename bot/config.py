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

SHEET_BOT_DATA_CSV_URL = "https://docs.google.com/spreadsheets/d/1N84XYb1HsphSefm6K_wNwNpUqbQ41WnAV2ZpfYdYjsA/export?format=csv&gid=1601570346"

ROSTER_CHECK_INTERVAL_SECONDS = 300  # 5 minutes
ROSTER_GRACE_MINUTES = 0            # if you want "late after 5 min", set to 5
ROSTER_ALERT_MIN_INTERVAL_SECONDS = 3600  # at most one alert per hour

WAR_START_CACHE_TTL_SECONDS = 120
USER_STATS_CACHE_TTL_SECONDS = 60

# Ordered list (first one that’s available wins)
EASY_TARGET_ATTACK_LINKS: list[str] = [
    "https://www.torn.com/loader.php?sid=attack&user2ID=1690708",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3517372",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3677182",
    "https://www.torn.com/loader.php?sid=attack&user2ID=1976263",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3121813",
    "https://www.torn.com/loader.php?sid=attack&user2ID=2074734",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3203692",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3204742",
    "https://www.torn.com/loader.php?sid=attack&user2ID=2035042",
    "https://www.torn.com/loader.php?sid=attack&user2ID=1669605",
    "https://www.torn.com/loader.php?sid=attack&user2ID=1683984",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3125220",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3675495",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3518771",
    "https://www.torn.com/loader.php?sid=attack&user2ID=2359838",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3494378",
    "https://www.torn.com/loader.php?sid=attack&user2ID=2661850",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3335007",
    "https://www.torn.com/loader.php?sid=attack&user2ID=2986400",
    "https://www.torn.com/loader.php?sid=attack&user2ID=3179561",

]

# Which Torn "status.state" values should be considered NOT attackable
# (You asked “out of hospital”; I’m including Jail/Federal as sensible defaults.
# If you want ONLY hospital, remove the others.)
DISALLOWED_TARGET_STATES = {"Hospital", "Jail", "Federal"}

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing in .env")
if not TORN_API_KEY:
    raise RuntimeError("TORN_API_KEY missing in .env")
if not BOT_MASTER_KEY:
    raise RuntimeError("BOT_MASTER_KEY missing in .env")
