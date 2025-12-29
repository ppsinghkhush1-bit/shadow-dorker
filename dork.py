import asyncio
import logging
import os
import random
import html
import json
from datetime import datetime, date, timedelta
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from gate_scanner import scan_single_site, scan_multiple_sites
from gate_scanner import close_session
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
import re

# ==================== CONFIG ====================
BOT_TOKEN = "8308834385:AAFAOW-b6UnMPj9Lo27q4rZod8k1Vz0s6Q0"

GOOGLE_API_KEY = "AIzaSyAShqpTaJ4Crtbr1w3qs9pjQtD8Rh9mvEY"
GOOGLE_CX = "67cfd7b411db244fd"

# ==================== PERMISSIONS ====================
OWNER_ID = 8228412160   # <-- replace with your Telegram user ID

ADMIN_IDS = {
    5248903529,          # admin 1
    5295792382,          # admin 3
}

QUOTA_FILE = "google_quota.json"
DAILY_LIMIT = 100
BLOCKED_GROUPS_FILE = "blocked_groups.json"
BLOCKED_USERS_FILE = "blocked_users.json"  # ← FIXED: defined

RESULTS_PER_PAGE = 10
MAX_PAGES = 3

RANDOM_DORKS = [
    'inurl:collections "powered by shopify"',
    'inurl:products "powered by shopify"',
    'site:myshopify.com -login -admin',
    'intext:"powered by shopify" "shop"',
]

# ==================== BOT ====================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# ==================== MENTION & REPLY AUTO-HARVEST ====================
BOT_USERNAME = "shadowdorker_bot"  # lowercase, no @

@dp.message(
    lambda message: (
        message.chat.type in ("group", "supergroup") and
        message.entities and
        any(
            e.type == "mention" and 
            message.text[e.offset:e.offset+e.length].lower() == f"@{BOT_USERNAME}"
            for e in message.entities
        )
    )
)

async def auto_mention_reply_harvest(message: Message):
    if await is_group_blocked(message):
        return

    query = message.text.strip()
    if query.lower().startswith(f"@{BOT_USERNAME}"):
        query = query[len(f"@{BOT_USERNAME}"):].strip()

    if not query:
        await message.answer("🩸 Mention me with a dork query.")
        return

    processing = await message.answer("🔍 Harvesting your dork live...")

    files = await perform_harvest(query)

    if files and "LIMIT REACHED" in open(files[0], "r", encoding="utf-8").read():
        await processing.edit_text("🚫 Daily Google quota exhausted.")
        os.remove(files[0])
        return

    await processing.edit_text("✅ Harvest complete")

    for f in files:
        await message.answer_document(FSInputFile(f))
        os.remove(f)

# ==================== QUOTA SYSTEM ====================
def load_quota():
    if not os.path.exists(QUOTA_FILE):
        return {"date": str(date.today()), "used": 0}
    with open(QUOTA_FILE, "r") as f:
        data = json.load(f)
    if data.get("date") != str(date.today()):
        return {"date": str(date.today()), "used": 0}
    return data

def save_quota(data):
    with open(QUOTA_FILE, "w") as f:
        json.dump(data, f)

def can_use_google(pages_needed: int) -> bool:
    quota = load_quota()
    return quota["used"] + pages_needed <= DAILY_LIMIT

def consume_quota(pages_used: int):
    quota = load_quota()
    quota["used"] += pages_used
    save_quota(quota)

# ==================== GROUP BLOCK SYSTEM ====================
def load_blocked_groups() -> set[int]:
    if not os.path.exists(BLOCKED_GROUPS_FILE):
        return set()
    with open(BLOCKED_GROUPS_FILE, "r") as f:
        return set(json.load(f))

def save_blocked_groups(groups: set[int]):
    with open(BLOCKED_GROUPS_FILE, "w") as f:
        json.dump(list(groups), f)

async def is_group_blocked(message: Message) -> bool:
    if message.chat.type in ("group", "supergroup"):
        blocked = load_blocked_groups()
        return message.chat.id in blocked
    return False

def is_owner_or_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ADMIN_IDS

# ==================== USER BLOCK SYSTEM ====================
def load_blocked_users() -> dict[int, str | None]:
    if not os.path.exists(BLOCKED_USERS_FILE):
        return {}
    with open(BLOCKED_USERS_FILE, "r") as f:
        raw = json.load(f)
    cleaned = {}
    today = str(date.today())
    for uid, expiry in raw.items():
        if expiry is None or expiry >= today:
            cleaned[int(uid)] = expiry
    if cleaned != raw:
        save_blocked_users(cleaned)
    return cleaned

def save_blocked_users(data: dict[int, str | None]):
    with open(BLOCKED_USERS_FILE, "w") as f:
        json.dump(data, f)

def is_user_blocked(user_id: int) -> bool:
    blocked = load_blocked_users()
    return user_id in blocked  # simple presence, None means not blocked

async def get_target_user_id(message: Message) -> int | None:
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    args = message.text.strip().split()
    if len(args) < 2:
        return None
    target = args[1].lstrip('@')
    if target.isdigit():
        return int(target)
    try:
        user = await bot.get_chat(target)
        return user.id
    except:
        return None

# ==================== MIDDLEWARE ====================
async def block_check_middleware(handler, event, data):
    if hasattr(event, "from_user") and event.from_user:
        if is_user_blocked(event.from_user.id):
            return  # ← silently drops the event
    return await handler(event, data)

dp.message.middleware(block_check_middleware)
dp.callback_query.middleware(block_check_middleware)

# ==================== NEW: IP LOOKUP ====================
async def ip_lookup(ip: str) -> str:
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data["status"] == "success":
                return (
                    f"🌐 <b>IP Lookup: {ip}</b>\n\n"
                    f"Country: {data.get('country', 'N/A')} ({data.get('countryCode', 'N/A')})\n"
                    f"Region: {data.get('regionName', 'N/A')}\n"
                    f"City: {data.get('city', 'N/A')}\n"
                    f"ISP: {data.get('isp', 'N/A')}\n"
                    f"Org: {data.get('org', 'N/A')}\n"
                    f"AS: {data.get('as', 'N/A')}\n"
                    f"Lat/Lon: {data.get('lat', 'N/A')}, {data.get('lon', 'N/A')}\n"
                    f"Timezone: {data.get('timezone', 'N/A')}\n"
                    f"Proxy/VPN/Tor: {'Yes' if data.get('proxy', False) or data.get('hosting', False) else 'No'}"
                )
            else:
                return f"❌ Invalid IP or lookup failed: {data.get('message', 'Unknown error')}"
        else:
            return "❌ API error"
    except:
        return "❌ Request timed out or failed"

@dp.message(Command("ip"))
async def ip_cmd(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("Usage: /ip <ip_address>")
    ip = command.args.strip()
    result = await ip_lookup(ip)
    await message.answer(result)

# ==================== GOOGLE SEARCH ====================
def google_search(dork: str, pages: int = MAX_PAGES) -> list[str]:
    # QUOTA CHECK
    if not can_use_google(pages):
        return ["❌ DAILY GOOGLE LIMIT REACHED (100 searches/day)"]

    results = []
    pages_used = 0

    for page in range(pages):
        start = page * RESULTS_PER_PAGE + 1
        params = {
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_CX,
            "q": dork,
            "num": RESULTS_PER_PAGE,
            "start": start,
        }

        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=15
        )

        if r.status_code != 200:
            break

        data = r.json()
        items = data.get("items", [])
        if not items:
            break

        pages_used += 1  # ✅ COUNT API CALL

        for item in items:
            link = item.get("link", "")
            if link.startswith("http"):
                results.append(link)

    # CONSUME QUOTA
    if pages_used > 0:
        consume_quota(pages_used)

    return results

# ==================== HARVEST ====================
async def perform_harvest(dork: str) -> list[str]:
    header = [
        "GOOGLE DORK HARVEST",
        f"Dork: {dork}",
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
    ]

    results = google_search(dork)

    filename = f"google_dork_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(header + results))

    return [filename]

async def is_admin_or_owner(message: Message) -> bool:
    if message.chat.type not in ("group", "supergroup"):
        return False

    member = await message.bot.get_chat_member(
        chat_id=message.chat.id,
        user_id=message.from_user.id
    )

    return member.status in ("administrator", "creator")

# ==================== NEW: PROXY CHECKER & FETCH ====================
PROXY_API = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"

async def fetch_proxies() -> list[str]:
    try:
        r = requests.get(PROXY_API, timeout=15)
        if r.status_code == 200:
            return [line.strip() for line in r.text.splitlines() if line.strip()]
    except:
        pass
    return []

@dp.message(Command("pxy"))
async def pxy_cmd(message: Message):
    msg = await message.answer("🩸 Scraping random fresh proxies...")
    proxies = await fetch_proxies()
    if not proxies:
        return await msg.edit_text("❌ No proxies available.")
    
    random_proxies = random.sample(proxies, min(200, len(proxies)))
    
    filename = f"random_proxies_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w") as f:
        f.write("\n".join(random_proxies))
    
    await msg.edit_text(f"✅ {len(random_proxies)} random proxies scraped")
    await message.answer_document(FSInputFile(filename))
    os.remove(filename)

CARD_REGEX = re.compile(r'\b(\d{15,16})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})\b')

async def scrape_cards(chat_id: str, bin_filter: str = None, amount: int = 50) -> list[str]:
    cards = []
    try:
        # Convert username to ID if needed
        if isinstance(chat_id, str) and chat_id.startswith('@'):
            try:
                chat = await bot.get_chat(chat_id)
                chat_id = chat.id
                print(f"Resolved @{chat_id} to ID: {chat.id}")
            except Exception as e:
                print(f"Failed to resolve username: {e}")
                return []
        
        # Ensure we have an integer ID
        chat_id = int(chat_id) if not isinstance(chat_id, int) else chat_id
        
        # Check if bot is in the chat
        try:
            chat_member = await bot.get_chat_member(chat_id, bot.id)
            print(f"Bot status in chat: {chat_member.status}")
        except Exception as e:
            print(f"Bot not in chat or no access: {e}")
            return []
        
        message_count = 0
        async for msg in bot.iter_messages(chat_id, limit=5000):
            message_count += 1
            if msg.text:
                matches = CARD_REGEX.findall(msg.text)
                for match in matches:
                    cc, mm, yy, cvc = match
                    full = f"{cc}|{mm}|{yy}|{cvc}"
                    if bin_filter and not cc.startswith(bin_filter):
                        continue
                    cards.append(full)
                    if len(cards) >= amount:
                        print(f"Found {len(cards)} cards in {message_count} messages")
                        return cards
        
        print(f"Scanned {message_count} messages, found {len(cards)} cards")
        
    except Exception as e:
        print(f"Error scraping cards: {e}")
    return cards

@dp.message(Command("scr"))
async def scr_cmd(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    if len(args) < 1:
        return await message.answer(
            "Usage: /scr <channel/group/username/id> [bin] [amount]\n"
            "Examples:\n"
            "/scr @channelname\n"
            "/scr -1001234567890 414720 100\n"
            "/scr groupusername 555555 50"
        )
    
    target = args[0]
    bin_f = args[1] if len(args) > 1 else None
    amt = int(args[2]) if len(args) > 2 else 50
    amt = min(amt, 200)  # cap
    
    msg = await message.answer(f"🩸 Scraping cards from {target}...")
    cards = await scrape_cards(target, bin_f, amt)
    
    if not cards:
        return await msg.edit_text("💀 No cards found or no access to target.")
    
    filename = f"cards_{target.replace('-100', '').replace('@', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, "w") as f:
        f.write("\n".join(cards))
    
    await msg.edit_text(f"🔥 Scraped {len(cards)} cards {'(BIN ' + bin_f + ')' if bin_f else '(random)'}")
    await message.answer_document(FSInputFile(filename))
    os.remove(filename)

# ==================== OPTIMIZED UNIVERSAL AUTO-PIN ====================
CHARGING_BOT_ID = 7945871785
CHARGED_TEXT = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"

@dp.message(lambda message: 
    message.chat.type in ("group", "supergroup") and
    message.from_user and 
    message.from_user.id == CHARGING_BOT_ID and
    message.text and 
    CHARGED_TEXT in message.text
)
async def universal_auto_pin_charged(message: Message):
    # Prevent pinning own messages if somehow triggered
    if message.from_user.is_bot and message.sender_chat:
        return
    
    try:
        await bot.pin_chat_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
            disable_notification=True
        )
        logging.info(f"[PINNED] CHARGED in {message.chat.id} | Msg ID: {message.message_id}")
    except Exception as e:
        logging.error(f"[PIN FAIL] Chat {message.chat.id}: {e}")

# ==================== GROUP BLOCK COMMANDS ====================
@dp.message(Command("blockgroup"))
async def blockgroup_cmd(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("❌ This command only works in groups.")
    if not await is_admin_or_owner(message):
        return await message.answer("⛔ Only admins/owner can block groups.")
    
    blocked = load_blocked_groups()
    if message.chat.id in blocked:
        return await message.answer("⚠️ This group is already blocked.")
    
    blocked.add(message.chat.id)
    save_blocked_groups(blocked)
    await message.answer("🚫 Bot blocked in this group.")

@dp.message(Command("unblockgroup"))
async def unblockgroup_cmd(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("❌ This command only works in groups.")
    if not await is_admin_or_owner(message):
        return await message.answer("⛔ Only admins/owner can unblock groups.")
    
    blocked = load_blocked_groups()
    if message.chat.id not in blocked:
        return await message.answer("✅ This group is not blocked.")
    
    blocked.remove(message.chat.id)
    save_blocked_groups(blocked)
    await message.answer("🔓 Bot unblocked in this group.")

# ==================== COMMANDS ====================
@dp.message(Command("start", "help"))
async def start_cmd(message: Message):
    text = (
        "😈 <b>ABYSS BOT v2.0</b> | Owner-Only Arsenal 🔥\n\n"
        "<b>GOOGLE DORKING</b>\n"
        "/dork <code>&lt;query&gt;</code> → Harvest URLs via Google dork\n"
        "/gen <code>&lt;n&gt;</code> → Generate & run random dorks\n\n"
        
        "<b>GATE SCANNING</b>\n"
        "/gate <code>&lt;url&gt;</code> → Single site payment gate check\n"
        "/mgate <code>&lt;url1 url2 ...&gt;</code> → Multi-gate check (max 5)\n\n"
        
        "<b>PROXY TOOLS</b>\n"
        "/pxy → Scrape 200 random fresh proxies (TXT)\n\n"
        
        "<b>INTEL & SCRAPING</b>\n"
        "/ip <code>&lt;ip_address&gt;</code> → Full IP geolocation lookup\n"
        "/scr <code>&lt;channel/group/id&gt; [bin] [amount]</code> → Scrape CC dumps (max 200)\n\n"
        
        "<b>ADMIN CONTROLS (Owner/Admins Only)</b>\n"
        "/blockgroup → Block bot in current group\n"
        "/unblockgroup → Unblock bot in current group\n\n"
        
        "🩸 All tools real-time\n"
        "Developer: ⏤͟͞𝐍𝐞𝐱𝐮𝐬 𝐒𝐡𝐚𝐝𝐨𝐰"
    )
    await message.answer(text)

@dp.message(Command("dork"))
async def dork_cmd(message: Message, command: CommandObject):

    if await is_group_blocked(message):
        return await message.answer("🚫 This bot is blocked in this group.")

    if not command.args:
        return await message.answer(
            "❌ Usage:\n<code>/dork &lt;google dork&gt;</code>"
        )

    dork = command.args.strip()

    msg = await message.answer("🔍 Searching Google...")

    files = await perform_harvest(dork)

    if files and "LIMIT REACHED" in open(files[0], encoding="utf-8").read():
        await msg.edit_text("🚫 Google daily limit reached (100 searches/day).")
        os.remove(files[0])
        return

    await msg.edit_text("✅ Done")

    for f in files:
        await message.answer_document(FSInputFile(f))
        os.remove(f)

@dp.message(Command("gen"))
async def gen_cmd(message: Message, command: CommandObject):
    try:
        n = int(command.args or 1)
    except:
        n = 1

    dorks = RANDOM_DORKS[:max(1, min(n, len(RANDOM_DORKS)))]
    kb = InlineKeyboardMarkup(inline_keyboard=[])

    text = "🔥 <b>Random Google Dorks</b>\n\n"
    for i, d in enumerate(dorks, 1):
        text += f"<code>{html.escape(d)}</code>\n"
        kb.inline_keyboard.append(
            [InlineKeyboardButton(text=f"Run #{i}", callback_data=f"run:{d}")]
        )

    await message.answer(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("run:"))
async def run_cb(call: types.CallbackQuery):
    dork = call.data.split(":", 1)[1]
    files = await perform_harvest(dork)
    for f in files:
        await call.message.answer_document(FSInputFile(f))
        os.remove(f)

@dp.message(Command("gate"))
async def gate_command(message: Message, state: FSMContext):
    args = message.text.strip().split()
    if len(args) < 2:
        return await message.answer("Usage: /gate <url>")

    url = args[1]
    checking = await message.answer("🔍 <b>Checking Site...</b>")

    result = await scan_single_site(url)
    safe_result = html.escape(result)

    await checking.edit_text(
        f"{safe_result}\n\n<b>Developer:</b> ⏤͟͞𝐍𝐞𝐱𝐮𝐬 𝐒𝐡𝐚𝐝𝐨𝐰"
    )

@dp.message(Command("mgate"))
async def mgate_command(message: Message):
    args = message.text.strip().split()[1:]
    if not args:
        return await message.answer("Usage: /mgate <url1> <url2> ... (max 5)")

    urls = args[:5]
    checking = await message.answer(f"🔍 <b>Checking {len(urls)} sites...</b>")

    result = await scan_multiple_sites(urls)
    safe_result = html.escape(result)

    await checking.edit_text(
        f"{safe_result}\n\n<b>Developer:</b> ⏤͟͞𝐍𝐞𝐱𝐮𝐬 𝐒𝐡𝐚𝐝𝐨𝐰"
    )

# ==================== RUN ====================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
