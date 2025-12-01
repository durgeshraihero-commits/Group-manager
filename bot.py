#!/usr/bin/env python3
# FULL Group Manager Bot — MongoDB + Hardcoded Config + No Boolean Collection Errors

import os, io, csv, json, logging, asyncio
from datetime import datetime, timedelta, time, timezone
from typing import Dict, Any
import motor.motor_asyncio
from zoneinfo import ZoneInfo

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatPermissions, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ---------------------------------------------------
# CONFIG (HARDCODED)
# ---------------------------------------------------
BOT_TOKEN = "8597564579:AAGHr1Rqi8ZIqD_RA8PuslB1ob6bAjtOEhU"
MONGODB_URI = "mongodb+srv://prarthanaray147_db_user:fMuTkgFsaHa5NRIy@cluster0.txn8bv3.mongodb.net/tg_bot_db?retryWrites=true&w=majority"
MONGODB_DBNAME = "tg_bot_db"

ADMIN_USERNAME = "itsmezigzagzozo"
ADMIN_USER_ID = 6314556756

DAILY_MESSAGE_LIMIT = 1
NEW_USER_MESSAGE_LIMIT = 5

PREMIUM_PLANS = {
    "week": {"price": 300, "duration_days": 7},
    "month": {"price": 500, "duration_days": 30},
}

IST = ZoneInfo("Asia/Kolkata")
LOCAL_USERS_FILE = "users.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------
# MONGO
# ---------------------------------------------------
mongo_client = None
db = None
users_coll = None
payments_coll = None


async def init_mongo():
    global mongo_client, db, users_coll, payments_coll
    try:
        mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
        db = mongo_client[MONGODB_DBNAME]

        users_coll = db["users"]
        payments_coll = db["pending_payments"]

        await users_coll.create_index("user_id", unique=True)
        logger.info("Connected to MongoDB & index ready")
    except Exception as e:
        logger.error(f"MongoDB init error: {e}")
        users_coll = None
        payments_coll = None

# ---------------------------------------------------
# CACHE + TIME HELPERS
# ---------------------------------------------------
user_cache: Dict[int, Dict[str, Any]] = {}

now_ist = lambda: datetime.now(tz=IST)
now_ist_iso = lambda: now_ist().isoformat(timespec="seconds")


def next_midnight_ist_as_utc():
    now = now_ist()
    midnight = datetime.combine(now.date() + timedelta(days=1), time(0, 0), tzinfo=IST)
    return midnight.astimezone(timezone.utc)

# ---------------------------------------------------
# LOAD + SAVE USERS
# ---------------------------------------------------
async def load_users_from_db():
    user_cache.clear()

    if users_coll is not None:
        try:
            async for doc in users_coll.find({}):
                user_cache[int(doc["user_id"])] = doc
            logger.info(f"Loaded {len(user_cache)} users from MongoDB")
            return
        except Exception as e:
            logger.error(f"Failed loading from MongoDB: {e}")

    if os.path.exists(LOCAL_USERS_FILE):
        try:
            with open(LOCAL_USERS_FILE) as f:
                data = json.load(f)
            for k, v in data.items():
                user_cache[int(k)] = v
            logger.info(f"Loaded {len(user_cache)} users from local JSON")
        except Exception as e:
            logger.error(f"Local file load error: {e}")


async def persist_user_to_db(doc):
    uid = doc["user_id"]
    user_cache[uid] = doc

    if users_coll is not None:
        try:
            await users_coll.update_one(
                {"user_id": uid},
                {"$set": doc},
                upsert=True
            )
            return
        except Exception as e:
            logger.error(f"Mongo upsert error: {e}")

    try:
        with open(LOCAL_USERS_FILE, "w") as f:
            json.dump({str(k): v for k, v in user_cache.items()}, f, indent=2)
    except:
        pass

# ---------------------------------------------------
# USER DOC + PREMIUM
# ---------------------------------------------------
def make_user_doc(uid, uname, fname):
    return {
        "user_id": uid,
        "username": uname,
        "first_name": fname,
        "count": 0,
        "date": now_ist().date().isoformat(),
        "is_new_user": True,
        "joined_date": now_ist_iso(),
        "premium_expires": "",
        "premium_plan": "",
        "last_seen": now_ist_iso(),
        "last_command": "",
    }


def is_premium_active(doc):
    try:
        if not doc.get("premium_expires"):
            return False
        return now_ist() < datetime.fromisoformat(doc["premium_expires"])
    except:
        return False


async def record_event(event, doc):
    await persist_user_to_db(doc)

# ---------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------
async def start_cmd(update, context):
    u = update.effective_user
    uid = u.id
    uname = u.username or ""
    fname = u.first_name or ""

    if uid not in user_cache:
        doc = make_user_doc(uid, uname, fname)
        await persist_user_to_db(doc)
        welcome = "\n🎁 Welcome Bonus Activated!"
    else:
        doc = user_cache[uid]
        doc["username"] = uname
        doc["first_name"] = fname
        doc["last_seen"] = now_ist_iso()
        await persist_user_to_db(doc)
        welcome = ""

    premium = "✅ PREMIUM" if is_premium_active(doc) else "🆓 FREE"
    await update.message.reply_text(
        f"👋 Hello!\nYour status: {premium}{welcome}\n\nUse /status to see limits."
    )


async def status_cmd(update, context):
    u = update.effective_user
    uid = u.id

    if uid not in user_cache:
        return await update.message.reply_text("Use /start first.")

    doc = user_cache[uid]
    today = now_ist().date().isoformat()

    if doc["date"] != today:
        doc["count"] = 0
        doc["date"] = today
        await persist_user_to_db(doc)

    if is_premium_active(doc):
        return await update.message.reply_text(
            f"💎 PREMIUM\nExpires: {doc['premium_expires']}"
        )

    joined_today = doc["joined_date"].split("T")[0] == today
    limit = NEW_USER_MESSAGE_LIMIT if (doc["is_new_user"] and joined_today) else DAILY_MESSAGE_LIMIT

    await update.message.reply_text(f"🆓 Free User\nUsed {doc['count']}/{limit}")
  # ---------------------------------------------------
# PREMIUM MENU
# ---------------------------------------------------
async def premium_cmd(update, context):
    kb = [
        [InlineKeyboardButton("📅 Weekly ₹300", callback_data="buy_week")],
        [InlineKeyboardButton("📆 Monthly ₹500", callback_data="buy_month")],
        [InlineKeyboardButton("💬 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")]
    ]
    await update.message.reply_text("Select a premium plan:", reply_markup=InlineKeyboardMarkup(kb))


# ---------------------------------------------------
# PREMIUM PURCHASE CALLBACK
# ---------------------------------------------------
async def plan_cb(update, context):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    plan = q.data.replace("buy_", "")

    if plan not in PREMIUM_PLANS:
        return await q.edit_message_text("❌ Invalid plan")

    price = PREMIUM_PLANS[plan]["price"]

    payment_id = f"{uid}_{plan}_{int(now_ist().timestamp())}"

    # Store payment request
    if payments_coll is not None:
        await payments_coll.insert_one({
            "_id": payment_id,
            "user_id": uid,
            "plan": plan,
            "amount": price,
            "time": now_ist_iso(),
        })

    # Notify admin
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USERNAME,
            text=f"💰 Payment Request\nUser: {uid}\nPlan: {plan}\nAmount: ₹{price}\nPayment ID: {payment_id}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{payment_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{payment_id}")
                ]
            ])
        )
    except:
        pass

    await q.edit_message_text(
        f"💳 Payment Request Sent\nPay admin and wait for approval."
    )


# ---------------------------------------------------
# ADMIN CONFIRMATION CALLBACK
# ---------------------------------------------------
async def pay_confirm_cb(update, context):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_USER_ID:
        return await q.answer("⛔ Admin only", show_alert=True)

    action, payment_id = q.data.split("_", 1)

    # Fetch pending payment
    pay = None
    if payments_coll is not None:
        pay = await payments_coll.find_one({"_id": payment_id})

    if not pay:
        return await q.edit_message_text("❌ Payment not found")

    uid = pay["user_id"]
    plan = pay["plan"]

    if action == "confirm":
        days = PREMIUM_PLANS[plan]["duration_days"]
        expires = now_ist() + timedelta(days=days)

        doc = user_cache.get(uid, make_user_doc(uid, "", ""))
        doc["premium_expires"] = expires.isoformat()
        doc["premium_plan"] = plan

        await persist_user_to_db(doc)

        await context.bot.send_message(
            chat_id=uid,
            text=f"🎉 PREMIUM ACTIVATED!\nPlan: {plan}\nExpires: {expires}"
        )

        await q.edit_message_text("✅ Payment Confirmed")
    else:
        await q.edit_message_text("❌ Payment Rejected")

    if payments_coll is not None:
        await payments_coll.delete_one({"_id": payment_id})


# ---------------------------------------------------
# ADMIN GIVE PREMIUM /allow
# ---------------------------------------------------
async def allow_cmd(update, context):
    if update.effective_user.id != ADMIN_USER_ID:
        return await update.message.reply_text("⛔ Admin only")

    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage:\n/allow <user_id> <days>")

    uid = int(args[0])
    days = int(args[1])
    expires = now_ist() + timedelta(days=days)

    doc = user_cache.get(uid, make_user_doc(uid, "", ""))
    doc["premium_expires"] = expires.isoformat()
    doc["premium_plan"] = f"custom_{days}"

    await persist_user_to_db(doc)

    await update.message.reply_text("✅ Premium Granted")


# ---------------------------------------------------
# GROUP MESSAGE HANDLER
# ---------------------------------------------------
async def handle_group(update, context):
    if update.effective_chat.type not in ["group", "supergroup"]:
        return

    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()
    if not text.startswith("/"):
        return  # only count commands

    u = update.effective_user
    uid = u.id
    uname = u.username or ""
    fname = u.first_name or ""

    # Admin bypasses
    if uid == ADMIN_USER_ID or u.username == ADMIN_USERNAME:
        return

    # Ensure user exists
    if uid not in user_cache:
        doc = make_user_doc(uid, uname, fname)
        await persist_user_to_db(doc)

    doc = user_cache[uid]
    today = now_ist().date().isoformat()

    # Reset daily
    if doc["date"] != today:
        doc["count"] = 0
        doc["date"] = today
        await persist_user_to_db(doc)

    # Premium bypass
    if is_premium_active(doc):
        return

    # Determine limit
    joined_today = doc["joined_date"].split("T")[0] == today
    limit = NEW_USER_MESSAGE_LIMIT if (doc["is_new_user"] and joined_today) else DAILY_MESSAGE_LIMIT

    # LIMIT REACHED
    if doc["count"] >= limit:
        try:
            await msg.delete()
        except:
            pass

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⛔ @{uname} DAILY LIMIT REACHED\nUpgrade to premium!",
        )
        return

    # Increase count
    doc["count"] += 1
    doc["last_seen"] = now_ist_iso()
    doc["last_command"] = text
    await persist_user_to_db(doc)

    remaining = limit - doc["count"]

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"📊 @{uname}: {remaining}/{limit} remaining today",
        reply_to_message_id=msg.message_id,
  )
# ---------------------------------------------------
# Admin-only helpers
# ---------------------------------------------------
def admin_only(func):
    async def wrapper(update, context):
        user = update.effective_user
        if not user:
            return
        if user.id != ADMIN_USER_ID and user.username != ADMIN_USERNAME:
            return await update.message.reply_text("⛔ This command is admin-only.")
        return await func(update, context)
    return wrapper

@admin_only
async def export_users_cmd(update, context):
    if not user_cache:
        return await update.message.reply_text("No users to export.")
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["user_id","username","first_name","count","date","is_new_user","joined_date","premium_expires","premium_plan","last_seen","last_command"]
    writer.writerow(headers)
    for uid, doc in user_cache.items():
        writer.writerow([doc.get(h,"") for h in headers])
    bio = io.BytesIO(output.getvalue().encode("utf-8"))
    bio.name = "users_export.csv"
    bio.seek(0)
    try:
        await context.bot.send_document(chat_id=update.effective_user.id, document=InputFile(bio, filename="users_export.csv"))
    except Exception as e:
        await update.message.reply_text(f"Failed to send file: {e}")

@admin_only
async def get_user_cmd(update, context):
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: /get_user <user_id>")
    try:
        uid = int(args[0])
    except:
        return await update.message.reply_text("Invalid user id")
    doc = user_cache.get(uid)
    if not doc:
        return await update.message.reply_text("User not found")
    pretty = json.dumps(doc, ensure_ascii=False, indent=2)
    if len(pretty) < 3500:
        return await update.message.reply_text(f"<pre>{pretty}</pre>", parse_mode="HTML")
    bio = io.BytesIO(pretty.encode("utf-8"))
    bio.name = f"user_{uid}.json"
    bio.seek(0)
    await context.bot.send_document(chat_id=update.effective_user.id, document=InputFile(bio, filename=bio.name))

@admin_only
async def resync_cmd(update, context):
    await load_users_from_db()
    await update.message.reply_text(f"Resynced {len(user_cache)} users from DB")

# ---------------------------------------------------
# Build application & register handlers
# ---------------------------------------------------
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("allow", allow_cmd))

    # Payment callbacks
    app.add_handler(CallbackQueryHandler(plan_cb, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(pay_confirm_cb, pattern="^(confirm|reject)_"))

    # Admin utilities
    app.add_handler(CommandHandler("export_users", export_users_cmd))
    app.add_handler(CommandHandler("get_user", get_user_cmd))
    app.add_handler(CommandHandler("resync", resync_cmd))

    # Group message handler
    app.add_handler(
    MessageHandler(
        filters.TEXT & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP),
        handle_group
    )
                                       )
    return app

# ---------------------------------------------------
# Main / startup
# ---------------------------------------------------
async def main():
    logger.info("Starting bot setup...")
    await init_mongo()
    await load_users_from_db()
    app = build_app()
    logger.info("Bot started — polling.")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped (KeyboardInterrupt)")
