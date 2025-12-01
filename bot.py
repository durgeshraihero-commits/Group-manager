#!/usr/bin/env python3
"""
bot.py - Telegram Group Manager Bot (MongoDB persistence)

Requirements:
  pip install python-telegram-bot==20.3 motor python-dotenv

Environment variables expected:
  BOT_TOKEN - your Telegram bot token
  MONGODB_URI - mongodb+srv://... connection string (include user & password)
  MONGODB_DBNAME - database name (e.g. tg_bot_db)
  ADMIN_USERNAME - admin Telegram username (without @)
  ADMIN_USER_ID - admin numeric Telegram user id
  DAILY_MESSAGE_LIMIT (optional) - default 1
  NEW_USER_MESSAGE_LIMIT (optional) - default 5

Run:
  python bot.py

This bot:
  - stores one document per user in MongoDB
  - loads users on startup so restarts do not re-award new user bonus
  - mutes users in groups until next IST midnight when they exceed daily limit
  - admin-only commands: /export_users, /get_user <id>, /resync, /allow <id> <days>
"""

import os
import io
import csv
import json
import logging
import asyncio
from datetime import datetime, timedelta, time, timezone
from typing import Dict, Any

import motor.motor_asyncio
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# -----------------------
# Config (from env)
# -----------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGODB_URI = os.environ.get("MONGODB_URI")
MONGODB_DBNAME = os.environ.get("MONGODB_DBNAME", "tg_bot_db")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "itsmezigzagzozo")
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "6314556756"))
DAILY_MESSAGE_LIMIT = int(os.environ.get("DAILY_MESSAGE_LIMIT", "1"))
NEW_USER_MESSAGE_LIMIT = int(os.environ.get("NEW_USER_MESSAGE_LIMIT", "5"))

PREMIUM_PLANS = {
    "week": {"price": 300, "duration_days": 7, "name": "Weekly"},
    "month": {"price": 500, "duration_days": 30, "name": "Monthly"}
}

IST = ZoneInfo("Asia/Kolkata")
LOCAL_USERS_FILE = os.environ.get("LOCAL_USERS_FILE", "users.json")

# -----------------------
# Logging
# -----------------------
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------
# MongoDB (async)
# -----------------------
mongo_client = None
db = None
users_coll = None
payments_coll = None

async def init_mongo():
    global mongo_client, db, users_coll, payments_coll
    if not MONGODB_URI:
        logger.warning("MONGODB_URI not set — falling back to local JSON persistence only.")
        return False
    try:
        mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
        db = mongo_client[MONGODB_DBNAME]
        users_coll = db.get_collection("users")
        payments_coll = db.get_collection("pending_payments")
        # ensure index
        await users_coll.create_index("user_id", unique=True)
        logger.info("Connected to MongoDB and ensured index on user_id")
        return True
    except Exception as e:
        logger.error(f"MongoDB init error: {e}")
        mongo_client = None
        return False

# -----------------------
# In-memory cache
# -----------------------
user_cache: Dict[int, Dict[str, Any]] = {}

# -----------------------
# Helpers: time
# -----------------------

def now_ist():
    return datetime.now(tz=IST)


def now_ist_iso():
    return now_ist().isoformat(timespec='seconds')


def next_midnight_ist_as_utc():
    now = now_ist()
    next_midnight_ist = datetime.combine(now.date() + timedelta(days=1), time(0,0), tzinfo=IST)
    return next_midnight_ist.astimezone(timezone.utc)

# -----------------------
# Persistence helpers
# -----------------------
async def load_users_from_db():
    """Load users from MongoDB into user_cache; fallback to local JSON if necessary."""
    user_cache.clear()
    if users_coll:
        try:
            async for doc in users_coll.find({}):
                user_cache[int(doc["user_id"])] = doc
            logger.info(f"Loaded {len(user_cache)} users from MongoDB")
            return
        except Exception as e:
            logger.error(f"Failed to load users from MongoDB: {e}")
    # fallback
    if os.path.exists(LOCAL_USERS_FILE):
        try:
            with open(LOCAL_USERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for k, v in data.items():
                user_cache[int(k)] = v
            logger.info(f"Loaded {len(user_cache)} users from local file")
        except Exception as e:
            logger.error(f"Failed to load local users file: {e}")
    else:
        logger.info("No users found in DB or local file; starting fresh")

async def persist_user_to_db(doc: Dict[str, Any]):
    """Upsert user doc to MongoDB; update cache and fallback to local file if needed."""
    uid = int(doc["user_id"])
    user_cache[uid] = doc
    if users_coll:
        try:
            await users_coll.update_one({"user_id": uid}, {"$set": doc}, upsert=True)
            return True
        except Exception as e:
            logger.error(f"Mongo upsert error for {uid}: {e}")
    # fallback save all
    try:
        tmp = {str(k): v for k,v in user_cache.items()}
        with open(LOCAL_USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(tmp, f, ensure_ascii=False, indent=2)
        logger.debug("Saved users to local fallback file")
    except Exception as e:
        logger.error(f"Failed to save local fallback: {e}")
    return False

# -----------------------
# Utils
# -----------------------

def make_user_doc(user_id: int, username: str = "", first_name: str = "") -> Dict[str, Any]:
    return {
        "user_id": int(user_id),
        "username": username or "",
        "first_name": first_name or "",
        "count": 0,
        "date": now_ist().date().isoformat(),
        "is_new_user": True,
        "joined_date": now_ist_iso(),
        "premium_expires": "",
        "premium_plan": "",
        "last_seen": now_ist_iso(),
        "last_command": ""
    }


def is_premium_active(doc: Dict[str, Any]) -> bool:
    exp = doc.get("premium_expires", "")
    if not exp:
        return False
    try:
        exp_dt = datetime.fromisoformat(exp)
        return now_ist() < exp_dt
    except Exception:
        return False

# -----------------------
# Audit stub
# -----------------------
async def record_event_audit(event_type: str, doc: Dict[str, Any], extra: Dict[str, Any] = None):
    logger.info(f"AUDIT {event_type} user={doc.get('user_id')} extra={extra}")
    # persist user state
    await persist_user_to_db(doc)

# -----------------------
# Command handlers
# -----------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    uname = user.username or ""
    fname = user.first_name or ""

    if uid not in user_cache:
        doc = make_user_doc(uid, uname, fname)
        await persist_user_to_db(doc)
        await record_event_audit('first_seen', doc)
        welcome = f"\n🎁 Welcome Bonus: {NEW_USER_MESSAGE_LIMIT} searches for today!"
    else:
        doc = user_cache[uid]
        # update names
        doc['username'] = uname or doc.get('username', '')
        doc['first_name'] = fname or doc.get('first_name', '')
        doc['last_seen'] = now_ist_iso()
        await persist_user_to_db(doc)
        welcome = "" if not doc.get('is_new_user', True) else f"\n🎁 Welcome Bonus: {NEW_USER_MESSAGE_LIMIT} searches for today!"

    premium_status = "✅ PREMIUM" if is_premium_active(doc) else "🆓 FREE"
    await update.message.reply_text(
        f"👋 Welcome!\n\nYour Status: {premium_status}{welcome}\n\nOnly messages starting with / are counted. Use /status to check your account."
    )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    if uid not in user_cache:
        await update.message.reply_text("You are not registered. Use /start.")
        return
    doc = user_cache[uid]
    today = now_ist().date().isoformat()
    if doc.get('date') != today:
        doc['count'] = 0
        doc['date'] = today
        doc['is_new_user'] = doc.get('is_new_user', True) and (doc.get('joined_date','').split('T')[0] == today)
        await persist_user_to_db(doc)

    if is_premium_active(doc):
        await update.message.reply_text(f"💎 PREMIUM\nPlan: {doc.get('premium_plan','')}\nExpires: {doc.get('premium_expires','')}")
    else:
        joined_today = doc.get('joined_date','').split('T')[0] == now_ist().date().isoformat()
        limit = NEW_USER_MESSAGE_LIMIT if doc.get('is_new_user', True) and joined_today else DAILY_MESSAGE_LIMIT
        await update.message.reply_text(f"🆓 Free\nUsed: {doc.get('count',0)}/{limit}\nJoined: {doc.get('joined_date','')}")

async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 Weekly - ₹300", callback_data="buy_week")],
        [InlineKeyboardButton("📆 Monthly - ₹500", callback_data="buy_month")],
        [InlineKeyboardButton("💬 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")]
    ]
    await update.message.reply_text("Choose a plan:", reply_markup=InlineKeyboardMarkup(keyboard))

async def plan_selection_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    uname = query.from_user.username or query.from_user.first_name
    plan = query.data.replace('buy_', '')
    if plan not in PREMIUM_PLANS:
        await query.edit_message_text("Invalid plan")
        return
    payment_id = f"{uid}_{plan}_{int(now_ist().timestamp())}"
    doc = {"user_id": uid, "username": uname, "plan": plan, "amount": PREMIUM_PLANS[plan]['price'], 'timestamp': now_ist_iso()}
    # store in payments collection if available
    if payments_coll:
        try:
            await payments_coll.insert_one({"_id": payment_id, **doc})
        except Exception as e:
            logger.error(f"Failed to persist payment: {e}")
    # notify admin
    admin_markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm Payment", callback_data=f"confirm_{payment_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{payment_id}")]])
    try:
        await context.bot.send_message(chat_id=ADMIN_USERNAME, text=f"New payment request @{uname} plan={plan}", reply_markup=admin_markup)
    except Exception:
        pass
    await query.edit_message_text("Payment request sent to admin.")

async def payment_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.username != ADMIN_USERNAME and query.from_user.id != ADMIN_USER_ID:
        await query.answer("Only admin", show_alert=True)
        return
    action, payment_id = query.data.split('_', 1)
    payment_doc = None
    if payments_coll:
        try:
            payment_doc = await payments_coll.find_one({"_id": payment_id})
        except Exception as e:
            logger.error(f"Read payment error: {e}")
    if not payment_doc:
        await query.edit_message_text("Payment not found.")
        return
    user_id = int(payment_doc['user_id'])
    plan = payment_doc['plan']
    amount = payment_doc['amount']
    if action == 'confirm':
        expires = now_ist() + timedelta(days=PREMIUM_PLANS[plan]['duration_days'])
        if user_id not in user_cache:
            ud = make_user_doc(user_id, payment_doc.get('username',''))
        else:
            ud = user_cache[user_id]
        ud['premium_expires'] = expires.isoformat()
        ud['premium_plan'] = plan
        await persist_user_to_db(ud)
        await record_event_audit('premium_activated', ud, extra={'plan':plan,'amount':amount})
        try:
            await context.bot.send_message(chat_id=user_id, text=f"🎉 Premium activated until {expires.isoformat()}")
        except Exception:
            pass
        await query.edit_message_text(f"Payment confirmed. Premium active until {expires.isoformat()}")
    else:
        await query.edit_message_text("Payment rejected")
        try:
            await context.bot.send_message(chat_id=user_id, text="Your payment was rejected.")
        except Exception:
            pass
    if payments_coll:
        try:
            await payments_coll.delete_one({"_id": payment_id})
        except Exception:
            pass

async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if caller.id != ADMIN_USER_ID:
        await update.message.reply_text("Only admin can use this command.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /allow <user_id> <days>")
        return
    try:
        target = int(args[0])
        days = int(args[1])
        expires = now_ist() + timedelta(days=days)
        if target not in user_cache:
            doc = make_user_doc(target)
        else:
            doc = user_cache[target]
        doc['premium_expires'] = expires.isoformat()
        doc['premium_plan'] = 'week' if days==7 else 'month' if days==30 else 'custom'
        await persist_user_to_db(doc)
        await record_event_audit('premium_granted_by_admin', doc, extra={'granted_by': caller.id, 'days': days})
        await update.message.reply_text(f"Granted premium to {target} until {expires.isoformat()}")
        try:
            await context.bot.send_message(chat_id=target, text=f"You were granted premium until {expires.isoformat()}")
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

# -----------------------
# Admin-only helpers
# -----------------------

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user:
            return
        if user.id != ADMIN_USER_ID and user.username != ADMIN_USERNAME:
            await update.message.reply_text("⛔ This command is admin-only.")
            return
        return await func(update, context)
    return wrapper

@admin_only
async def export_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_cache:
        await update.message.reply_text("No users to export.")
        return
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["user_id","username","first_name","count","date","is_new_user","joined_date","premium_expires","premium_plan","last_seen","last_command"]
    writer.writerow(headers)
    for uid, doc in user_cache.items():
        writer.writerow([doc.get(h, "") for h in headers])
    bio = io.BytesIO(output.getvalue().encode('utf-8'))
    bio.name = 'users_export.csv'
    bio.seek(0)
    try:
        await context.bot.send_document(chat_id=update.effective_user.id, document=InputFile(bio, filename='users_export.csv'))
    except Exception as e:
        await update.message.reply_text(f"Failed to send file: {e}")

@admin_only
async def get_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /get_user <user_id>")
        return
    try:
        uid = int(args[0])
    except Exception:
        await update.message.reply_text("Invalid user_id")
        return
    doc = user_cache.get(uid)
    if not doc:
        await update.message.reply_text("User not found")
        return
    pretty = json.dumps(doc, ensure_ascii=False, indent=2)
    if len(pretty) < 3500:
        await update.message.reply_text(f"<pre>{pretty}</pre>", parse_mode='HTML')
    else:
        bio = io.BytesIO(pretty.encode('utf-8'))
        bio.name = f'user_{uid}.json'
        bio.seek(0)
        await context.bot.send_document(chat_id=update.effective_user.id, document=InputFile(bio, filename=bio.name))

@admin_only
async def resync_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await load_users_from_db()
    await update.message.reply_text(f"Resynced {len(user_cache)} users from DB")

# -----------------------
# Group message handler
# -----------------------
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type not in ['group','supergroup']:
        return
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    uid = user.id
    uname = user.username or ""
    fname = user.first_name or ""
    text = update.message.text.strip()
    if not text.startswith('/'):
        return
    command = text.split()[0].lower()
    bot_cmds = ['/start','/status','/premium','/help','/test','/allow']
    if command in bot_cmds:
        if uid in user_cache:
            user_cache[uid]['last_seen'] = now_ist_iso()
            user_cache[uid]['last_command'] = command
            await persist_user_to_db(user_cache[uid])
        return
    # admin bypass
    if uid == ADMIN_USER_ID or user.username == ADMIN_USERNAME:
        return
    # check bot moderation
    bot_can_moderate = False
    try:
        bot_member = await context.bot.get_chat_member(update.effective_chat.id, context.bot.id)
        if bot_member.status in ['administrator','creator']:
            bot_can_moderate = True
    except Exception:
        pass
    # ensure user
    if uid not in user_cache:
        doc = make_user_doc(uid, uname, fname)
        await persist_user_to_db(doc)
        await record_event_audit('first_seen', doc)
    doc = user_cache[uid]
    # premium check
    if is_premium_active(doc):
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"💎 @{uname}: Premium - unlimited", reply_to_message_id=update.message.message_id)
        except Exception:
            pass
        doc['last_seen'] = now_ist_iso()
        doc['last_command'] = command
        await persist_user_to_db(doc)
        return
    # reset daily
    today_str = now_ist().date().isoformat()
    if doc.get('date') != today_str:
        doc['count'] = 0
        doc['date'] = today_str
        doc['is_new_user'] = doc.get('is_new_user', True) and (doc.get('joined_date','').split('T')[0] == today_str)
    joined_today = doc.get('joined_date','').split('T')[0] == now_ist().date().isoformat()
    limit = NEW_USER_MESSAGE_LIMIT if doc.get('is_new_user', True) and joined_today else DAILY_MESSAGE_LIMIT
    if doc.get('count',0) >= limit:
        await record_event_audit('limit_exceeded', doc, extra={'count': doc.get('count',0), 'limit': limit})
        try:
            if bot_can_moderate:
                await update.message.delete()
        except Exception:
            pass
        # check if target admin
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, uid)
            if member.status in ['administrator','creator']:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"ℹ️ @{uname} is admin and cannot be muted.")
                doc['last_seen'] = now_ist_iso()
                doc['last_command'] = command
                await persist_user_to_db(doc)
                return
        except Exception:
            pass
        if bot_can_moderate:
            until_utc = next_midnight_ist_as_utc()
            mute_perms = ChatPermissions(can_send_messages=False, can_send_media_messages=False, can_send_polls=False, can_send_other_messages=False, can_add_web_page_previews=False, can_change_info=False, can_invite_users=False, can_pin_messages=False)
            try:
                await context.bot.restrict_chat_member(chat_id=update.effective_chat.id, user_id=uid, permissions=mute_perms, until_date=until_utc)
                unmute_str = (now_ist().date() + timedelta(days=1)).isoformat() + ' 00:00 IST'
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⛔ @{uname} — DAILY LIMIT REACHED. Muted until {unmute_str}. Upgrade: /premium")
                doc['last_seen'] = now_ist_iso()
                doc['last_command'] = command
                await persist_user_to_db(doc)
                await record_event_audit('user_muted', doc, extra={'mute_until_utc': until_utc.isoformat()})
            except Exception as e:
                logger.error(f"Failed to restrict: {e}")
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⛔ @{uname} reached daily limit but I couldn't mute them — ensure I have restrict permission.")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⛔ @{uname} reached daily limit ({limit}) — I couldn't mute them (I am not admin).")
        return
    # increment and persist
    doc['count'] = doc.get('count',0) + 1
    doc['date'] = today_str
    doc['last_seen'] = now_ist_iso()
    doc['last_command'] = command
    await persist_user_to_db(doc)
    await record_event_audit('command_used', doc, extra={'count': doc['count'], 'remaining': max(limit - doc['count'], 0)})
    remaining = max(limit - doc['count'], 0)
    try:
        if remaining > 0:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"📊 @{uname}: {remaining}/{limit} searches remaining today", reply_to_message_id=update.message.message_id)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⚠️ @{uname}: This was your last search today! Next will be blocked. /premium", reply_to_message_id=update.message.message_id)
    except Exception:
        pass

# -----------------------
# Setup and run
# -----------------------
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start_cmd))
    app.add_handler(CommandHandler('status', status_cmd))
    app.add_handler(CommandHandler('premium', premium_cmd))
    app.add_handler(CommandHandler('help', lambda u,c: c.bot.send_message(chat_id=u.effective_chat.id, text='Commands: /start /status /premium /help /test /allow')))
    app.add_handler(CommandHandler('test', lambda u,c: c.bot.send_message(chat_id=u.effective_chat.id, text='Bot is running')))
    app.add_handler(CommandHandler('allow', allow_cmd))
    app.add_handler(CallbackQueryHandler(plan_selection_cb, pattern='^buy_'))
    app.add_handler(CallbackQueryHandler(payment_confirm_cb, pattern='^(confirm|reject)_'))
    app.add_handler(CommandHandler('export_users', export_users_cmd))
    app.add_handler(CommandHandler('get_user', get_user_cmd))
    app.add_handler(CommandHandler('resync', resync_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUPS), handle_group_message))
    return app

async def main():
    if not BOT_TOKEN:
        logger.error('BOT_TOKEN is not set in environment')
        return
    await init_mongo()
    await load_users_from_db()
    app = build_app()
    logger.info('Bot starting...')
    await app.run_polling()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Shutting down')
