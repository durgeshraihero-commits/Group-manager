# bot.py
import logging
import os
import json
import io
import asyncio
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

import pytz
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMemberAdministrator,
    ChatMemberOwner,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# -----------------------
# Configuration (env)
# -----------------------
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8597564579:AAGHr1Rqi8ZIqD_RA8PuslB1ob6bAjtOEhU')
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb+srv://prarthanaray147_db_user:fMuTkgFsaHa5NRIy@cluster0.txn8bv3.mongodb.net/tg_bot_db?retryWrites=true&w=majority')
MONGODB_DBNAME = os.environ.get('MONGODB_DBNAME', 'tg_bot_db')
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'itsmezigzagzozo')
ADMIN_USER_ID = int(os.environ.get('ADMIN_USER_ID', '6314556756'))
DAILY_MESSAGE_LIMIT = int(os.environ.get('DAILY_MESSAGE_LIMIT', '1'))
NEW_USER_MESSAGE_LIMIT = int(os.environ.get('NEW_USER_MESSAGE_LIMIT', '5'))
PORT = int(os.environ.get('PORT', '10000'))

KOLKATA_TZ = pytz.timezone('Asia/Kolkata')

PREMIUM_PLANS = {
    "week": {"price": 300, "duration_days": 7, "name": "Weekly"},
    "month": {"price": 500, "duration_days": 30, "name": "Monthly"}
}

# -----------------------
# Globals
# -----------------------
mongo_client = None
db = None
users_collection = None
commands_collection = None
pending_payments = {}  # in-memory pending payment store (simple)

# -----------------------
# Logging
# -----------------------
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------
# MongoDB init
# -----------------------
async def init_mongodb():
    global mongo_client, db, users_collection, commands_collection
    try:
        mongo_client = AsyncIOMotorClient(MONGODB_URI)
        db = mongo_client[MONGODB_DBNAME]
        users_collection = db['users']
        commands_collection = db['commands']
        # Indexes - create if not exists
        await users_collection.create_index('user_id', unique=True)
        await commands_collection.create_index([('user_id', 1), ('timestamp', -1)])
        logger.info("✅ MongoDB connected!")
    except Exception as e:
        logger.error(f"❌ MongoDB error: {e}")
        raise

# -----------------------
# Time helpers
# -----------------------
def get_kolkata_time():
    return datetime.now(KOLKATA_TZ)

def get_midnight_kolkata():
    now = get_kolkata_time()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight

# -----------------------
# User helpers (DB)
# -----------------------
async def get_or_create_user(user_id, username, first_name):
    user = await users_collection.find_one({'user_id': user_id})
    if not user:
        now = get_kolkata_time()
        user = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'registration_time': now,
            'is_new_user': True,
            'message_count': 0,
            'last_reset': now.date().isoformat(),
            'premium_history': [],
            'current_premium': None,
            'total_commands': 0
        }
        await users_collection.insert_one(user)
        logger.info(f"New user created: {user_id}")
    return user

async def update_user_info(user_id, username, first_name):
    await users_collection.update_one({'user_id': user_id}, {'$set': {'username': username, 'first_name': first_name}})

async def log_command(user_id, username, command, chat_id):
    try:
        await commands_collection.insert_one({'user_id': user_id, 'username': username, 'command': command, 'timestamp': get_kolkata_time(), 'chat_id': chat_id})
        await users_collection.update_one({'user_id': user_id}, {'$inc': {'total_commands': 1}})
    except Exception as e:
        logger.error(f"Failed to log command: {e}")

async def reset_daily_count_if_needed(user_id):
    user = await users_collection.find_one({'user_id': user_id})
    if not user:
        return
    today = get_kolkata_time().date().isoformat()
    if user.get('last_reset') != today:
        await users_collection.update_one({'user_id': user_id}, {'$set': {'message_count': 0, 'last_reset': today, 'is_new_user': False}})

async def is_premium(user_id):
    user = await users_collection.find_one({'user_id': user_id})
    if not user:
        return False
    premium = user.get('current_premium')
    if not premium:
        return False
    expires = premium.get('expires')
    if expires:
        # If stored as datetime -> compare; if string, try parse
        if isinstance(expires, str):
            try:
                expires_dt = datetime.fromisoformat(expires)
            except Exception:
                return False
        else:
            expires_dt = expires
        # ensure timezone awareness
        if expires_dt.tzinfo is None:
            # treat as kolkata tz
            expires_dt = KOLKATA_TZ.localize(expires_dt)
        if get_kolkata_time() < expires_dt:
            return True
        else:
            # expired -> clear
            await users_collection.update_one({'user_id': user_id}, {'$set': {'current_premium': None}})
            return False
    return False

async def get_user_message_limit(user_id):
    user = await users_collection.find_one({'user_id': user_id})
    if not user:
        return DAILY_MESSAGE_LIMIT
    if user.get('is_new_user', False):
        return NEW_USER_MESSAGE_LIMIT
    return DAILY_MESSAGE_LIMIT

# -----------------------
# Command handlers
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    user = await get_or_create_user(user_id, username, first_name)
    await update_user_info(user_id, username, first_name)
    premium_status = "✅ PREMIUM" if await is_premium(user_id) else "🆓 FREE"
    welcome_bonus = f"\n🎁 Welcome Bonus: {NEW_USER_MESSAGE_LIMIT} searches!" if user.get('is_new_user') else ""
    await update.message.reply_text(
        f"👋 Welcome!\n\nStatus: {premium_status}{welcome_bonus}\n\n"
        f"🔍 Only / commands counted\n\n"
        f"📊 Free: {NEW_USER_MESSAGE_LIMIT} (new) / {DAILY_MESSAGE_LIMIT} (regular)\n"
        f"💎 Premium: Unlimited\n\n"
        f"Plans: Weekly ₹300 | Monthly ₹500\n\n"
        f"/status /premium /help"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    user = await get_or_create_user(user_id, username, first_name)
    await reset_daily_count_if_needed(user_id)
    user = await users_collection.find_one({'user_id': user_id})
    if await is_premium(user_id):
        premium = user.get('current_premium', {})
        expires = premium.get('expires')
        plan = premium.get('plan', 'custom')
        if expires:
            expires_kolkata = expires if isinstance(expires, datetime) else (datetime.fromisoformat(expires) if isinstance(expires, str) else None)
            if expires_kolkata and expires_kolkata.tzinfo is None:
                expires_kolkata = KOLKATA_TZ.localize(expires_kolkata)
            if expires_kolkata:
                days_left = (expires_kolkata - get_kolkata_time()).days
                await update.message.reply_text(
                    f"💎 PREMIUM\n\n"
                    f"Plan: {PREMIUM_PLANS.get(plan, {}).get('name', 'Custom')}\n"
                    f"Expires: {expires_kolkata.strftime('%Y-%m-%d %H:%M')} IST\n"
                    f"Days: {days_left}\n"
                    f"Commands: {user.get('total_commands', 0)}\n\n"
                    f"/premium to renew"
                )
                return
    # Not premium
    count = user.get('message_count', 0)
    limit = await get_user_message_limit(user_id)
    remaining = limit - count
    user_type = "NEW 🎁" if user.get('is_new_user') else "FREE"
    midnight = get_midnight_kolkata()
    await update.message.reply_text(
        f"🆓 {user_type}\n\n"
        f"Used: {count}/{limit}\n"
        f"Remaining: {remaining}\n"
        f"Resets: {midnight.strftime('%H:%M')} IST\n"
        f"Commands: {user.get('total_commands', 0)}\n\n"
        f"/premium to upgrade"
    )

async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("📅 Weekly ₹300", callback_data="buy_week")],
        [InlineKeyboardButton("📆 Monthly ₹500", callback_data="buy_month")],
        [InlineKeyboardButton("💬 Contact", url=f"https://t.me/{ADMIN_USERNAME}")]
    ]
    status_text = "💎 Premium Plans:\n\n"
    if await is_premium(user_id):
        user = await users_collection.find_one({'user_id': user_id})
        premium = user.get('current_premium', {})
        expires = premium.get('expires')
        if expires:
            days_left = (expires.replace(tzinfo=KOLKATA_TZ) - get_kolkata_time()).days if isinstance(expires, datetime) else 0
            status_text = f"✅ Premium! Expires in {days_left} days\n\n"
    await update.message.reply_text(
        f"{status_text}📅 Weekly: ₹300 (7 days)\n📆 Monthly: ₹500 (30 days)",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_name = query.from_user.username or query.from_user.first_name
    plan = query.data.replace("buy_", "")
    if plan not in PREMIUM_PLANS:
        await query.edit_message_text("❌ Invalid plan")
        return
    plan_info = PREMIUM_PLANS[plan]
    payment_id = f"{user_id}_{plan}_{datetime.utcnow().timestamp()}"
    pending_payments[payment_id] = {"user_id": user_id, "user_name": user_name, "plan": plan, "amount": plan_info["price"], "timestamp": get_kolkata_time().isoformat()}
    admin_keyboard = [[InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{payment_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{payment_id}")]]
    try:
        # send payment request to admin (by username or id)
        admin_target = ADMIN_USER_ID if ADMIN_USER_ID else f"@{ADMIN_USERNAME}"
        await context.bot.send_message(
            chat_id=admin_target,
            text=f"💰 Payment Request\n\nUser: @{user_name}\nID: {user_id}\nPlan: {plan_info['name']}\nAmount: ₹{plan_info['price']}",
            reply_markup=InlineKeyboardMarkup(admin_keyboard)
        )
    except Exception as e:
        logger.error(f"Failed to notify admin of payment: {e}")
        await query.edit_message_text("❌ Error. Contact admin.")
        return
    await query.edit_message_text(
        f"💳 Payment: ₹{plan_info['price']}\n\nSend to @{ADMIN_USERNAME}\nWait for confirmation",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Contact", url=f"https://t.me/{ADMIN_USERNAME}")]])
    )

async def handle_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Only admin can confirm
    if query.from_user.id != ADMIN_USER_ID:
        await query.answer("⛔ Admin only", show_alert=True)
        return
    data = query.data
    action, payment_id = data.split("_", 1)
    if payment_id not in pending_payments:
        await query.edit_message_text("❌ Expired or invalid")
        return
    payment_info = pending_payments[payment_id]
    user_id = payment_info["user_id"]
    user_name = payment_info["user_name"]
    plan = payment_info["plan"]
    amount = payment_info["amount"]
    if action == "confirm":
        duration_days = PREMIUM_PLANS[plan]["duration_days"]
        expires = get_kolkata_time() + timedelta(days=duration_days)
        premium_record = {'plan': plan, 'expires': expires, 'activated': get_kolkata_time(), 'amount': amount, 'duration_days': duration_days}
        await users_collection.update_one({'user_id': user_id}, {'$set': {'current_premium': premium_record}, '$push': {'premium_history': premium_record}}, upsert=True)
        await query.edit_message_text(f"✅ CONFIRMED\n\nUser: @{user_name}\nPlan: {PREMIUM_PLANS[plan]['name']}\nAmount: ₹{amount}")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"🎉 PREMIUM ACTIVATED!\n\nPlan: {PREMIUM_PLANS[plan]['name']}\nDuration: {duration_days} days\n\n/status")
        except Exception:
            pass
    else:
        await query.edit_message_text(f"❌ REJECTED\n\nUser: @{user_name}")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"❌ Payment rejected\n\nContact @{ADMIN_USERNAME}")
        except Exception:
            pass
    del pending_payments[payment_id]

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ Admin only")
        return
    try:
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /approve <user_id> <days>")
            return
        target_user_id = int(context.args[0])
        days = int(context.args[1])
        if days <= 0:
            await update.message.reply_text("❌ Days > 0")
            return
        expires = get_kolkata_time() + timedelta(days=days)
        plan = "week" if days == 7 else "month" if days == 30 else "custom"
        premium_record = {'plan': plan, 'expires': expires, 'activated': get_kolkata_time(), 'amount': 0, 'duration_days': days, 'approved_by_admin': True}
        user = await users_collection.find_one({'user_id': target_user_id})
        if not user:
            await users_collection.insert_one({'user_id': target_user_id, 'username': None, 'first_name': None, 'registration_time': get_kolkata_time(), 'is_new_user': False, 'message_count': 0, 'last_reset': get_kolkata_time().date().isoformat(), 'premium_history': [premium_record], 'current_premium': premium_record, 'total_commands': 0})
        else:
            await users_collection.update_one({'user_id': target_user_id}, {'$set': {'current_premium': premium_record}, '$push': {'premium_history': premium_record}})
        await update.message.reply_text(f"✅ APPROVED\n\nID: {target_user_id}\nDays: {days}")
        try:
            await context.bot.send_message(chat_id=target_user_id, text=f"🎉 PREMIUM by ADMIN!\n\nDays: {days}\n\n/status")
        except Exception:
            await update.message.reply_text("⚠️ Couldn't notify user")
    except ValueError:
        await update.message.reply_text("❌ Invalid input")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def database_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ Admin only")
        return
    try:
        users = await users_collection.find().to_list(length=None)
        export_data = []
        for user in users:
            user_data = {
                'user_id': user.get('user_id'),
                'username': user.get('username'),
                'first_name': user.get('first_name'),
                'registration_time': user.get('registration_time').isoformat() if user.get('registration_time') else None,
                'is_new_user': user.get('is_new_user'),
                'message_count': user.get('message_count'),
                'last_reset': user.get('last_reset'),
                'total_commands': user.get('total_commands', 0),
                'current_premium': None,
                'premium_history': []
            }
            if user.get('current_premium'):
                premium = user['current_premium']
                user_data['current_premium'] = {
                    'plan': premium.get('plan'),
                    'expires': premium.get('expires').isoformat() if premium.get('expires') else None,
                    'activated': premium.get('activated').isoformat() if premium.get('activated') else None,
                    'amount': premium.get('amount'),
                    'duration_days': premium.get('duration_days')
                }
            for premium in user.get('premium_history', []):
                user_data['premium_history'].append({
                    'plan': premium.get('plan'),
                    'expires': premium.get('expires').isoformat() if premium.get('expires') else None,
                    'activated': premium.get('activated').isoformat() if premium.get('activated') else None,
                    'amount': premium.get('amount'),
                    'duration_days': premium.get('duration_days')
                })
            export_data.append(user_data)
        json_data = json.dumps(export_data, indent=2, ensure_ascii=False)
        file_buffer = io.BytesIO(json_data.encode('utf-8'))
        file_buffer.name = f'db_{get_kolkata_time().strftime("%Y%m%d_%H%M%S")}.json'
        await update.message.reply_document(document=file_buffer, filename=file_buffer.name, caption=f"📊 DB Export\n\nUsers: {len(export_data)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📚 HELP\n\n"
        f"Only / commands counted\n"
        f"Free: {NEW_USER_MESSAGE_LIMIT} (new) / {DAILY_MESSAGE_LIMIT} (regular)\n"
        f"Resets: midnight IST\n"
        f"Blocked until midnight if exceeded\n\n"
        f"/start /status /premium /help\n\n"
        f"Contact: @{ADMIN_USERNAME}"
    )

# -----------------------
# Group message handler (core logic)
# -----------------------
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("=== MESSAGE RECEIVED ===")
        chat_type = update.effective_chat.type if update.effective_chat else 'unknown'
        logger.info(f"Chat type: {chat_type}")
        logger.info(f"Message: {update.message.text if update.message else 'None'}")

        # Only process group/supergroup messages for counting
        if chat_type not in ["group", "supergroup"]:
            logger.info("Not a group message, ignoring")
            return

        if not update.message or not update.message.text:
            logger.info("No message text, ignoring")
            return

        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        first_name = update.effective_user.first_name
        message_text = update.message.text.strip()

        logger.info(f"User: {user_id} (@{username})")
        logger.info(f"Message text: {message_text}")

        if not message_text.startswith('/'):
            logger.info("Not a command, ignoring")
            return

        command = message_text.split()[0].lower()
        logger.info(f"Command extracted: {command}")

        # Ignore bot management commands that should not be counted in groups
        if command in ['/start', '/status', '/premium', '/help', '/approve', '/database']:
            logger.info("Bot management command, ignoring")
            return

        # Admin bypass
        if user_id == ADMIN_USER_ID:
            logger.info("Admin user, unlimited access")
            return

        # Check bot permissions but DO NOT abort processing if missing - only toggle delete ability
        can_delete = False
        try:
            bot_member = await context.bot.get_chat_member(update.effective_chat.id, context.bot.id)
            logger.info(f"Bot member status: {bot_member.status}")
            # If admin/owner -> check attribute
            if isinstance(bot_member, (ChatMemberAdministrator, ChatMemberOwner)) or bot_member.status in ["administrator", "creator"]:
                can_delete = getattr(bot_member, 'can_delete_messages', True)
            else:
                can_delete = getattr(bot_member, 'can_delete_messages', False)
            if not can_delete:
                logger.warning("Bot cannot delete messages — will skip deletions but continue processing.")
        except Exception as e:
            logger.error(f"Error checking bot status: {e}")
            can_delete = False

        # Ensure user in DB
        logger.info("Getting/creating user...")
        user = await get_or_create_user(user_id, username, first_name)
        await update_user_info(user_id, username, first_name)

        # Log command (DB)
        logger.info("Logging command to database...")
        await log_command(user_id, username, command, update.effective_chat.id)
        logger.info("Command logged successfully!")

        # Premium check
        is_premium_user = await is_premium(user_id)
        logger.info(f"Premium status: {is_premium_user}")
        if is_premium_user:
            logger.info("User is premium, announcing in group")
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"💎 @{username}: Premium Member - Unlimited searches!",
                    reply_to_message_id=update.message.message_id
                )
            except Exception as e:
                logger.error(f"Failed to send premium msg: {e}")
            return

        # Reset daily count if needed
        logger.info("Resetting daily count if needed...")
        await reset_daily_count_if_needed(user_id)

        # Re-fetch user
        user = await users_collection.find_one({'user_id': user_id})
        limit = await get_user_message_limit(user_id)
        count = user.get('message_count', 0)
        logger.info(f"User count: {count}/{limit}")

        # If limit exceeded -> delete (if possible) and notify
        if count >= limit:
            logger.info("LIMIT EXCEEDED! Will block user until midnight.")
            midnight = get_midnight_kolkata()
            try:
                if can_delete:
                    try:
                        await update.message.delete()
                        logger.info("User message deleted")
                    except Exception as e:
                        logger.error(f"Failed to delete message: {e}")
                else:
                    logger.info("Skipping deletion due to missing permission.")
                block_msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"⛔ @{username} - BLOCKED UNTIL MIDNIGHT\n\n"
                         f"You've used {limit}/{limit} searches today.\n"
                         f"You cannot send ANY commands until midnight.\n\n"
                         f"🕐 Resets at: {midnight.strftime('%H:%M')} IST\n\n"
                         f"💎 Upgrade to Premium for unlimited searches!\n"
                         f"Use /premium to upgrade now!",
                    reply_to_message_id=None
                )
                logger.info("Block notification sent!")
            except Exception as e:
                logger.error(f"Error blocking user: {e}")
            return

        # Increment user's message count
        logger.info("Incrementing message count...")
        try:
            await users_collection.update_one({'user_id': user_id}, {'$inc': {'message_count': 1}})
            logger.info("Count incremented!")
        except Exception as e:
            logger.error(f"Failed to increment count: {e}")

        remaining = limit - (count + 1)
        is_new = user.get('is_new_user', False)
        logger.info(f"Remaining after increment: {remaining}")

        # Send a status message or last warning
        try:
            if remaining > 0:
                status_msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"📊 @{username}: {remaining}/{limit} search{'es' if remaining != 1 else ''} remaining today{' 🎁' if is_new else ''}",
                    reply_to_message_id=update.message.message_id
                )
                logger.info("Status message sent!")
            else:
                midnight = get_midnight_kolkata()
                warning_msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"⚠️ @{username}: This was your last search for today!\n"
                         f"Next command will be blocked until {midnight.strftime('%H:%M')} IST.\n"
                         f"💎 Upgrade to Premium: /premium",
                    reply_to_message_id=update.message.message_id
                )
                logger.info("Warning message sent!")
        except Exception as e:
            logger.error(f"Failed to send status/warning: {e}")

    except Exception as e:
        logger.error(f"CRITICAL ERROR in handle_group_message: {e}", exc_info=True)

# -----------------------
# Main / Run
# -----------------------
def start_health_server(port):
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot running!')
        def log_message(self, format, *args):
            pass

    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    logger.info(f"Health check server started on port {port}")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # init db first
    loop.run_until_complete(init_mongodb())

    # health check (useful for Render)
    start_health_server(PORT)
    logger.info(f"Health check: {PORT}")

    application = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("premium", premium_menu))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("database", database_command))
    application.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern="^(confirm|reject)_"))
    application.add_handler(MessageHandler(filters.ALL & (~filters.User(bot_id=int(BOT_TOKEN.split(':')[0]))), handle_group_message))

    logger.info("🚀 Bot Initialized!")
    logger.info(f"Time: {get_kolkata_time().strftime('%Y-%m-%d %H:%M:%S')} IST")

    # IMPORTANT: delete any webhook to avoid 409 Conflict when polling.
    try:
        loop.run_until_complete(application.bot.delete_webhook(drop_pending_updates=True))
        logger.info("Webhook removed (if any). Starting polling.")
    except Exception as e:
        logger.warning(f"Couldn't delete webhook (non-fatal): {e}")

    # Start polling (blocking call)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
