import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from datetime import datetime, timedelta
from collections import defaultdict
import json

# Configuration
BOT_TOKEN = "8178740511:AAEv7r1qLoorgLXcxQoxLN8szd9vpU6ILFo"
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
    "date": None,
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
        welcome_bonus = f"\n🎁 Welcome Bonus: {NEW_USER_MESSAGE_LIMIT} messages for today!"
    else:
        welcome_bonus = ""
    
    await update.message.reply_text(
        f"👋 Welcome to the Premium Membership Bot!\n\n"
        f"Your Status: {premium_status}{welcome_bonus}\n\n"
        f"📊 Free Users:\n"
        f"• New Users: {NEW_USER_MESSAGE_LIMIT} messages (first day only)\n"
        f"• Regular Users: {DAILY_MESSAGE_LIMIT} message/day\n\n"
        f"💎 Premium Users: Unlimited messages\n\n"
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
        f"You'll be notified once approved!"
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
        f"🆓 Free Members:\n"
        f"• New Users: {NEW_USER_MESSAGE_LIMIT} messages (first day only)\n"
        f"• Regular Users: {DAILY_MESSAGE_LIMIT} message per day\n"
        f"• Resets daily at midnight\n\n"
        f"💎 Premium Members:\n"
        f"• Unlimited messages\n"
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
    
    user_id = update.effective_user.id
    
    # Admin has unlimited messages
    if update.effective_user.username == ADMIN_USERNAME:
        return
    
    # Premium users have unlimited messages
    if is_premium(user_id):
        return
    
    # Check and reset daily count for free users
    reset_daily_count(user_id)
    
    # Get user's message limit
    limit = get_user_message_limit(user_id)
    
    # Check message limit
    if user_messages[user_id]["count"] >= limit:
        is_new = user_messages[user_id]["is_new_user"]
        try:
            await update.message.delete()
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⛔ DAILY LIMIT REACHED\n\n"
                     f"You've used {limit}/{limit} {'welcome bonus ' if is_new else ''}messages today.\n\n"
                     f"💎 Upgrade to Premium for unlimited messages!\n\n"
                     f"Plans:\n"
                     f"• Weekly: ₹300\n"
                     f"• Monthly: ₹500\n\n"
                     f"Use /premium to upgrade now!"
            )
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
        return
    
    # Increment counter
    user_messages[user_id]["count"] += 1
    remaining = limit - user_messages[user_id]["count"]
    
    # Warn when approaching limit
    if remaining <= 2 and remaining > 0:
        is_new = user_messages[user_id]["is_new_user"]
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ WARNING\n\n"
                     f"Only {remaining} message{'s' if remaining != 1 else ''} remaining today!\n"
                     f"{'(Welcome bonus) ' if is_new else ''}\n\n"
                     f"💎 Get Premium for unlimited messages\n"
                     f"Use /premium to upgrade"
            )
        except Exception as e:
            logger.error(f"Error sending warning: {e}")

def main():
    """Start the bot"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("premium", premium_menu))
    application.add_handler(CommandHandler("help", help_command))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(handle_payment_confirmation, pattern="^(confirm|reject)_"))
    
    # Message handler for group messages
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND,
        handle_group_message
    ))
    
    logger.info("🚀 Premium Membership Bot Started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
