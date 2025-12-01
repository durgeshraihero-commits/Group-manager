import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
import pytz
import json
import io

# Configuration from environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8597564579:AAGHr1Rqi8ZIqD_RA8PuslB1ob6bAjtOEhU')
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb+srv://prarthanaray147_db_user:fMuTkgFsaHa5NRIy@cluster0.txn8bv3.mongodb.net/tg_bot_db?retryWrites=true&w=majority')
MONGODB_DBNAME = os.environ.get('MONGODB_DBNAME', 'tg_bot_db')
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'itsmezigzagzozo')
ADMIN_USER_ID = int(os.environ.get('ADMIN_USER_ID', '6314556756'))
DAILY_MESSAGE_LIMIT = int(os.environ.get('DAILY_MESSAGE_LIMIT', '1'))
NEW_USER_MESSAGE_LIMIT = int(os.environ.get('NEW_USER_MESSAGE_LIMIT', '5'))

# Timezone
KOLKATA_TZ = pytz.timezone('Asia/Kolkata')

# Premium Plans
PREMIUM_PLANS = {
    "week": {"price": 300, "duration_days": 7, "name": "Weekly"},
    "month": {"price": 500, "duration_days": 30, "name": "Monthly"}
}

# MongoDB client
mongo_client = None
db = None
users_collection = None
commands_collection = None
pending_payments = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_mongodb():
    """Initialize MongoDB connection"""
    global mongo_client, db, users_collection, commands_collection
    
    try:
        mongo_client = AsyncIOMotorClient(MONGODB_URI)
        db = mongo_client[MONGODB_DBNAME]
        users_collection = db['users']
        commands_collection = db['commands']
        
        # Create indexes
        await users_collection.create_index('user_id', unique=True)
        await commands_collection.create_index([('user_id', 1), ('timestamp', -1)])
        
        logger.info("✅ MongoDB connected successfully!")
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        raise

def get_kolkata_time():
    """Get current time in Asia/Kolkata timezone"""
    return datetime.now(KOLKATA_TZ)

def get_midnight_kolkata():
    """Get next midnight in Asia/Kolkata timezone"""
    now = get_kolkata_time()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight

async def get_or_create_user(user_id, username, first_name):
    """Get user from database or create new one"""
    user = await users_collection.find_one({'user_id': user_id})
    
    if not user:
        # Create new user
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
        logger.info(f"New user created: {user_id} (@{username})")
    
    return user

async def update_user_info(user_id, username, first_name):
    """Update user info if changed"""
    await users_collection.update_one(
        {'user_id': user_id},
        {'$set': {
            'username': username,
            'first_name': first_name
        }}
    )

async def log_command(user_id, username, command, chat_id):
    """Log command to database"""
    await commands_collection.insert_one({
        'user_id': user_id,
        'username': username,
        'command': command,
        'timestamp': get_kolkata_time(),
        'chat_id': chat_id
    })
    
    # Increment total commands
    await users_collection.update_one(
        {'user_id': user_id},
        {'$inc': {'total_commands': 1}}
    )

async def reset_daily_count(user_id):
    """Reset message count if it's a new day (Asia/Kolkata time)"""
    user = await users_collection.find_one({'user_id': user_id})
    if not user:
        return
    
    today = get_kolkata_time().date().isoformat()
    
    if user.get('last_reset') != today:
        # New day - reset count
        await users_collection.update_one(
            {'user_id': user_id},
            {'$set': {
                'message_count': 0,
                'last_reset': today,
                'is_new_user': False  # No longer new user after first day
            }}
        )

async def is_premium(user_id):
    """Check if user has active premium"""
    user = await users_collection.find_one({'user_id': user_id})
    if not user or not user.get('current_premium'):
        return False
    
    premium = user['current_premium']
    expires = premium.get('expires')
    
    if expires and isinstance(expires, datetime):
        if get_kolkata_time() < expires.replace(tzinfo=KOLKATA_TZ):
            return True
        else:
            # Premium expired - remove it
            await users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'current_premium': None}}
            )
    
    return False

async def get_user_message_limit(user_id):
    """Get message limit for user"""
    user = await users_collection.find_one({'user_id': user_id})
    if not user:
        return DAILY_MESSAGE_LIMIT
    
    if user.get('is_new_user', False):
        return NEW_USER_MESSAGE_LIMIT
    
    return DAILY_MESSAGE_LIMIT

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    user = await get_or_create_user(user_id, username, first_name)
    await update_user_info(user_id, username, first_name)
    
    premium_status = "✅ PREMIUM" if await is_premium(user_id) else "🆓 FREE"
    
    welcome_bonus = ""
    if user.get('is_new_user'):
        welcome_bonus = f"\n🎁 Welcome Bonus: {NEW_USER_MESSAGE_LIMIT} searches for today!"
    
    await update.message.reply_text(
        f"👋 Welcome to the Premium Membership Bot!\n\n"
        f"Your Status: {premium_status}{welcome_bonus}\n\n"
        f"🔍 Only messages starting with / are counted\n"
        f"Examples: /num, /search, /find\n"
        f"Regular chat is unlimited!\n\n"
        f"📊 Free Users:\n"
        f"• New Users: {NEW_USER_MESSAGE_LIMIT} searches (first day only)\n"
        f"• Regular Users: {DAILY_MESSAGE_LIMIT} search/day\n"
        f"• Resets daily at midnight (Asia/Kolkata)\n\n"
        f"💎 Premium Users: Unlimited searches\n\n"
        f"💰 Premium Plans:\n"
        f"• Weekly: ₹300 (7 days)\n"
        f"• Monthly: ₹500 (30 days)\n\n"
        f"Commands:\n"
        f"/status - Check your account\n"
        f"/premium - View & buy premium plans\n"
        f"/help - Get help"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check user's status"""
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    user = await get_or_create_user(user_id, username, first_name)
    await reset_daily_count(user_id)
    
    # Refresh user data
    user = await users_collection.find_one({'user_id': user_id})
    
    if await is_premium(user_id):
        premium = user.get('current_premium', {})
        expires = premium.get('expires')
        plan = premium.get('plan', 'custom')
        
        if expires:
            expires_kolkata = expires.replace(tzinfo=KOLKATA_TZ)
            days_left = (expires_kolkata - get_kolkata_time()).days
            
            await update.message.reply_text(
                f"💎 PREMIUM MEMBER\n\n"
                f"Plan: {PREMIUM_PLANS.get(plan, {}).get('name', 'Custom')}\n"
                f"Expires: {expires_kolkata.strftime('%Y-%m-%d %H:%M')} IST\n"
                f"Days Left: {days_left}\n"
                f"Messages: Unlimited ♾️\n"
                f"Total Commands: {user.get('total_commands', 0)}\n\n"
                f"Use /premium to renew"
            )
    else:
        count = user.get('message_count', 0)
        limit = await get_user_message_limit(user_id)
        remaining = limit - count
        
        user_type = "NEW USER 🎁" if user.get('is_new_user') else "FREE MEMBER"
        midnight = get_midnight_kolkata()
        
        await update.message.reply_text(
            f"🆓 {user_type}\n\n"
            f"📊 Today's Messages:\n"
            f"Used: {count}/{limit}\n"
            f"Remaining: {remaining}\n"
            f"{'(Welcome bonus!)' if user.get('is_new_user') else ''}\n\n"
            f"🕐 Resets at: {midnight.strftime('%H:%M')} IST\n"
            f"Total Commands: {user.get('total_commands', 0)}\n\n"
            f"💎 Upgrade to Premium for unlimited messages!\n"
            f"Use /premium to see plans"
        )

async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show premium plans"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("📅 Weekly - ₹300", callback_data="buy_week")],
        [InlineKeyboardButton("📆 Monthly - ₹500", callback_data="buy_month")],
        [InlineKeyboardButton("💬 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")],
    ]
    
    if await is_premium(user_id):
        user = await users_collection.find_one({'user_id': user_id})
        premium = user.get('current_premium', {})
        expires = premium.get('expires')
        if expires:
            expires_kolkata = expires.replace(tzinfo=KOLKATA_TZ)
            days_left = (expires_kolkata - get_kolkata_time()).days
            status_text = f"✅ You're already Premium!\n\nExpires in {days_left} days\n\nWant to extend?\n\n"
    else:
        status_text = "💎 Premium Membership Plans:\n\n"
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"{status_text}"
        f"📅 Weekly Plan: ₹300\n"
        f"   • 7 days unlimited messages\n"
        f"   • Best for short-term needs\n\n"
        f"📆 Monthly Plan: ₹500\n"
        f"   • 30 days unlimited messages\n"
        f"   • Best value! Save ₹700\n\n"
        f"Choose a plan below:",
        reply_markup=reply_markup
    )

async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle premium plan purchase"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_name = query.from_user.username or query.from_user.first_name
    plan = query.data.replace("buy_", "")
    
    if plan not in PREMIUM_PLANS:
        await query.edit_message_text("❌ Invalid plan selected.")
        return
    
    plan_info = PREMIUM_PLANS[plan]
    payment_id = f"{user_id}_{plan}_{datetime.now().timestamp()}"
    
    pending_payments[payment_id] = {
        "user_id": user_id,
        "user_name": user_name,
        "plan": plan,
        "amount": plan_info["price"],
        "timestamp": get_kolkata_time()
    }
    
    admin_keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Payment", callback_data=f"confirm_{payment_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{payment_id}")
        ]
    ]
    admin_markup = InlineKeyboardMarkup(admin_keyboard)
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USERNAME,
            text=f"💰 NEW PAYMENT REQUEST\n\n"
                 f"User: @{user_name}\n"
                 f"User ID: {user_id}\n"
                 f"Plan: {plan_info['name']} Premium\n"
                 f"Amount: ₹{plan_info['price']}\n"
                 f"Duration: {plan_info['duration_days']} days\n\n"
                 f"⚠️ Confirm only after receiving payment!",
            reply_markup=admin_markup
        )
    except Exception as e:
        logger.error(f"Error notifying admin: {e}")
        await query.edit_message_text("❌ Error sending request. Please contact admin directly.")
        return
    
    await query.edit_message_text(
        f"💳 Payment Instructions\n\n"
        f"Plan: {plan_info['name']} Premium\n"
        f"Amount: ₹{plan_info['price']}\n"
        f"Duration: {plan_info['duration_days']} days\n\n"
        f"📱 Send payment to: @{ADMIN_USERNAME}\n\n"
        f"Payment Methods:\n"
        f"• UPI\n"
        f"• Bank Transfer\n"
        f"• PayTM\n\n"
        f"⏳ After payment, wait for admin confirmation.\n"
        f"You'll be notified once approved!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("💬 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")
        ]])
    )

async def handle_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin payment confirmation"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_USER_ID:
        await query.answer("⛔ Only admin can confirm payments!", show_alert=True)
        return
    
    data = query.data
    action, payment_id = data.split("_", 1)
    
    if payment_id not in pending_payments:
        await query.edit_message_text("❌ Payment request expired or already processed.")
        return
    
    payment_info = pending_payments[payment_id]
    user_id = payment_info["user_id"]
    user_name = payment_info["user_name"]
    plan = payment_info["plan"]
    amount = payment_info["amount"]
    
    if action == "confirm":
        duration_days = PREMIUM_PLANS[plan]["duration_days"]
        expires = get_kolkata_time() + timedelta(days=duration_days)
        
        # Update user premium status
        premium_record = {
            'plan': plan,
            'expires': expires,
            'activated': get_kolkata_time(),
            'amount': amount,
            'duration_days': duration_days
        }
        
        await users_collection.update_one(
            {'user_id': user_id},
            {
                '$set': {'current_premium': premium_record},
                '$push': {'premium_history': premium_record}
            }
        )
        
        await query.edit_message_text(
            f"✅ PAYMENT CONFIRMED\n\n"
            f"User: @{user_name}\n"
            f"Plan: {PREMIUM_PLANS[plan]['name']} Premium\n"
            f"Amount: ₹{amount}\n"
            f"Valid Until: {expires.strftime('%Y-%m-%d %H:%M')} IST\n\n"
            f"Premium activated successfully! 🎉"
        )
        
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 PREMIUM ACTIVATED!\n\n"
                     f"Plan: {PREMIUM_PLANS[plan]['name']}\n"
                     f"Duration: {duration_days} days\n"
                     f"Expires: {expires.strftime('%Y-%m-%d %H:%M')} IST\n\n"
                     f"✅ You now have unlimited messages!\n"
                     f"Use /status to check your membership."
            )
        except Exception as e:
            logger.error(f"Error notifying user: {e}")
    
    else:
        await query.edit_message_text(
            f"❌ PAYMENT REJECTED\n\n"
            f"User: @{user_name}\n"
            f"Amount: ₹{amount}"
        )
        
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Your payment request was rejected.\n\n"
                     f"Please contact @{ADMIN_USERNAME} for details."
            )
        except Exception as e:
            logger.error(f"Error notifying user: {e}")
    
    del pending_payments[payment_id]

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to approve premium"""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ This command is only for admins.")
        return
    
    try:
        if len(context.args) < 2:
            await update.message.reply_text(
                "❌ Invalid format!\n\n"
                "Usage: /approve <user_id> <days>\n\n"
                "Examples:\n"
                "/approve 123456789 7\n"
                "/approve 123456789 30"
            )
            return
        
        target_user_id = int(context.args[0])
        days = int(context.args[1])
        
        if days <= 0:
            await update.message.reply_text("❌ Days must be greater than 0!")
            return
        
        expires = get_kolkata_time() + timedelta(days=days)
        plan = "week" if days == 7 else "month" if days == 30 else "custom"
        
        premium_record = {
            'plan': plan,
            'expires': expires,
            'activated': get_kolkata_time(),
            'amount': 0,
            'duration_days': days,
            'approved_by_admin': True
        }
        
        # Ensure user exists
        user = await users_collection.find_one({'user_id': target_user_id})
        if not user:
            await users_collection.insert_one({
                'user_id': target_user_id,
                'username': None,
                'first_name': None,
                'registration_time': get_kolkata_time(),
                'is_new_user': False,
                'message_count': 0,
                'last_reset': get_kolkata_time().date().isoformat(),
                'premium_history': [premium_record],
                'current_premium': premium_record,
                'total_commands': 0
            })
        else:
            await users_collection.update_one(
                {'user_id': target_user_id},
                {
                    '$set': {'current_premium': premium_record},
                    '$push': {'premium_history': premium_record}
                }
            )
        
        await update.message.reply_text(
            f"✅ PREMIUM APPROVED!\n\n"
            f"User ID: {target_user_id}\n"
            f"Duration: {days} days\n"
            f"Expires: {expires.strftime('%Y-%m-%d %H:%M')} IST\n\n"
            f"User now has unlimited searches!"
        )
        
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🎉 PREMIUM ACTIVATED BY ADMIN!\n\n"
                     f"Duration: {days} days\n"
                     f"Expires: {expires.strftime('%Y-%m-%d %H:%M')} IST\n\n"
                     f"✅ You now have unlimited searches!\n"
                     f"Use /status to check your membership."
            )
        except Exception as e:
            logger.error(f"Could not notify user {target_user_id}: {e}")
            await update.message.reply_text("⚠️ Premium granted but couldn't notify user.")
    
    except ValueError:
        await update.message.reply_text("❌ Invalid input! User ID and days must be numbers.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        logger.error(f"Error in approve_command: {e}")

async def database_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to get database export"""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ This command is only for admins.")
        return
    
    try:
        # Export all users
        users = await users_collection.find().to_list(length=None)
        
        # Convert to JSON-serializable format
        export_data = []
        for user in users:
            user_data = {
                'user_id': user.get('user_id'),
                'username': user.get('username'),
                'first_name': user.get('first_name'),
                'registration_time': user.get('registration_time').isoformat() if user.get('registration_time') else None,
                'is_new_user': user.get('is_new_user'),
                'message_count': user.get('message_count')
                'last_reset': user.get('last_reset'),
                'total_commands': user.get('total_commands', 0),
                'current_premium': None,
                'premium_history': []
            }
            
            # Handle current premium
            if user.get('current_premium'):
                premium = user['current_premium']
                user_data['current_premium'] = {
                    'plan': premium.get('plan'),
                    'expires': premium.get('expires').isoformat() if premium.get('expires') else None,
                    'activated': premium.get('activated').isoformat() if premium.get('activated') else None,
                    'amount': premium.get('amount'),
                    'duration_days': premium.get('duration_days')
                }
            
            # Handle premium history
            for premium in user.get('premium_history', []):
                user_data['premium_history'].append({
                    'plan': premium.get('plan'),
                    'expires': premium.get('expires').isoformat() if premium.get('expires') else None,
                    'activated': premium.get('activated').isoformat() if premium.get('activated') else None,
                    'amount': premium.get('amount'),
                    'duration_days': premium.get('duration_days')
                })
            
            export_data.append(user_data)
        
        # Create JSON file
        json_data = json.dumps(export_data, indent=2, ensure_ascii=False)
        file_buffer = io.BytesIO(json_data.encode('utf-8'))
        file_buffer.name = f'database_export_{get_kolkata_time().strftime("%Y%m%d_%H%M%S")}.json'
        
        await update.message.reply_document(
            document=file_buffer,
            filename=file_buffer.name,
            caption=f"📊 Database Export\n\n"
                    f"Total Users: {len(export_data)}\n"
                    f"Export Time: {get_kolkata_time().strftime('%Y-%m-%d %H:%M:%S')} IST"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error exporting database: {e}")
        logger.error(f"Error in database_command: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    await update.message.reply_text(
        f"📚 BOT HELP\n\n"
        f"🔍 Message Counting:\n"
        f"• Only messages starting with / are counted\n"
        f"• Examples: /num, /search, /find, etc.\n"
        f"• Regular chat messages are NOT counted\n\n"
        f"🆓 Free Members:\n"
        f"• New Users: {NEW_USER_MESSAGE_LIMIT} searches (first day only)\n"
        f"• Regular Users: {DAILY_MESSAGE_LIMIT} search per day\n"
        f"• Resets daily at midnight (Asia/Kolkata)\n"
        f"• Blocked until midnight if limit exceeded\n\n"
        f"💎 Premium Members:\n"
        f"• Unlimited searches\n"
        f"• No restrictions\n\n"
        f"💰 Premium Plans:\n"
        f"• Weekly: ₹300 (7 days)\n"
        f"• Monthly: ₹500 (30 days)\n\n"
        f"📱 Commands:\n"
        f"/start - Start bot\n"
        f"/status - Check account\n"
        f"/premium - Buy premium\n"
        f"/help - This message\n\n"
        f"Need help? Contact @{ADMIN_USERNAME}"
    )

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages in the group"""
    if update.effective_chat.type not in ["group", "supergroup"]:
        return
    
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    message_text = update.message.text.strip()
    
    if not message_text.startswith('/'):
        return
    
    command = message_text.split()[0].lower()
    
    # Ignore bot management commands
    bot_commands = ['/start', '/status', '/premium', '/help', '/approve', '/database']
    if command in bot_commands:
        return
    
    # Admin has unlimited access
    if user_id == ADMIN_USER_ID:
        return
    
    # Check if bot is admin
    try:
        bot_member = await context.bot.get_chat_member(update.effective_chat.id, context.bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            return
    except Exception as e:
        logger.error(f"Error checking bot admin status: {e}")
        return
    
    # Get or create user
    user = await get_or_create_user(user_id, username, first_name)
    await update_user_info(user_id, username, first_name)
    
    # Log the command
    await log_command(user_id, username, command, update.effective_chat.id)
    
    # Check premium status
    if await is_premium(user_id):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"💎 @{username or first_name}: Premium Member - Unlimited searches!",
            reply_to_message_id=update.message.message_id
        )
        return
    
    # Reset daily count if needed
    await reset_daily_count(user_id)
    
    # Get fresh user data
    user = await users_collection.find_one({'user_id': user_id})
    limit = await get_user_message_limit(user_id)
    count = user.get('message_count', 0)
    
    # Check if limit exceeded
    if count >= limit:
        is_new = user.get('is_new_user', False)
        midnight = get_midnight_kolkata()
        
        try:
            # Delete user's command
            await update.message.delete()
            
            # Send block notification
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⛔ @{username or first_name} - BLOCKED UNTIL MIDNIGHT\n\n"
                     f"You've used {limit}/{limit} {'welcome bonus ' if is_new else ''}searches today.\n"
                     f"You cannot send ANY commands until midnight.\n\n"
                     f"🕐 Resets at: {midnight.strftime('%H:%M')} IST\n\n"
                     f"💎 Upgrade to Premium for unlimited searches!\n"
                     f"Use /premium to upgrade now!",
                reply_to_message_id=None
            )
        except Exception as e:
            logger.error(f"Error blocking user: {e}")
        return
    
    # Increment count
    await users_collection.update_one(
        {'user_id': user_id},
        {'$inc': {'message_count': 1}}
    )
    
    remaining = limit - (count + 1)
    is_new = user.get('is_new_user', False)
    
    try:
        if remaining > 0:
            # Send status message
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📊 @{username or first_name}: {remaining}/{limit} search{'es' if remaining != 1 else ''} remaining today"
                     f"{' 🎁' if is_new else ''}",
                reply_to_message_id=update.message.message_id
            )
        else:
            # Last message warning
            midnight = get_midnight_kolkata()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ @{username or first_name}: This was your last search for today!\n"
                     f"Next command will be blocked until {midnight.strftime('%H:%M')} IST.\n"
                     f"💎 Upgrade to Premium: /premium",
                reply_to_message_id=update.message.message_id
            )
    except Exception as e:
        logger.error(f"Error sending status: {e}")

def main():
    """Start the bot"""
    import asyncio
    from threading import Thread
    from http.server import HTTPServer, BaseHTTPRequestHandler
    
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        
        def log_message(self, format, *args):
            pass
    
    # Initialize MongoDB
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_mongodb())
    
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    health_thread = Thread(target=server.serve_forever, daemon=True)
    health_thread.start()
    logger.info(f"Health check server started on port {port}")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("premium", premium_menu))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("database", database_command))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern="^(confirm|reject)_"))
    
    # Message handler
    application.add_handler(MessageHandler(filters.ALL, handle_group_message))
    
    logger.info("🚀 Premium Membership Bot Started with MongoDB!")
    logger.info(f"Timezone: Asia/Kolkata")
    logger.info(f"Current time: {get_kolkata_time().strftime('%Y-%m-%d %H:%M:%S')} IST")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
                'last_reset': user.get('last_reset'),
                'total_commands': user.get('total_commands', 0),
                'current_premium': None,
                'premium_history': []
            }
            
            # Handle current premium
            if user.get('current_premium'):
                premium = user['current_premium']
                user_data['current_premium'] = {
                    'plan': premium.get('plan'),
                    'expires': premium.get('expires').isoformat() if premium.get('expires') else None,
                    'activated': premium.get('activated').isoformat() if premium.get('activated') else None,
                    'amount': premium.get('amount'),
                    'duration_days': premium.get('duration_days')
                }
            
            # Handle premium history
            for premium in user.get('premium_history', []):
                user_data['premium_history'].append({
                    'plan': premium.get('plan'),
                    'expires': premium.get('expires').isoformat() if premium.get('expires') else None,
                    'activated': premium.get('activated').isoformat() if premium.get('activated') else None,
                    'amount': premium.get('amount'),
                    'duration_days': premium.get('duration_days')
                })
            
            export_data.append(user_data)
        
        # Create JSON file
        json_data = json.dumps(export_data, indent=2, ensure_ascii=False)
        file_buffer = io.BytesIO(json_data.encode('utf-8'))
        file_buffer.name = f'database_export_{get_kolkata_time().strftime("%Y%m%d_%H%M%S")}.json'
        
        await update.message.reply_document(
            document=file_buffer,
            filename=file_buffer.name,
            caption=f"📊 Database Export\n\n"
                    f"Total Users: {len(export_data)}\n"
                    f"Export Time: {get_kolkata_time().strftime('%Y-%m-%d %H:%M:%S')} IST"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error exporting database: {e}")
        logger.error(f"Error in database_command: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    await update.message.reply_text(
        f"📚 BOT HELP\n\n"
        f"🔍 Message Counting:\n"
        f"• Only messages starting with / are counted\n"
        f"• Examples: /num, /search, /find, etc.\n"
        f"• Regular chat messages are NOT counted\n\n"
        f"🆓 Free Members:\n"
        f"• New Users: {NEW_USER_MESSAGE_LIMIT} searches (first day only)\n"
        f"• Regular Users: {DAILY_MESSAGE_LIMIT} search per day\n"
        f"• Resets daily at midnight (Asia/Kolkata)\n"
        f"• Blocked until midnight if limit exceeded\n\n"
        f"💎 Premium Members:\n"
        f"• Unlimited searches\n"
        f"• No restrictions\n\n"
        f"💰 Premium Plans:\n"
        f"• Weekly: ₹300 (7 days)\n"
        f"• Monthly: ₹500 (30 days)\n\n"
        f"📱 Commands:\n"
        f"/start - Start bot\n"
        f"/status - Check account\n"
        f"/premium - Buy premium\n"
        f"/help - This message\n\n"
        f"Need help? Contact @{ADMIN_USERNAME}"
    )

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages in the group"""
    if update.effective_chat.type not in ["group", "supergroup"]:
        return
    
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    message_text = update.message.text.strip()
    
    if not message_text.startswith('/'):
        return
    
    command = message_text.split()[0].lower()
    
    # Ignore bot management commands
    bot_commands = ['/start', '/status', '/premium', '/help', '/approve', '/database']
    if command in bot_commands:
        return
    
    # Admin has unlimited access
    if user_id == ADMIN_USER_ID:
        return
    
    # Check if bot is admin
    try:
        bot_member = await context.bot.get_chat_member(update.effective_chat.id, context.bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            return
    except Exception as e:
        logger.error(f"Error checking bot admin status: {e}")
        return
    
    # Get or create user
    user = await get_or_create_user(user_id, username, first_name)
    await update_user_info(user_id, username, first_name)
    
    # Log the command
    await log_command(user_id, username, command, update.effective_chat.id)
    
    # Check premium status
    if await is_premium(user_id):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"💎 @{username or first_name}: Premium Member - Unlimited searches!",
            reply_to_message_id=update.message.message_id
        )
        return
    
    # Reset daily count if needed
    await reset_daily_count(user_id)
    
    # Get fresh user data
    user = await users_collection.find_one({'user_id': user_id})
    limit = await get_user_message_limit(user_id)
    count = user.get('message_count', 0)
    
    # Check if limit exceeded
    if count >= limit:
        is_new = user.get('is_new_user', False)
        midnight = get_midnight_kolkata()
        
        try:
            # Delete user's command
            await update.message.delete()
            
            # Send block notification
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⛔ @{username or first_name} - BLOCKED UNTIL MIDNIGHT\n\n"
                     f"You've used {limit}/{limit} {'welcome bonus ' if is_new else ''}searches today.\n"
                     f"You cannot send ANY commands until midnight.\n\n"
                     f"🕐 Resets at: {midnight.strftime('%H:%M')} IST\n\n"
                     f"💎 Upgrade to Premium for unlimited searches!\n"
                     f"Use /premium to upgrade now!",
                reply_to_message_id=None
            )
        except Exception as e:
            logger.error(f"Error blocking user: {e}")
        return
    
    # Increment count
    await users_collection.update_one(
        {'user_id': user_id},
        {'$inc': {'message_count': 1}}
    )
    
    remaining = limit - (count + 1)
    is_new = user.get('is_new_user', False)
    
    try:
        if remaining > 0:
            # Send status message
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📊 @{username or first_name}: {remaining}/{limit} search{'es' if remaining != 1 else ''} remaining today"
                     f"{' 🎁' if is_new else ''}",
                reply_to_message_id=update.message.message_id
            )
        else:
            # Last message warning
            midnight = get_midnight_kolkata()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ @{username or first_name}: This was your last search for today!\n"
                     f"Next command will be blocked until {midnight.strftime('%H:%M')} IST.\n"
                     f"💎 Upgrade to Premium: /premium",
                reply_to_message_id=update.message.message_id
            )
    except Exception as e:
        logger.error(f"Error sending status: {e}")

def main():
    """Start the bot"""
    import asyncio
    from threading import Thread
    from http.server import HTTPServer, BaseHTTPRequestHandler
    
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        
        def log_message(self, format, *args):
            pass
    
    # Initialize MongoDB
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_mongodb())
    
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    health_thread = Thread(target=server.serve_forever, daemon=True)
    health_thread.start()
    logger.info(f"Health check server started on port {port}")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("premium", premium_menu))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("database", database_command))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern="^(confirm|reject)_"))
    
    # Message handler
    application.add_handler(MessageHandler(filters.ALL, handle_group_message))
    
    logger.info("🚀 Premium Membership Bot Started with MongoDB!")
    logger.info(f"Timezone: Asia/Kolkata")
    logger.info(f"Current time: {get_kolkata_time().strftime('%Y-%m-%d %H:%M:%S')} IST")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
