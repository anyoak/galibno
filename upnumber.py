import logging
import sqlite3
import time
import os
import csv
import re
import threading
import subprocess
import sys
from datetime import datetime, timedelta
from threading import Thread
import telebot
from telebot import types

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
API_TOKEN = "8490533685:AAFqWp8cLxzkLIzRdILWn8UQsngURibH29A"
ADMIN_IDS = [6577308099, 5878787791]

# Default channel values (used only as fallback / initial database values)
DEFAULT_MAIN_CHANNEL = '@FutureTech30'
DEFAULT_BACKUP_CHANNEL = '-1003223529033'
DEFAULT_BACKUP_CHANNEL_LINK = 'https://t.me/FutureTechOtp'
DEFAULT_OTP_CHANNEL = '@FutureTechOtp'

if ':' not in API_TOKEN:
    raise ValueError('Invalid bot token format.')

bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=4)

# Database setup with connection pooling and thread safety
class Database:
    _instance = None
    _connection = None
    _lock = threading.RLock()  # Add a lock for thread safety
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._connection = sqlite3.connect('numbers.db', check_same_thread=False, timeout=30)
            cls._connection.row_factory = sqlite3.Row
            cls.init_db()
        return cls._instance
    
    @classmethod
    def init_db(cls):
        with cls._lock:
            c = cls._connection.cursor()
            
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
                         last_name TEXT, join_date TEXT, is_banned INTEGER DEFAULT 0)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS numbers
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, number TEXT UNIQUE, 
                         is_used INTEGER DEFAULT 0, used_by INTEGER, use_date TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS countries
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, code TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS user_stats
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, date TEXT, 
                         numbers_today INTEGER DEFAULT 0)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS cooldowns
                         (user_id INTEGER PRIMARY KEY, timestamp INTEGER)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS notifications
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, country TEXT, notified INTEGER DEFAULT 0)''')
            
            # NEW: Add table for bot status
            c.execute('''CREATE TABLE IF NOT EXISTS bot_status
                         (id INTEGER PRIMARY KEY CHECK (id = 1), is_enabled INTEGER DEFAULT 1)''')
            
            # Initialize bot status if not exists
            c.execute("INSERT OR IGNORE INTO bot_status (id, is_enabled) VALUES (1, 1)")

            # NEW: Channel settings table
            c.execute('''CREATE TABLE IF NOT EXISTS channel_settings
                         (id INTEGER PRIMARY KEY CHECK (id = 1),
                          main_channel TEXT,
                          backup_channel TEXT,
                          backup_channel_link TEXT,
                          otp_channel TEXT)''')

            c.execute("""INSERT OR IGNORE INTO channel_settings 
                         (id, main_channel, backup_channel, backup_channel_link, otp_channel)
                         VALUES (1, ?, ?, ?, ?)""",
                      (DEFAULT_MAIN_CHANNEL,
                       DEFAULT_BACKUP_CHANNEL,
                       DEFAULT_BACKUP_CHANNEL_LINK,
                       DEFAULT_OTP_CHANNEL))
            
            cls._connection.commit()
    
    @classmethod
    def get_connection(cls):
        return cls._connection
    
    @classmethod
    def execute(cls, query, params=()):
        with cls._lock:  # Use lock to prevent concurrent access
            try:
                c = cls._connection.cursor()
                c.execute(query, params)
                cls._connection.commit()
                return c
            except sqlite3.Error as e:
                logger.error(f"Database error: {e}")
                try:
                    # Try to reconnect if there's an error
                    cls._connection = sqlite3.connect('numbers.db', check_same_thread=False, timeout=30)
                    cls._connection.row_factory = sqlite3.Row
                    c = cls._connection.cursor()
                    c.execute(query, params)
                    cls._connection.commit()
                    return c
                except sqlite3.Error as e2:
                    logger.error(f"Database reconnection failed: {e2}")
                    # Wait and retry once more
                    time.sleep(1)
                    try:
                        cls._connection = sqlite3.connect('numbers.db', check_same_thread=False, timeout=30)
                        cls._connection.row_factory = sqlite3.Row
                        c = cls._connection.cursor()
                        c.execute(query, params)
                        cls._connection.commit()
                        return c
                    except sqlite3.Error as e3:
                        logger.error(f"Database final reconnection failed: {e3}")
                        raise e3

# Initialize database
db = Database()

# === Channel settings helpers ===
def get_channel_settings():
    c = db.execute("SELECT main_channel, backup_channel, backup_channel_link, otp_channel FROM channel_settings WHERE id = 1")
    row = c.fetchone()
    if row:
        return row['main_channel'], row['backup_channel'], row['backup_channel_link'], row['otp_channel']
    # Fallback (should not happen normally)
    return DEFAULT_MAIN_CHANNEL, DEFAULT_BACKUP_CHANNEL, DEFAULT_BACKUP_CHANNEL_LINK, DEFAULT_OTP_CHANNEL

def update_channel_settings(main=None, backup=None, link=None, otp=None):
    current_main, current_backup, current_link, current_otp = get_channel_settings()
    main = main if main not in (None, '') else current_main
    backup = backup if backup not in (None, '') else current_backup
    link = link if link not in (None, '') else current_link
    otp = otp if otp not in (None, '') else current_otp

    db.execute("""UPDATE channel_settings 
                  SET main_channel=?, backup_channel=?, backup_channel_link=?, otp_channel=?
                  WHERE id=1""",
               (main, backup, link, otp))

# NEW: Function to check if bot is enabled
def is_bot_enabled():
    c = db.execute("SELECT is_enabled FROM bot_status WHERE id = 1")
    result = c.fetchone()
    return result[0] == 1 if result else True

# NEW: Function to set bot status
def set_bot_status(enabled):
    status = 1 if enabled else 0
    db.execute("UPDATE bot_status SET is_enabled = ? WHERE id = 1", (status,))
    return True

# NEW: Function to notify all users
def notify_all_users(message_text):
    c = db.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = c.fetchall()
    
    success = 0
    failed = 0
    
    for user in users:
        try:
            bot.send_message(user[0], message_text)
            success += 1
        except Exception as e:
            logger.error(f"Failed to notify user {user[0]}: {e}")
            failed += 1
        time.sleep(0.1)  # Rate limiting
    
    return success, failed

# Utility functions
def update_user_stats(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    
    c = db.execute("SELECT numbers_today FROM user_stats WHERE user_id = ? AND date = ?", (user_id, today))
    result = c.fetchone()
    
    if result:
        db.execute("UPDATE user_stats SET numbers_today = numbers_today + 1 WHERE user_id = ? AND date = ?", 
                   (user_id, today))
    else:
        db.execute("INSERT INTO user_stats (user_id, date, numbers_today) VALUES (?, ?, 1)", 
                   (user_id, today))

def is_admin(user_id):
    return user_id in ADMIN_IDS

def check_membership(user_id, force_check=False):
    """
    Check if the user is a member of both main and backup channels.
    force_check=True bypasses the cache for a fresh check.
    """
    cache_key = f"member_{user_id}"
    
    # Bypass cache if force_check is True or cache is outdated
    if not force_check and hasattr(check_membership, 'cache') and cache_key in check_membership.cache:
        if time.time() - check_membership.cache[cache_key]['time'] < 300:  # 5-minute cache
            return check_membership.cache[cache_key]['result']
    
    max_retries = 3
    retry_delay = 1  # seconds
    
    for attempt in range(max_retries):
        try:
            main_channel, backup_channel, backup_link, otp_channel = get_channel_settings()
            # Check main channel membership
            main_member = bot.get_chat_member(main_channel, user_id)
            if main_member.status not in ['member', 'administrator', 'creator']:
                result = (False, "public")
                break
                
            # Check backup channel membership
            backup_member = bot.get_chat_member(backup_channel, user_id)
            if backup_member.status not in ['member', 'administrator', 'creator']:
                result = (False, "private")
                break
                
            result = (True, "both")
            break
            
        except Exception as e:
            logger.error(f"Membership check failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                result = (False, "error")
    
    # Update cache
    if not hasattr(check_membership, 'cache'):
        check_membership.cache = {}
    check_membership.cache[cache_key] = {'result': result, 'time': time.time()}
    
    return result

def get_today_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    c = db.execute("SELECT COUNT(*) FROM numbers WHERE use_date LIKE ?", (f"{today}%",))
    total_used = c.fetchone()[0]
    
    c = db.execute("SELECT COUNT(DISTINCT user_id) FROM user_stats WHERE date = ?", (today,))
    active_users = c.fetchone()[0]
    
    return total_used, active_users

def get_country_stats():
    c = db.execute("SELECT country, COUNT(*) as total, SUM(is_used) as used FROM numbers GROUP BY country")
    return c.fetchall()

def get_user_stats(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    c = db.execute("SELECT numbers_today FROM user_stats WHERE user_id = ? AND date = ?", (user_id, today))
    result = c.fetchone()
    return result[0] if result else 0

def check_low_numbers():
    c = db.execute("SELECT country, COUNT(*) as available FROM numbers WHERE is_used = 0 GROUP BY country")
    results = c.fetchall()
    
    low_countries = []
    for country, available in results:
        if available < 5:
            low_countries.append((country, available))
    
    return low_countries

def check_country_availability(country):
    c = db.execute("SELECT COUNT(*) FROM numbers WHERE country = ? AND is_used = 0", (country,))
    return c.fetchone()[0]

def notify_admins_country_empty(country):
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, f"⚠️ COUNTRY EMPTY: {country} has run out of numbers!")
        except Exception as e:
            logger.error(f"Error notifying admin: {e}")

def check_and_notify_country_empty(country):
    c = db.execute("SELECT notified FROM notifications WHERE country = ?", (country,))
    result = c.fetchone()
    
    available = check_country_availability(country)
    
    if available == 0:
        if not result:
            notify_admins_country_empty(country)
            db.execute("INSERT INTO notifications (country, notified) VALUES (?, 1)", (country,))
        elif result[0] == 0:
            notify_admins_country_empty(country)
            db.execute("UPDATE notifications SET notified = 1 WHERE country = ?", (country,))
    else:
        if result:
            db.execute("UPDATE notifications SET notified = 0 WHERE country = ?", (country,))

def set_cooldown(user_id):
    timestamp = int(time.time())
    db.execute("REPLACE INTO cooldowns (user_id, timestamp) VALUES (?, ?)", (user_id, timestamp))

def check_cooldown(user_id):
    c = db.execute("SELECT timestamp FROM cooldowns WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if result:
        elapsed = int(time.time()) - result[0]
        if elapsed < 5:  # Changed from 10 to 5 seconds
            return 5 - elapsed  # Changed from 10 to 5 seconds
    return 0

def extract_numbers_from_content(content, filename):
    numbers = set()
    file_ext = os.path.splitext(filename)[1].lower() if filename else '.txt'
    
    if file_ext == '.csv':
        try:
            csv_content = content.decode('utf-8').splitlines()
            reader = csv.reader(csv_content)
            for row in reader:
                for item in row:
                    found_numbers = re.findall(r'\+?[0-9][0-9\s\-\(\)\.]{7,}[0-9]', item)
                    numbers.update(found_numbers)
        except:
            text_content = content.decode('utf-8', errors='ignore')
            found_numbers = re.findall(r'\+?[0-9][0-9\s\-\(\)\.]{7,}[0-9]', text_content)
            numbers.update(found_numbers)
    else:
        try:
            text_content = content.decode('utf-8')
        except:
            text_content = content.decode('utf-8', errors='ignore')
        
        found_numbers = re.findall(r'\+?[0-9][0-9\s\-\(\)\.]{7,}[0-9]', text_content)
        numbers.update(found_numbers)
    
    cleaned_numbers = set()
    for number in numbers:
        cleaned = re.sub(r'(?!^\+)[^\d]', '', number)
        if not cleaned.startswith('+'):
            cleaned = '+' + cleaned
        cleaned_numbers.add(cleaned)
    
    return list(cleaned_numbers)

def admin_panel(chat_id):
    markup = types.InlineKeyboardMarkup()
    
    btn1 = types.InlineKeyboardButton("➕ Add Numbers", callback_data="admin_add_numbers")
    btn2 = types.InlineKeyboardButton("🗑️ Remove Numbers", callback_data="admin_remove_numbers")
    btn3 = types.InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")
    btn4 = types.InlineKeyboardButton("👤 User Management", callback_data="admin_users")
    btn5 = types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")
    btn6 = types.InlineKeyboardButton("🔍 Find Number", callback_data="admin_find_number")
    btn7 = types.InlineKeyboardButton("🔄 Restart Bot", callback_data="admin_restart")
    btn8 = types.InlineKeyboardButton("⚙️ Channel Settings", callback_data="admin_channel_settings")
    
    markup.row(btn1, btn2)
    markup.row(btn3, btn4)
    markup.row(btn5, btn6)
    markup.row(btn7)
    markup.row(btn8)
    
    bot.send_message(chat_id, "🔧 Admin Panel\n\nSelect an option:", reply_markup=markup)

# Start command
@bot.message_handler(commands=['start', 'help', 'push', 'on'])  # Added /on command
def handle_commands(message):
    # NEW: Check if bot is disabled for non-admin users
    if not is_admin(message.from_user.id) and not is_bot_enabled():
        if message.text == '/push' or message.text == '/on':
            # These commands are for admins only
            bot.reply_to(message, "❌ Access denied!")
            return
            
        # For regular users when bot is disabled
        bot.reply_to(message, "⚠️ Service Unavailable!\nThe bot has been temporarily disabled by the admin for maintenance purposes.Please try again after a while.")
        return
    
    if message.text == '/push':
        if is_admin(message.from_user.id):
            # Disable the bot
            set_bot_status(False)
            bot.reply_to(message, "✅ Bot has been disabled. Users will be notified when trying to use it.")
        else:
            bot.reply_to(message, "❌ Access denied!")
        return
    
    if message.text == '/on':
        if is_admin(message.from_user.id):
            # Enable the bot and notify all users
            set_bot_status(True)
            success, failed = notify_all_users("✅ The bot is now back online! You can start using it again.")
            bot.reply_to(message, f"✅ Bot has been enabled. Notifications sent: {success} successful, {failed} failed.")
        else:
            bot.reply_to(message, "❌ Access denied!")
        return
    
    send_welcome(message)

def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    c = db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if result and result[0] == 1:
        bot.send_message(message.chat.id, "❌ You are banned from using this bot.")
        return
    
    if not result:
        join_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT INTO users (user_id, username, first_name, last_name, join_date) VALUES (?, ?, ?, ?, ?)",
                   (user_id, username, first_name, last_name, join_date))
    
    is_member, channel_type = check_membership(user_id, force_check=True)  # Force fresh check for new users
    main_channel, backup_channel, backup_link, otp_channel = get_channel_settings()
    
    if not is_member:
        if channel_type == "public":
            error_msg = "❌ You need to join our main channel to use this bot."
        elif channel_type == "private":
            error_msg = "❌ You need to join our backup channel to use this bot."
        else:
            error_msg = "❌ You need to join our channels to use this bot."
        
        markup = types.InlineKeyboardMarkup()
        main_btn = types.InlineKeyboardButton("📢 Main Channel", url=f"https://t.me/{main_channel.lstrip('@')}")
        backup_btn = types.InlineKeyboardButton("🔗 Backup Channel", url=backup_link)
        check_btn = types.InlineKeyboardButton("✅ Check Membership", callback_data="check_membership")
        
        markup.row(main_btn)
        markup.row(backup_btn)
        markup.row(check_btn)
        
        bot.send_message(message.chat.id, 
                        f"{error_msg}\n\n"
                        f"✅ Main Channel: {main_channel}\n"
                        f"✅ Backup Channel: Join via the button below\n\n"
                        "After joining both channels, click 'Check Membership'.",
                        reply_markup=markup)
        return
    
    show_main_menu(message.chat.id, user_id)

def show_main_menu(chat_id, user_id):
    markup = types.InlineKeyboardMarkup()
    
    c = db.execute("SELECT DISTINCT country FROM numbers WHERE is_used = 0")
    countries = c.fetchall()
    
    for country in countries:
        country_name = country[0]
        btn = types.InlineKeyboardButton(f" {country_name}", callback_data=f"country_{country_name}")
        markup.add(btn)
    
    if is_admin(user_id):
        admin_btn = types.InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")
        markup.add(admin_btn)
    
    bot.send_message(chat_id, 
                    "🌍 Welcome to the FutureTech Bot!\n\n"
                    "✨ Choose a country to get a unique phone number for verification purposes.\n"
                    "🔐 All numbers are private and secure.\n\n"
                    "```Select a country from the options below:```",
                    reply_markup=markup)

# Callback query handler
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        # NEW: Check if bot is disabled for non-admin users
        if not is_admin(call.from_user.id) and not is_bot_enabled():
            bot.answer_callback_query(call.id, "❌ Admin has disabled the bot. Please try again after some time.", show_alert=True)
            return
            
        # Handle change number cooldown check
        if call.data.startswith("change_"):
            user_id = call.from_user.id
            cooldown = check_cooldown(user_id)
            if cooldown > 0:
                bot.answer_callback_query(call.id, f"⏳ Please wait {cooldown} seconds before changing number", show_alert=True)
                return
                
        bot.answer_callback_query(call.id)
        Thread(target=process_callback, args=(call,)).start()
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")

def process_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    if call.data == "check_membership":
        is_member, channel_type = check_membership(user_id, force_check=True)  # Force fresh check
        
        if is_member:
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            show_main_menu(chat_id, user_id)
        else:
            if channel_type == "public":
                error_msg = "❌ You haven't joined the main channel yet!"
            elif channel_type == "private":
                error_msg = "❌ You haven't joined the backup channel yet!"
            else:
                error_msg = "❌ You haven't joined our channels yet! Please try again or contact support."
            
            try:
                bot.answer_callback_query(call.id, error_msg)
            except:
                pass
        return
    
    if call.data == "admin_panel":
        if is_admin(user_id):
            admin_panel(chat_id)
        else:
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
        return

    # Channel settings panel
    if call.data == "admin_channel_settings":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            except:
                pass
            return

        main_channel, backup_channel, backup_link, otp_channel = get_channel_settings()

        text = (
            "⚙️ *Channel Settings*\n\n"
            f"📢 Main Channel: `{main_channel}`\n"
            f"🔄 Backup Channel (ID): `{backup_channel}`\n"
            f"🔗 Backup Link: `{backup_link}`\n"
            f"🔑 OTP Channel: `{otp_channel}`\n\n"
            "Choose what you want to update:"
        )

        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("Main", callback_data="set_main"),
            types.InlineKeyboardButton("Backup", callback_data="set_backup")
        )
        markup.row(
            types.InlineKeyboardButton("Backup Link", callback_data="set_backup_link"),
            types.InlineKeyboardButton("OTP", callback_data="set_otp")
        )

        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
        return

    if call.data == "set_main":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        msg = bot.send_message(chat_id, "Send new Main Channel username (like @example):")
        bot.register_next_step_handler(msg, update_main)
        return

    if call.data == "set_backup":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        msg = bot.send_message(chat_id, "Send new Backup Channel chat ID (like -10018xxxxxx):")
        bot.register_next_step_handler(msg, update_backup)
        return

    if call.data == "set_backup_link":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        msg = bot.send_message(chat_id, "Send new Backup Channel invite link:")
        bot.register_next_step_handler(msg, update_backup_link)
        return

    if call.data == "set_otp":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        msg = bot.send_message(chat_id, "Send new OTP Channel username (like @OtpChannel):")
        bot.register_next_step_handler(msg, update_otp)
        return
    
    if call.data == "admin_restart":
        if is_admin(user_id):
            try:
                bot.edit_message_text("🔄 Restarting bot...", chat_id, message_id)
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception as e:
                bot.edit_message_text(f"❌ Error restarting: {str(e)}", chat_id, message_id)
        else:
            bot.answer_callback_query(call.id, "❌ Access denied!")
        return
    
    if call.data == "admin_find_number":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        msg = bot.send_message(chat_id, "🔍 Send the phone number to find (with country code, e.g., +1234567890):")
        bot.register_next_step_handler(msg, find_number_info)
        return
    
    if call.data.startswith("country_"):
        country = call.data.split("_", 1)[1]
        
        is_member, channel_type = check_membership(user_id)
        if not is_member:
            if channel_type == "public":
                error_msg = "❌ Please join our main channel first!"
            else:
                error_msg = "❌ Please join our backup channel first!"
            
            try:
                bot.answer_callback_query(call.id, error_msg)
            except:
                pass
            return
        
        c = db.execute("SELECT number FROM numbers WHERE country = ? AND is_used = 0 LIMIT 1", (country,))
        result = c.fetchone()
        
        if not result:
            try:
                bot.answer_callback_query(call.id, f"❌ No numbers available for {country}!")
            except:
                pass
            return
        
        number = result[0]
        
        use_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE numbers SET is_used = 1, used_by = ?, use_date = ? WHERE number = ?",
                   (user_id, use_date, number))
        
        update_user_stats(user_id)
        set_cooldown(user_id)
        check_and_notify_country_empty(country)

        main_channel, backup_channel, backup_link, otp_channel = get_channel_settings()
        
        markup = types.InlineKeyboardMarkup()
        change_btn = types.InlineKeyboardButton("🔄 Change Number", callback_data=f"change_{country}")
        otp_btn = types.InlineKeyboardButton("🔑 OTP GROUP", url=f"https://t.me/{otp_channel.lstrip('@')}")
        back_btn = types.InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_countries")
        
        markup.row(change_btn)
        markup.row(otp_btn)
        markup.row(back_btn)
        
        message_text = f"✅ Your Unique {country} Number:\n\n\t\t> `{number}` <\n\n"
        message_text += "• Tap on the number to copy it to clipboard\n"
        message_text += "• This is your personal one-time use number\n"
        message_text += "• Please do NOT use this number for any illegal activities ⚠️\n\n"
        message_text += "✨ Join our OTP channel to receive verification codes"
        
        try:
            bot.edit_message_text(message_text, chat_id, message_id, parse_mode='Markdown', reply_markup=markup)
        except Exception as e:
            logger.error(f"Error editing message: {e}")
        return
    
    if call.data.startswith("change_"):
        country = call.data.split("_", 1)[1]
        
        # Cooldown check is already handled in the callback_handler above
        # This ensures users see the popup before any processing happens
        
        is_member, channel_type = check_membership(user_id)
        if not is_member:
            if channel_type == "public":
                error_msg = "❌ Please join our main channel first!"
            else:
                error_msg = "❌ Please join our backup channel first!"
            
            try:
                bot.answer_callback_query(call.id, error_msg)
            except:
                pass
            return
        
        c = db.execute("SELECT number FROM numbers WHERE country = ? AND used_by = ? ORDER BY use_date DESC LIMIT 1", 
                       (country, user_id))
        old_number = c.fetchone()
        if old_number:
            db.execute("UPDATE numbers SET is_used = 2 WHERE number = ?", (old_number[0],))
        
        c = db.execute("SELECT number FROM numbers WHERE country = ? AND is_used = 0 LIMIT 1", (country,))
        result = c.fetchone()
        
        if not result:
            try:
                bot.answer_callback_query(call.id, f"❌ No numbers available for {country}!")
            except:
                pass
            return
        
        new_number = result[0]
        
        use_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE numbers SET is_used = 1, used_by = ?, use_date = ? WHERE number = ?",
                   (user_id, use_date, new_number))
        
        update_user_stats(user_id)
        set_cooldown(user_id)
        check_and_notify_country_empty(country)

        main_channel, backup_channel, backup_link, otp_channel = get_channel_settings()
        
        markup = types.InlineKeyboardMarkup()
        change_btn = types.InlineKeyboardButton("🔄 Change Number", callback_data=f"change_{country}")
        otp_btn = types.InlineKeyboardButton("🔑 OTP GROUP", url=f"https://t.me/{otp_channel.lstrip('@')}")
        back_btn = types.InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_countries")
        
        markup.row(change_btn)
        markup.row(otp_btn)
        markup.row(back_btn)
        
        message_text = f"✅ Your New {country} Number:\n\n\t\t> `{new_number}` <\n\n"
        message_text += "• Tap on the number to copy it to clipboard\n"
        message_text += "• This is your personal one-time use number\n"
        message_text += "• Please do NOT use this number for any illegal activities ⚠️\n\n"
        message_text += "✨ Join our OTP channel to receive verification codes"
        
        try:
            bot.edit_message_text(message_text, chat_id, message_id, parse_mode='Markdown', reply_markup=markup)
        except Exception as e:
            logger.error(f"Error editing message: {e}")
        return
    
    if call.data == "back_to_countries":
        try:
            bot.delete_message(chat_id, message_id)
        except:
            pass
        show_main_menu(chat_id, user_id)
        return
    
    if call.data == "admin_add_numbers":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        msg = bot.send_message(chat_id, "🌍 Please send the country name with flag (e.g., 🇺🇸 United States):")
        bot.register_next_step_handler(msg, process_country_name)
        return
    
    if call.data == "admin_remove_numbers":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        c = db.execute("SELECT DISTINCT country FROM numbers")
        countries = c.fetchall()
        
        markup = types.InlineKeyboardMarkup()
        for country in countries:
            btn = types.InlineKeyboardButton(country[0], callback_data=f"remove_{country[0]}")
            markup.add(btn)
        
        bot.send_message(chat_id, "Select a country to remove all its numbers:", reply_markup=markup)
        return
    
    if call.data.startswith("remove_"):
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        country = call.data.split("_", 1)[1]
        
        markup = types.InlineKeyboardMarkup()
        confirm_btn = types.InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirm_remove_{country}")
        cancel_btn = types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove")
        markup.row(confirm_btn, cancel_btn)
        
        bot.send_message(chat_id, f"Are you sure you want to delete ALL numbers for {country}?", reply_markup=markup)
        return
    
    if call.data.startswith("confirm_remove_"):
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        country = call.data.split("_", 2)[2]
        
        # Use a retry mechanism for database operations
        max_retries = 3
        for attempt in range(max_retries):
            try:
                db.execute("DELETE FROM numbers WHERE country = ?", (country,))
                bot.send_message(chat_id, f"✅ All numbers for {country} have been removed.")
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"Database locked, retrying {attempt + 1}/{max_retries}")
                    time.sleep(1)  # Wait before retrying
                else:
                    logger.error(f"Failed to delete numbers after {max_retries} attempts: {e}")
                    bot.send_message(chat_id, f"❌ Error deleting numbers for {country}. Please try again.")
                    break
        return
    
    if call.data == "cancel_remove":
        bot.send_message(chat_id, "❌ Deletion cancelled.")
        return
    
    if call.data == "admin_stats":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        total_used, active_users = get_today_stats()
        country_stats = get_country_stats()
        
        stats_text = f"📊 Today's Stats:\n\n• Numbers Used: {total_used}\n• Active Users: {active_users}\n\n"
        stats_text += "📈 Country-wise Stats:\n"
        
        for country, total, used in country_stats:
            used = used if used is not None else 0
            available = total - used
            stats_text += f"• {country}: {used}/{total} (Available: {available})\n"
        
        low_numbers = check_low_numbers()
        if low_numbers:
            stats_text += "\n⚠️ Low Numbers Alert:\n"
            for country, available in low_numbers:
                stats_text += f"• {country}: Only {available} numbers left!\n"
        
        bot.send_message(chat_id, stats_text)
        return
    
    if call.data == "admin_users":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        markup = types.InlineKeyboardMarkup()
        btn1 = types.InlineKeyboardButton("👤 Find User", callback_data="admin_find_user")
        btn2 = types.InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban_user")
        btn3 = types.InlineKeyboardButton("✅ Unban User", callback_data="admin_unban_user")
        markup.row(btn1)
        markup.row(btn2, btn3)
        
        bot.send_message(chat_id, "👤 User Management\n\nSelect an option:", reply_markup=markup)
        return
    
    if call.data == "admin_find_user":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        msg = bot.send_message(chat_id, "Send the user ID to find:")
        bot.register_next_step_handler(msg, find_user)
        return
    
    if call.data == "admin_ban_user":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        msg = bot.send_message(chat_id, "Send the user ID to ban:")
        bot.register_next_step_handler(msg, ban_user)
        return
    
    if call.data == "admin_unban_user":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        msg = bot.send_message(chat_id, "Send the user ID to unban:")
        bot.register_next_step_handler(msg, unban_user)
        return
    
    if call.data == "admin_broadcast":
        if not is_admin(user_id):
            try:
                bot.answer_callback_query(call.id, "❌ Access denied!")
            except:
                pass
            return
        
        msg = bot.send_message(chat_id, "Send the message you want to broadcast to all users:")
        bot.register_next_step_handler(msg, broadcast_message)
        return

# New function to find number information
def find_number_info(message):
    number = message.text.strip()
    
    # Clean the number format
    cleaned_number = re.sub(r'(?!^\+)[^\d]', '', number)
    if not cleaned_number.startswith('+'):
        cleaned_number = '+' + cleaned_number
    
    c = db.execute("""
        SELECT n.number, n.country, n.use_date, n.used_by, 
               u.username, u.first_name, u.last_name, u.user_id
        FROM numbers n
        LEFT JOIN users u ON n.used_by = u.user_id
        WHERE n.number = ?
    """, (cleaned_number,))
    
    result = c.fetchone()
    
    if result:
        number, country, use_date, used_by, username, first_name, last_name, user_id = result
        
        if used_by:
            user_info = f"👤 User Information:\n\n"
            user_info += f"• User ID: {user_id}\n"
            user_info += f"• Username: @{username if username else 'N/A'}\n"
            user_info += f"• Full Name: {first_name} {last_name if last_name else ''}\n"
            user_info += f"• Number Used: {number}\n"
            user_info += f"• Country: {country}\n"
            user_info += f"• Use Date: {use_date}"
        else:
            user_info = f"ℹ️ Number Information:\n\n"
            user_info += f"• Number: {number}\n"
            user_info += f"• Country: {country}\n"
            user_info += f"• Status: {'Available' if not used_by else 'Used'}\n"
        
        bot.send_message(message.chat.id, user_info)
    else:
        bot.send_message(message.chat.id, f"❌ Number {number} not found in the database.")

# Admin functions
def process_country_name(message):
    country_name = message.text
    msg = bot.send_message(message.chat.id, f"📤 Now send me a file with numbers for {country_name}")
    bot.register_next_step_handler(msg, process_number_file, country_name)

def process_number_file(message, country_name):
    if not message.document:
        bot.send_message(message.chat.id, "❌ Please send a file.")
        return
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error downloading file: {str(e)}")
        return
    
    try:
        numbers = extract_numbers_from_content(downloaded_file, message.document.file_name)
        
        if not numbers:
            bot.send_message(message.chat.id, "❌ No valid phone numbers found in the file.")
            return
        
        added = 0
        skipped = 0
        
        for number in numbers:
            c = db.execute("SELECT id FROM numbers WHERE number = ?", (number,))
            if c.fetchone():
                skipped += 1
                continue
            
            try:
                db.execute("INSERT INTO numbers (country, number) VALUES (?, ?)", (country_name, number))
                added += 1
            except:
                skipped += 1
        
        c = db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = c.fetchall()
        
        for user in users:
            try:
                bot.send_message(user[0], f"🆕 New numbers added for {country_name}! Use /start to get one.")
            except:
                pass
        
        bot.send_message(message.chat.id, 
                        f"✅ Numbers added successfully for {country_name}!\n\n"
                        f"Added: {added}\nSkipped (duplicates): {skipped}\n"
                        f"Total processed: {len(numbers)}")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error processing file: {str(e)}")

def find_user(message):
    try:
        user_id = int(message.text)
        c = db.execute("SELECT user_id, username, first_name, last_name, join_date, is_banned FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        
        if user:
            user_id, username, first_name, last_name, join_date, is_banned = user
            status = "Banned" if is_banned else "Active"
            user_info = f"👤 User Info:\n\nID: {user_id}\nUsername: @{username}\nName: {first_name} {last_name}\nJoin Date: {join_date}\nStatus: {status}"
            
            today = datetime.now().strftime("%Y-%m-%d")
            c = db.execute("SELECT numbers_today FROM user_stats WHERE user_id = ? AND date = ?", (user_id, today))
            result = c.fetchone()
            numbers_today = result[0] if result else 0
            
            user_info += f"\nNumbers Today: {numbers_today}"
            
            bot.send_message(message.chat.id, user_info)
        else:
            bot.send_message(message.chat.id, "❌ User not found.")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid user ID.")

def ban_user(message):
    try:
        user_id = int(message.text)
        db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        
        bot.send_message(message.chat.id, f"✅ User {user_id} has been banned.")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid user ID.")

def unban_user(message):
    try:
        user_id = int(message.text)
        db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        
        bot.send_message(message.chat.id, f"✅ User {user_id} has been unbanned.")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid user ID.")

def broadcast_message(message):
    text = message.text
    c = db.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = c.fetchall()
    
    total = len(users)
    success = 0
    failed = 0
    
    bot.send_message(message.chat.id, f"📢 Broadcasting to {total} users...")
    
    for user in users:
        try:
            bot.send_message(user[0], f"📢 Announcement from Admin:\n\n{text}")
            success += 1
        except:
            failed += 1
        
        time.sleep(0.1)
    
    bot.send_message(message.chat.id, f"✅ Broadcast completed!\n\nSuccess: {success}\nFailed: {failed}")

# === Channel update step handlers ===
def update_main(message):
    new_main = message.text.strip()
    update_channel_settings(main=new_main)
    bot.send_message(message.chat.id, f"✅ Main Channel updated to: {new_main}")

def update_backup(message):
    new_backup = message.text.strip()
    update_channel_settings(backup=new_backup)
    bot.send_message(message.chat.id, f"✅ Backup Channel ID updated to: {new_backup}")

def update_backup_link(message):
    new_link = message.text.strip()
    update_channel_settings(link=new_link)
    bot.send_message(message.chat.id, f"✅ Backup Channel Link updated to: {new_link}")

def update_otp(message):
    new_otp = message.text.strip()
    update_channel_settings(otp=new_otp)
    bot.send_message(message.chat.id, f"✅ OTP Channel updated to: {new_otp}")

# Run the bot
if __name__ == "__main__":
    print("🤖 Bot is running...")
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        time.sleep(5)
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
