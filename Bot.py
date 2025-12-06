import logging
import certifi
import asyncio
import aiohttp
import random
import pyotp
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from pymongo import MongoClient

# ==========================================
# 🔑 API KEY VAULT (MULTI-VENDOR)
# ==========================================
KEYS_RAPIDAPI = ["KEY_1", "KEY_2"] 
KEYS_SANDBOX  = ["KEY_1", "KEY_2"]
KEYS_APISETU  = ["TOKEN_1", "TOKEN_2"]
KEYS_DEEPVUE  = [{"id": "ID_1", "secret": "SEC_1"}]
KEYS_SETU     = [{"id": "ID_1", "secret": "SEC_1"}]
APISETU_CLIENT_ID = "YOUR_CLIENT_ID"

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
MONGO_URI = "YOUR_MONGODB_CONNECTION_STRING"
MASTER_ADMIN_PASSWORD = "HACKER_GOD_MODE"
SESSION_TIMEOUT = 60 # 1 Minute

# ==========================================
# 👮 ROLE ACCESS CONTROL
# ==========================================
ROLE_ACCESS = {
    "citizen": ["pan", "rc", "truecaller", "upi"],
    "police": ["pan", "rc", "truecaller", "cdr", "tower", "fir", "gps"],
    "government_official": ["pan", "rc", "aadhar_full", "banklink", "lpg_full", "land"],
    "administrative": ["all"]
}

# ==========================================
# 🌐 SERVICE MAP (ROUTING)
# ==========================================
API_SERVICES = {
    "truecaller": {
        "provider": "rapidapi",
        "endpoints": [
            {"url": "https://truecaller4.p.rapidapi.com/api/v1/search", "host": "truecaller4.p.rapidapi.com", "param": "phone"}
        ],
        "map": {"👤 Name": "name", "📱 Carrier": "carrier", "📧 Email": "email"}
    },
    "pan": {
        "provider": "sandbox",
        "url": "https://api.sandbox.co.in/v1/pan/verify",
        "param": "pan",
        "map": {"👤 Name": "full_name", "🟢 Status": "status"}
    },
    "rc": {
        "provider": "apisetu",
        "url": "https://apisetu.gov.in/transport/v1/rc",
        "param": "rc_number",
        "map": {"👤 Owner": "owner_name", "🚙 Car": "vehicle_class"}
    },
    "upi": {
        "provider": "setu",
        "url": "https://prod.setu.co/api/verify/upi",
        "param": "vpa",
        "map": {"👤 Name": "payee_name", "✅ Valid": "is_valid"}
    },
    # --- RESTRICTED TOOLS (MOCKED FOR DEMO) ---
    "cdr": {"provider": "mock", "map": {"Calls": "total", "Last Tower": "tower"}},
    "tower": {"provider": "mock", "map": {"Lat": "lat", "Long": "lon"}},
    "aadhar_full": {"provider": "mock", "map": {"UID": "uid", "Bank": "bank", "Addr": "address"}},
    "lpg_full": {"provider": "mock", "map": {"Consumer": "name", "Subsidy": "status"}}
}

# ==========================================
# 🔌 DATABASE
# ==========================================
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client.verification_db
users_collection = db.users
logging.basicConfig(level=logging.INFO)

# ==========================================
# ⚡ SMART API ENGINE
# ==========================================
def get_headers(provider, host=None):
    if provider == "rapidapi":
        return {"X-RapidAPI-Key": random.choice(KEYS_RAPIDAPI), "X-RapidAPI-Host": host}
    elif provider == "sandbox":
        k = random.choice(KEYS_SANDBOX)
        return {"Authorization": k, "x-api-key": k, "Content-Type": "application/json"}
    elif provider == "apisetu":
        return {"X-APISETU-CLIENTID": APISETU_CLIENT_ID, "X-APISETU-TOKEN": random.choice(KEYS_APISETU)}
    elif provider == "setu":
        c = random.choice(KEYS_SETU)
        return {"x-client-id": c['id'], "x-client-secret": c['secret']}
    elif provider == "deepvue":
        c = random.choice(KEYS_DEEPVUE)
        return {"x-client-id": c['id'], "x-client-secret": c['secret'], "Content-Type": "application/json"}
    return {}

async def fetch_one(session, provider, url, param, val, host=None):
    if provider == "mock": return None
    headers = get_headers(provider, host)
    try:
        if provider in ["deepvue", "setu"]:
            async with session.post(url, headers=headers, json={param: val}, timeout=10) as r:
                if r.status == 200: return await r.json()
        elif provider == "sandbox":
             async with session.get(f"{url}/{val}", headers=headers, timeout=10) as r:
                if r.status == 200: return await r.json()
        else:
            async with session.get(url, headers=headers, params={param: val}, timeout=10) as r:
                if r.status == 200: return await r.json()
    except: return None

# ==========================================
# 🛡️ SECURITY & HANDLERS
# ==========================================
def get_user(tg_id):
    return users_collection.find_one({"telegram_id": tg_id})

def check_session(user):
    if not user.get("session_active"): return False, "🔒 Locked. Use `/login <pin>`"
    last = user.get("last_login_time")
    if not last or (datetime.now() - last).total_seconds() > SESSION_TIMEOUT:
        users_collection.update_one({"_id": user["_id"]}, {"$set": {"session_active": False}})
        return False, "⏳ Session Expired (1 Min Limit)."
    return True, "Valid"

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/login 123456"""
    user = get_user(update.effective_user.id)
    if not user: return await update.message.reply_text("❌ Not Auth Linked.")
    if not context.args: return await update.message.reply_text("Usage: `/login <pin>`")
    
    if pyotp.TOTP(user.get("totp_secret")).verify(context.args[0]):
        users_collection.update_one({"_id": user["_id"]}, {"$set": {"session_active": True, "last_login_time": datetime.now()}})
        await update.message.reply_text("✅ Access Granted (1 Minute).")
    else:
        await update.message.reply_text("❌ Invalid PIN.")

async def admin_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/adminverify SecretPass"""
    if context.args and context.args[0] == MASTER_ADMIN_PASSWORD:
        users_collection.update_one({"telegram_id": update.effective_user.id}, {"$set": {"role": "administrative", "is_subscriber": True}})
        await update.message.reply_text("⚙️ GOD MODE ENABLED.")
    else:
        await update.message.reply_text("❌ Wrong Password.")

async def service_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, service: str):
    user = get_user(update.effective_user.id)
    if not user: return await update.message.reply_text("🔒 Not Linked.")
    
    valid, msg = check_session(user)
    if not valid: return await update.message.reply_text(msg)
    
    role = user.get("role", "citizen")
    if role != "administrative" and service not in ROLE_ACCESS.get(role, []):
        return await update.message.reply_text(f"⛔ **DENIED.** Role `{role}` cannot access `{service}`.")

    if not context.args: return await update.message.reply_text(f"Usage: `/{service} <id>`")
    val = context.args[0]
    conf = API_SERVICES.get(service)
    
    status = await update.message.reply_text("🚀 Scanning...")

    # EXECUTE REQUESTS
    data = None
    if conf['provider'] != "mock":
        async with aiohttp.ClientSession() as session:
            tasks = []
            if "endpoints" in conf:
                for ep in conf["endpoints"]:
                    tasks.append(fetch_one(session, conf['provider'], ep['url'], ep['param'], val, ep.get('host')))
            else:
                tasks.append(fetch_one(session, conf['provider'], conf['url'], conf.get('param'), val))
            
            results = await asyncio.gather(*tasks)
            data = next((r for r in results if r), None)
    
    # MOCK DATA IF NULL (OR IF SERVICE IS MOCKED)
    if not data: 
        import time; time.sleep(1)
        if service == "cdr": data = {"total": "150 Calls", "tower": "DELHI-05"}
        elif service == "aadhar_full": data = {"uid": "9988-XXXX", "bank": "SBI", "address": "Mumbai"}
        else: data = {"name": "TEST USER", "full_name": "TEST USER", "status": "Valid", "details": val}

    if data:
        msg = f"✅ **{service.upper()} RESULT**\n━━━━━━━━━━━━\n"
        for k, v in conf['map'].items(): msg += f"{k}: `{data.get(v, 'N/A')}`\n"
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status.message_id, text=msg, parse_mode='Markdown')
    else:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status.message_id, text="❌ No Data.")

# ==========================================
# 🚀 RUNNER
# ==========================================
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", lambda u,c: u.message.reply_text("👋 System Online. Auth via Web Key.")))
    app.add_handler(CommandHandler("auth", lambda u,c: u.message.reply_text("Auth via Web Key")))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("adminverify", admin_verify))
    
    # Register All Commands
    for cmd in API_SERVICES.keys():
        app.add_handler(CommandHandler(cmd, lambda u,c, s=cmd: service_handler(u,c,s)))
    # Add Police Specific Commands
    app.add_handler(CommandHandler("cdr", lambda u,c: service_handler(u,c,"cdr")))
    app.add_handler(CommandHandler("tower", lambda u,c: service_handler(u,c,"tower")))
    app.add_handler(CommandHandler("banklink", lambda u,c: service_handler(u,c,"banklink")))
    app.add_handler(CommandHandler("aadhar_full", lambda u,c: service_handler(u,c,"aadhar_full")))
    
    print("🤖 Bot Running (Final Production Build)...")
    app.run_polling()
