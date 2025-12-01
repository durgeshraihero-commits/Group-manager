import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from datetime import datetime, timedelta
from collections import defaultdict
import json

# Configuration
BOT_TOKEN = "8597564579:AAGHr1Rqi8ZIqD_RA8PuslB1ob6bAjtOEhU"
ADMIN_USERNAME = "itsmezigzagzozo"
DAILY_MESSAGE_LIMIT = 1      # Regular users: 1 message per day
NEW_USER_MESSAGE_LIMIT = 5   # New users: 5 messages on first day

# Premium Plans
PREMIUM_PLANS = {
    "week": {"price": 300, "duration_days": 7, "name": "Weekly"},
    "month": {"price": 500, "duration_days": 30, "name": "Monthly"}
}

# Storage (in production, use a database)
user_messages = defaultdict(lambda: {
    "count": 0, 
    "date": def main():
    """Start the bot"""
    # For Render.com and other platforms - set up a simple HTTP server
    import os
    from threading import Thread
    from http.server import HTTPServer, BaseHTTPRequestHandler
    
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        
        def log_message(self, format, *args):
            pass  # Suppress logs
    
    # Start health check server on PORT (for Render.com)
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    health_thread = Thread(target=server.serve_forever, daemon=True)
    health_thread.start()
    logger.info(f"Health check server started on port {port}")
    
    # Start the bot
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers MUST come FIRST - ORDER IS CRITICAL!
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("premium", premium_menu))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("test", test_command))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern="^(confirm|reject)_"))
    
    # Message handler MUST come LAST - catches everything else
    application.add_handler(MessageHandler(
        filters.ALL,
        handle_group_message
    )),
    "is_new_user": True,
    "joined_date": datetime.now()
})
premium_users = {}  # {user_id: {"expires": datetime, "plan": "week/month"}}
pending_payments = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def is_premium(user_id):
    """Check if user has active premium membership"""
    if user_id in premium_users:
        if datetime.now() < premium_users[user_id]["expires"]:
            return True
        else:
            # Premium expired
            del premium_users[user_id]
    return False

def get_user_message_limit(user_id):
    """Get message limit for user based on their status"""
    user_data = user_messages[user_id]
    
    # Check if it's user's first day
    if user_data["is_new_user"]:
        joined_date = user_data["joined_date"].date()
        today = datetime.now().date()
        
        # If joined today, give 5 messages
        if joined_date == today:
            return NEW_USER_MESSAGE_LIMIT
        else:
            # No longer a new user
            user_data["is_new_user"] = False
            return DAILY_MESSAGE_LIMIT
    
    return DAILY_MESSAGE_LIMIT

def reset_daily_count(user_id):
    """Reset message count if it's a new day"""
    today = datetime.now().date()
    if user_messages[user_id]["date"] != today:
        user_messages[user_id]["count"] = 0
        user_messages[user_id]["date"] = today

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    premium_status = "✅ PREMIUM" if is_premium(user_id) else "🆓 FREE"
    
    # Mark user as registered
    if user_id not in user_messages:
        user_messages[user_id]["joined_date"] = datetime.now()
        user_messages[user_id]["is_new_user"] = True
        welcome_bonus = f"\n🎁 Welcome Bonus: {NEW_USER_MESSAGE_LIMIT} searches for today!"
    else:
        welcome_bonus = ""
    
    await update.message.reply_text(
        f"👋 Welcome to the Premium Membership Bot!\n\n"
        f"Your Status: {premium_status}{welcome_bonus}\n\n"
        f"🔍 Only messages starting with / are counted\n"
        f"Examples: /num, /search, /find\n"
        f"Regular chat is unlimited!\n\n"
        f"📊 Free Users:\n"
        f"• New Users: {NEW_USER_MESSAGE_LIMIT} searches (first day only)\n"
        f"• Regular Users: {DAILY_MESSAGE_LIMIT} search/day\n\n"
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
    reset_daily_count(user_id)
    
    if is_premium(user_id):
        expires = premium_users[user_id]["expires"]
        plan = premium_users[user_id]["plan"]
        days_left = (expires - datetime.now()).days
        
        await update.message.reply_text(
            f"💎 PREMIUM MEMBER\n\n"
            f"Plan: {PREMIUM_PLANS[plan]['name']}\n"
            f"Expires: {expires.strftime('%Y-%m-%d %H:%M')}\n"
            f"Days Left: {days_left}\n"
            f"Messages: Unlimited ♾️\n\n"
            f"Use /premium to renew"
        )
    else:
        count = user_messages[user_id]["count"]
        limit = get_user_message_limit(user_id)
        remaining = limit - count
        
        user_type = "NEW USER 🎁" if user_messages[user_id]["is_new_user"] else "FREE MEMBER"
        
        await update.message.reply_text(
            f"🆓 {user_type}\n\n"
            f"📊 Today's Messages:\n"
            f"Used: {count}/{limit}\n"
            f"Remaining: {remaining}\n"
            f"{'(Welcome bonus!)' if user_messages[user_id]['is_new_user'] else ''}\n\n"
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
    
    if is_premium(user_id):
        expires = premium_users[user_id]["expires"]
        days_left = (expires - datetime.now()).days
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
        "timestamp": datetime.now()
    }
    
    # Admin approval keyboard
    admin_keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Payment", callback_data=f"confirm_{payment_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{payment_id}")
        ]
    ]
    admin_markup = InlineKeyboardMarkup(admin_keyboard)
    
    # Notify admin
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
    
    # Notify user
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
    
    # Check if user is admin
    if query.from_user.username != ADMIN_USERNAME:
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
        # Grant premium membership
        duration_days = PREMIUM_PLANS[plan]["duration_days"]
        expires = datetime.now() + timedelta(days=duration_days)
        
        premium_users[user_id] = {
            "expires": expires,
            "plan": plan,
            "activated": datetime.now()
        }
        
        await query.edit_message_text(
            f"✅ PAYMENT CONFIRMED\n\n"
            f"User: @{user_name}\n"
            f"Plan: {PREMIUM_PLANS[plan]['name']} Premium\n"
            f"Amount: ₹{amount}\n"
            f"Valid Until: {expires.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Premium activated successfully! 🎉"
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 PREMIUM ACTIVATED!\n\n"
                     f"Plan: {PREMIUM_PLANS[plan]['name']}\n"
                     f"Duration: {duration_days} days\n"
                     f"Expires: {expires.strftime('%Y-%m-%d %H:%M')}\n\n"
                     f"✅ You now have unlimited messages!\n"
                     f"Use /status to check your membership."
            )
        except Exception as e:
            logger.error(f"Error notifying user: {e}")
    
    else:  # reject
        await query.edit_message_text(
            f"❌ PAYMENT REJECTED\n\n"
            f"User: @{user_name}\n"
            f"Amount: ₹{amount}"
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Your payment request was rejected.\n\n"
                     f"Please contact @{ADMIN_USERNAME} for details."
            )
        except Exception as e:
            logger.error(f"Error notifying user: {e}")
    
    del pending_payments[payment_id]

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
        f"• Resets daily at midnight\n\n"
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
        f"/help - This message\n"
        f"/test - Test bot in group\n\n"
        f"Need help? Contact @{ADMIN_USERNAME}"
    )

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test if bot is working in the group"""
    logger.info(f"TEST COMMAND RECEIVED from {update.effective_user.username}")
    
    chat_type = update.effective_chat.type
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name
    
    logger.info(f"Chat type: {chat_type}, User: {user_name}, User ID: {user_id}")
    
    # Check if in group
    if chat_type in ["group", "supergroup"]:
        # Check bot admin status
        try:
            bot_member = await context.bot.get_chat_member(update.effective_chat.id, context.bot.id)
            bot_status = bot_member.status
            logger.info(f"Bot status in group: {bot_status}")
            
            if bot_status in ["administrator", "creator"]:
                admin_status = "✅ Bot is Admin (Can delete messages)"
            else:
                admin_status = "❌ Bot is NOT Admin (Cannot delete messages)\n⚠️ Make bot admin with 'Delete Messages' permission!"
        except Exception as e:
            admin_status = f"❌ Error checking status: {e}"
            logger.error(f"Error checking bot admin status: {e}")
        
        # Check user status
        is_new = user_messages[user_id]["is_new_user"]
        limit = get_user_message_limit(user_id)
        
        response_text = (
            f"🤖 BOT STATUS TEST\n\n"
            f"Chat Type: {chat_type}\n"
            f"{admin_status}\n\n"
            f"👤 Your Status:\n"
            f"User: @{user_name}\n"
            f"Type: {'🎁 New User' if is_new else '🆓 Regular User'}\n"
            f"Daily Limit: {limit} message(s)\n"
            f"Premium: {'✅ Yes' if is_premium(user_id) else '❌ No'}\n\n"
            f"✅ Bot is working in this group!\n\n"
            f"🔍 Debug Info:\n"
            f"Privacy Mode must be: DISABLED\n"
            f"Bot sees all messages: YES"
        )
        
        logger.info(f"Sending test response to group")
        await update.message.reply_text(response_text)
        logger.info(f"Test response sent successfully")
    else:
        logger.info(f"Test command in private chat")
        await update.message.reply_text(
            f"🤖 BOT TEST\n\n"
            f"Chat Type: {chat_type} (Private Chat)\n\n"
            f"ℹ️ To test in group:\n"
            f"1. Add me to your group\n"
            f"2. Make me admin with 'Delete Messages' permission\n"
            f"3. Use /test in the group"
        )


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages in the group"""
    # Debug logging
    logger.info(f"Received message: {update.message.text if update.message else 'No message'}")
    logger.info(f"Chat type: {update.effective_chat.type if update.effective_chat else 'No chat'}")
    
    # Only process group messages
    if update.effective_chat.type not in ["group", "supergroup"]:
        logger.info("Not a group message, ignoring")
        return
    
    # Ignore if no message or no text
    if not update.message or not update.message.text:
        logger.info("No message text, ignoring")
        return
    
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name
    message_text = update.message.text.strip()
    
    logger.info(f"Processing message from {user_name}: {message_text}")
    
    # ONLY COUNT MESSAGES STARTING WITH /
    if not message_text.startswith('/'):
        logger.info("Message doesn't start with /, ignoring")
        return
    
    # Extract command (first word)
    command = message_text.split()[0].lower()
    logger.info(f"Command extracted: {command}")
    
    # Ignore ONLY bot management commands - count everything else
    bot_commands = ['/start', '/status', '/premium', '/help', '/test']
    if command in bot_commands:
        logger.info(f"Bot management command {command}, ignoring")
        return
    
    logger.info(f"This command will be counted: {command}")
    
    # Admin has unlimited messages
    if update.effective_user.username == ADMIN_USERNAME:
        logger.info("User is admin, unlimited access")
        return
    
    # Check if bot is admin (needed to delete messages)
    try:
        bot_member = await context.bot.get_chat_member(update.effective_chat.id, context.bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            logger.warning(f"Bot is not admin in chat {update.effective_chat.id}")
            return
    except Exception as e:
        logger.error(f"Error checking bot admin status: {e}")
        return
    
    # Premium users have unlimited messages
    if is_premium(user_id):
        logger.info(f"User {user_name} is premium")
        try:
            premium_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"💎 @{user_name}: Premium Member - Unlimited searches!",
                reply_to_message_id=update.message.message_id
            )
            # Delete after 3 seconds using asyncio
            import asyncio
            await asyncio.sleep(3)
            await premium_msg.delete()
        except Exception as e:
            logger.error(f"Error sending premium status: {e}")
        return
    
    # Check and reset daily count for free users
    reset_daily_count(user_id)
    
    # Get user's message limit
    limit = get_user_message_limit(user_id)
    
    logger.info(f"User {user_name} count: {user_messages[user_id]['count']}/{limit}")
    
    # Check message limit
    if user_messages[user_id]["count"] >= limit:
        is_new = user_messages[user_id]["is_new_user"]
        logger.info(f"User {user_name} exceeded limit, deleting message")
        try:
            await update.message.delete()
            
            # Send notification in GROUP
            limit_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⛔ @{user_name} - DAILY LIMIT REACHED\n\n"
                     f"You've used {limit}/{limit} {'welcome bonus ' if is_new else ''}searches today.\n\n"
                     f"💎 Upgrade to Premium for unlimited searches!\n"
                     f"Plans: Weekly ₹300 | Monthly ₹500\n\n"
                     f"Use /premium to upgrade now!",
                reply_to_message_id=None
            )
            
            # Delete the notification after 10 seconds
            import asyncio
            await asyncio.sleep(10)
            await limit_msg.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
        return
    
    # Increment counter
    user_messages[user_id]["count"] += 1
    remaining = limit - user_messages[user_id]["count"]
    is_new = user_messages[user_id]["is_new_user"]
    
    logger.info(f"Incremented count for {user_name}. New count: {user_messages[user_id]['count']}, Remaining: {remaining}")
    
    # Show remaining messages after EVERY message
    try:
        if remaining > 0:
            status_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📊 @{user_name}: {remaining}/{limit} search{'es' if remaining != 1 else ''} remaining today"
                     f"{' 🎁' if is_new else ''}",
                reply_to_message_id=update.message.message_id
            )
            
            logger.info(f"Sent status message, will delete in 5 seconds")
            # Delete status message after 5 seconds
            import asyncio
            await asyncio.sleep(5)
            await status_msg.delete()
            logger.info("Status message deleted")
        else:
            # Last message - warn about limit
            warning_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ @{user_name}: This was your last search for today!\n"
                     f"Next search will be blocked.\n"
                     f"💎 Upgrade to Premium: /premium",
                reply_to_message_id=update.message.message_id
            )
            
            # Delete warning after 8 seconds
            import asyncio
            await asyncio.sleep(8)
            await warning_msg.delete()
    except Exception as e:
        logger.error(f"Error sending status: {e}")

def main():
    """Start the bot"""
    # For Render.com and other platforms - set up a simple HTTP server
    import os
    from threading import Thread
    from http.server import HTTPServer, BaseHTTPRequestHandler
    
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        
        def log_message(self, format, *args):
            pass  # Suppress logs
    
    # Start health check server on PORT (for Render.com)
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    health_thread = Thread(target=server.serve_forever, daemon=True)
    health_thread.start()
    logger.info(f"Health check server started on port {port}")
    
    # Start the bot
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("premium", premium_menu))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("test", test_command))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern="^(confirm|reject)_"))
    
    # Message handler for group messages (both group and supergroup)
    # Use a simpler filter to catch ALL messages first
    application.add_handler(MessageHandler(
        filters.ALL,
        handle_group_message
    ))
    
    logger.info("🚀 Premium Membership Bot Started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
