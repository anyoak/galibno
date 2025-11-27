import logging
import sqlite3
import time
import os
import csv
import re
import threading
import sys
from datetime import datetime
from threading import Thread

import telebot
from telebot import types

# =======================
# Logging configuration
# =======================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =======================
# Bot configuration
# =======================

API_TOKEN = "8490533685:AAHsZW-Do8ioSQHlU4SCDh3RlvMdBPpz2To"   # <-- এখানে নতুন টোকেন দাও
ADMIN_IDS = [6577308099, 5878787791]

# Default channel values
DEFAULT_MAIN_CHANNEL = '@mailtwist'
DEFAULT_BACKUP_CHANNEL = '-1002110340097'
DEFAULT_BACKUP_CHANNEL_LINK = 'https://t.me/+FFG2MEKtQsxkMTQ9'
DEFAULT_OTP_CHANNEL = '@OrangeTrack'

if ':' not in API_TOKEN:
    raise ValueError('Invalid bot token format.')

bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=4)

# =======================
# Database setup (singleton)
# =======================

class Database:
    _instance = None
    _connection = None
    _lock = threading.RLock()  # Thread safety

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._connection = sqlite3.connect(
                'numbers.db',
                check_same_thread=False,
                timeout=30
            )
            cls._connection.row_factory = sqlite3.Row
            cls.init_db()
        return cls._instance

    @classmethod
    def init_db(cls):
        with cls._lock:
            c = cls._connection.cursor()

            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (user_id INTEGER PRIMARY KEY,
                          username TEXT,
                          first_name TEXT,
                          last_name TEXT,
                          join_date TEXT,
                          is_banned INTEGER DEFAULT 0)''')

            c.execute('''CREATE TABLE IF NOT EXISTS numbers
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          country TEXT,
                          number TEXT UNIQUE,
                          is_used INTEGER DEFAULT 0,
                          used_by INTEGER,
                          use_date TEXT)''')

            c.execute('''CREATE TABLE IF NOT EXISTS countries
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          name TEXT UNIQUE,
                          code TEXT)''')

            c.execute('''CREATE TABLE IF NOT EXISTS user_stats
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id INTEGER,
                          date TEXT,
                          numbers_today INTEGER DEFAULT 0)''')

            c.execute('''CREATE TABLE IF NOT EXISTS cooldowns
                         (user_id INTEGER PRIMARY KEY,
                          timestamp INTEGER)''')

            c.execute('''CREATE TABLE IF NOT EXISTS notifications
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          country TEXT,
                          notified INTEGER DEFAULT 0,
                          last_notified TEXT)''')

            c.execute('''CREATE TABLE IF NOT EXISTS bot_status
                         (id INTEGER PRIMARY KEY CHECK (id = 1),
                          is_enabled INTEGER DEFAULT 1)''')

            c.execute(
                "INSERT OR IGNORE INTO bot_status (id, is_enabled) VALUES (1, 1)"
            )

            c.execute('''CREATE TABLE IF NOT EXISTS channel_settings
                         (id INTEGER PRIMARY KEY CHECK (id = 1),
                          main_channel TEXT,
                          backup_channel TEXT,
                          backup_channel_link TEXT,
                          otp_channel TEXT)''')

            c.execute(
                """INSERT OR IGNORE INTO channel_settings
                   (id, main_channel, backup_channel, backup_channel_link, otp_channel)
                   VALUES (1, ?, ?, ?, ?)""",
                (
                    DEFAULT_MAIN_CHANNEL,
                    DEFAULT_BACKUP_CHANNEL,
                    DEFAULT_BACKUP_CHANNEL_LINK,
                    DEFAULT_OTP_CHANNEL
                )
            )

            cls._connection.commit()

    @classmethod
    def get_connection(cls):
        return cls._connection

    @classmethod
    def execute(cls, query, params=()):
        with cls._lock:
            try:
                c = cls._connection.cursor()
                c.execute(query, params)
                cls._connection.commit()
                return c
            except sqlite3.Error as e:
                logger.error(f"Database error: {e}")
                # Try reconnect
                for attempt in range(2):
                    try:
                        time.sleep(1)
                        cls._connection = sqlite3.connect(
                            'numbers.db',
                            check_same_thread=False,
                            timeout=30
                        )
                        cls._connection.row_factory = sqlite3.Row
                        c = cls._connection.cursor()
                        c.execute(query, params)
                        cls._connection.commit()
                        return c
                    except sqlite3.Error as e2:
                        logger.error(f"Database reconnection failed (attempt {attempt+1}): {e2}")
                raise

# Initialize DB
db = Database()

# =======================
# Channel settings helpers
# =======================

def get_channel_settings():
    c = db.execute(
        "SELECT main_channel, backup_channel, backup_channel_link, otp_channel "
        "FROM channel_settings WHERE id = 1"
    )
    row = c.fetchone()
    if row:
        return (
            row['main_channel'],
            row['backup_channel'],
            row['backup_channel_link'],
            row['otp_channel'],
        )
    return (
        DEFAULT_MAIN_CHANNEL,
        DEFAULT_BACKUP_CHANNEL,
        DEFAULT_BACKUP_CHANNEL_LINK,
        DEFAULT_OTP_CHANNEL,
    )


def update_channel_settings(main=None, backup=None, link=None, otp=None):
    current_main, current_backup, current_link, current_otp = get_channel_settings()

    main = main if main not in (None, '') else current_main
    backup = backup if backup not in (None, '') else current_backup
    link = link if link not in (None, '') else current_link
    otp = otp if otp not in (None, '') else current_otp

    db.execute(
        """UPDATE channel_settings
           SET main_channel=?, backup_channel=?, backup_channel_link=?, otp_channel=?
           WHERE id=1""",
        (main, backup, link, otp),
    )

# =======================
# Bot status helpers
# =======================

def is_bot_enabled():
    c = db.execute("SELECT is_enabled FROM bot_status WHERE id = 1")
    result = c.fetchone()
    return (result[0] == 1) if result else True


def set_bot_status(enabled: bool):
    status = 1 if enabled else 0
    db.execute("UPDATE bot_status SET is_enabled = ? WHERE id = 1", (status,))
    return True

# =======================
# Notify all users
# =======================

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
        time.sleep(0.1)

    return success, failed

# =======================
# Notification helpers
# =======================

def notify_admins_country_empty(country):
    message = (
        "⚠️ *COUNTRY EMPTY ALERT*\n\n"
        f"🛑 *{country}* has run out of numbers!\n\n"
        "Please add more numbers for this country."
    )
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, message, parse_mode='Markdown')
            logger.info(f"Empty country notification sent to admin {admin_id} for {country}")
        except Exception as e:
            logger.error(f"Error notifying admin {admin_id}: {e}")


def notify_admins_country_low(country, available_count):
    message = (
        "🔔 *LOW NUMBERS ALERT*\n\n"
        f"📉 *{country}* is running low!\n\n"
        f"Only *{available_count}* numbers remaining."
    )
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, message, parse_mode='Markdown')
            logger.info(f"Low numbers notification sent to admin {admin_id} for {country}")
        except Exception as e:
            logger.error(f"Error notifying admin {admin_id} for low numbers: {e}")


def check_country_availability(country):
    c = db.execute(
        "SELECT COUNT(*) AS cnt FROM numbers WHERE country = ? AND is_used = 0",
        (country,),
    )
    row = c.fetchone()
    return row[0] if row else 0


def check_and_notify_country_status(country):
    available = check_country_availability(country)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c = db.execute(
        "SELECT notified, last_notified FROM notifications WHERE country = ?",
        (country,),
    )
    result = c.fetchone()

    if available == 0:
        # Empty
        if not result or result['notified'] == 0:
            notify_admins_country_empty(country)
            if result:
                db.execute(
                    "UPDATE notifications SET notified = 1, last_notified = ? WHERE country = ?",
                    (current_time, country),
                )
            else:
                db.execute(
                    "INSERT INTO notifications (country, notified, last_notified) VALUES (?, 1, ?)",
                    (country, current_time),
                )
        else:
            last_notified = datetime.strptime(result['last_notified'], "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - last_notified).total_seconds() > 6 * 3600:
                notify_admins_country_empty(country)
                db.execute(
                    "UPDATE notifications SET last_notified = ? WHERE country = ?",
                    (current_time, country),
                )
    elif available < 5:
        # Low
        if not result or result['notified'] != 2:
            notify_admins_country_low(country, available)
            if result:
                db.execute(
                    "UPDATE notifications SET notified = 2, last_notified = ? WHERE country = ?",
                    (current_time, country),
                )
            else:
                db.execute(
                    "INSERT INTO notifications (country, notified, last_notified) VALUES (?, 2, ?)",
                    (country, current_time),
                )
    else:
        # Reset
        if result and result['notified'] != 0:
            db.execute(
                "UPDATE notifications SET notified = 0 WHERE country = ?",
                (country,),
            )


def check_all_countries_status(chat_id):
    c = db.execute("SELECT DISTINCT country FROM numbers")
    countries = c.fetchall()

    status_report = "📊 *COUNTRY STATUS REPORT*\n\n"

    for row in countries:
        country = row[0]
        available = check_country_availability(country)
        if available == 0:
            status_report += f"🛑 *{country}:* EMPTY (0 numbers)\n"
        elif available < 5:
            status_report += f"⚠️ *{country}:* LOW ({available} numbers)\n"
        else:
            status_report += f"✅ *{country}:* OK ({available} numbers)\n"

    c = db.execute("SELECT COUNT(*) FROM numbers WHERE is_used = 0")
    total_available = c.fetchone()[0]

    status_report += f"\n📈 *SUMMARY*\nTotal available numbers: {total_available}"

    bot.send_message(chat_id, status_report, parse_mode='Markdown')

# =======================
# Utility helpers
# =======================

def update_user_stats(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    c = db.execute(
        "SELECT numbers_today FROM user_stats WHERE user_id = ? AND date = ?",
        (user_id, today),
    )
    result = c.fetchone()
    if result:
        db.execute(
            "UPDATE user_stats SET numbers_today = numbers_today + 1 "
            "WHERE user_id = ? AND date = ?",
            (user_id, today),
        )
    else:
        db.execute(
            "INSERT INTO user_stats (user_id, date, numbers_today) VALUES (?, ?, 1)",
            (user_id, today),
        )


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def check_membership(user_id, force_check=False):
    """
    Check if user is member of both main & backup channels.
    Returns: (is_member: bool, type: "public"/"private"/"both")
    """
    cache_key = f"member_{user_id}"

    # Cache
    if not force_check and hasattr(check_membership, 'cache'):
        cache_item = check_membership.cache.get(cache_key)
        if cache_item and time.time() - cache_item['time'] < 300:
            return cache_item['result']

    main_channel, backup_channel, _, _ = get_channel_settings()

    max_retries = 3
    retry_delay = 1

    main_ok = False
    backup_ok = False

    # Main channel
    for attempt in range(max_retries):
        try:
            member = bot.get_chat_member(main_channel, user_id)
            if member.status in ['member', 'administrator', 'creator']:
                main_ok = True
            break
        except Exception as e:
            logger.error(f"Main channel check failed (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    if not main_ok:
        result = (False, "public")
    else:
        # Backup channel
        for attempt in range(max_retries):
            try:
                backup_member = bot.get_chat_member(backup_channel, user_id)
                if backup_member.status in ['member', 'administrator', 'creator']:
                    backup_ok = True
                break
            except Exception as e:
                logger.error(f"Backup channel check failed (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        if not backup_ok:
            result = (False, "private")
        else:
            result = (True, "both")

    if not hasattr(check_membership, 'cache'):
        check_membership.cache = {}
    check_membership.cache[cache_key] = {'result': result, 'time': time.time()}
    return result


def get_today_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    c = db.execute(
        "SELECT COUNT(*) FROM numbers WHERE use_date LIKE ?",
        (f"{today}%",),
    )
    total_used = c.fetchone()[0]

    c = db.execute(
        "SELECT COUNT(DISTINCT user_id) FROM user_stats WHERE date = ?",
        (today,),
    )
    active_users = c.fetchone()[0]

    return total_used, active_users


def get_country_stats():
    c = db.execute(
        "SELECT country, COUNT(*) as total, SUM(is_used) as used "
        "FROM numbers GROUP BY country"
    )
    return c.fetchall()


def get_user_stats(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    c = db.execute(
        "SELECT numbers_today FROM user_stats WHERE user_id = ? AND date = ?",
        (user_id, today),
    )
    result = c.fetchone()
    return result[0] if result else 0


def check_low_numbers():
    c = db.execute(
        "SELECT country, COUNT(*) as available "
        "FROM numbers WHERE is_used = 0 GROUP BY country"
    )
    results = c.fetchall()
    low_countries = []
    for row in results:
        country = row[0]
        available = row[1]
        if available < 5:
            low_countries.append((country, available))
    return low_countries


def set_cooldown(user_id):
    db.execute(
        "REPLACE INTO cooldowns (user_id, timestamp) VALUES (?, ?)",
        (user_id, int(time.time())),
    )


def check_cooldown(user_id):
    c = db.execute("SELECT timestamp FROM cooldowns WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    if result:
        elapsed = int(time.time()) - result[0]
        if elapsed < 5:
            return 5 - elapsed
    return 0


def extract_numbers_from_content(content, filename):
    numbers = set()
    file_ext = os.path.splitext(filename)[1].lower() if filename else '.txt'

    pattern = r'\+?[0-9][0-9\s\-\.\,]{7,}[0-9]'

    if file_ext == '.csv':
        try:
            csv_content = content.decode('utf-8').splitlines()
            reader = csv.reader(csv_content)
            for row in reader:
                for item in row:
                    found = re.findall(pattern, item)
                    numbers.update(found)
        except Exception:
            text_content = content.decode('utf-8', errors='ignore')
            found = re.findall(pattern, text_content)
            numbers.update(found)
    else:
        try:
            text_content = content.decode('utf-8')
        except Exception:
            text_content = content.decode('utf-8', errors='ignore')
        found = re.findall(pattern, text_content)
        numbers.update(found)

    cleaned_numbers = set()
    for number in numbers:
        cleaned = re.sub(r'(?!^\+)[^\d]', '', number)
        if not cleaned.startswith('+'):
            cleaned = '+' + cleaned
        cleaned_numbers.add(cleaned)

    return list(cleaned_numbers)

# =======================
# Admin panel
# =======================

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
    btn9 = types.InlineKeyboardButton("📋 Country Status", callback_data="admin_country_status")

    markup.row(btn1, btn2)
    markup.row(btn3, btn4)
    markup.row(btn5, btn6)
    markup.row(btn7, btn9)
    markup.row(btn8)

    bot.send_message(
        chat_id,
        "🔧 Admin Panel\n\nSelect an option:",
        reply_markup=markup
    )

# =======================
# /start, /help, /push, /on
# =======================

@bot.message_handler(commands=['start', 'help', 'push', 'on'])
def handle_commands(message):
    user_id = message.from_user.id

    # Bot disabled for non-admins
    if not is_admin(user_id) and not is_bot_enabled():
        if message.text in ['/push', '/on']:
            bot.reply_to(message, "❌ Access denied!")
            return

        bot.reply_to(
            message,
            "```⚠️ Service Unavailable!\n"
            "The bot has been temporarily disabled by the admin for maintenance purposes."
            "Please try again after a while.```"
        )
        return

    if message.text == '/push':
        if is_admin(user_id):
            set_bot_status(False)
            bot.reply_to(message, "✅ Bot has been disabled. Users will be notified when trying to use it.")
        else:
            bot.reply_to(message, "❌ Access denied!")
        return

    if message.text == '/on':
        if is_admin(user_id):
            set_bot_status(True)
            success, failed = notify_all_users(
                "✅ The bot is now back online! You can start using it again."
            )
            bot.reply_to(
                message,
                f"✅ Bot has been enabled. Notifications sent: {success} successful, {failed} failed."
            )
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
        db.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, join_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, username, first_name, last_name, join_date),
        )

    # Admins bypass membership
    if is_admin(user_id):
        show_main_menu(message.chat.id, user_id)
        return

    is_member, channel_type = check_membership(user_id, force_check=True)
    main_channel, backup_channel, backup_link, otp_channel = get_channel_settings()

    if not is_member:
        if channel_type == "public":
            error_msg = "❌ You need to join our main channel to use this bot."
        elif channel_type == "private":
            error_msg = "❌ You need to join our backup channel to use this bot."
        else:
            error_msg = "❌ You need to join our channels to use this bot."

        markup = types.InlineKeyboardMarkup()
        main_btn = types.InlineKeyboardButton(
            "📢 Main Channel",
            url=f"https://t.me/{main_channel.lstrip('@')}"
        )
        backup_btn = types.InlineKeyboardButton(
            "🔗 Backup Channel",
            url=backup_link
        )
        check_btn = types.InlineKeyboardButton(
            "✅ Check Membership",
            callback_data="check_membership"
        )

        markup.row(main_btn)
        markup.row(backup_btn)
        markup.row(check_btn)

        bot.send_message(
            message.chat.id,
            f"{error_msg}\n\n"
            f"✅ Main Channel: {main_channel}\n"
            f"✅ Backup Channel: Join via the button below\n\n"
            "After joining both channels, click 'Check Membership'.",
            reply_markup=markup
        )
        return

    show_main_menu(message.chat.id, user_id)


def show_main_menu(chat_id, user_id):
    markup = types.InlineKeyboardMarkup()

    c = db.execute("SELECT DISTINCT country FROM numbers WHERE is_used = 0")
    countries = c.fetchall()

    for row in countries:
        country_name = row[0]
        btn = types.InlineKeyboardButton(
            f" {country_name}",
            callback_data=f"country_{country_name}"
        )
        markup.add(btn)

    if is_admin(user_id):
        admin_btn = types.InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")
        markup.add(admin_btn)

    bot.send_message(
        chat_id,
        "🌍 Welcome to the Global Virtual Number Hub!\n\n"
        "✨ Choose a country to get a unique phone number for verification purposes.\n"
        "🔐 All numbers are private and secure.\n\n"
        "⏬ Select a country from the options below:",
        reply_markup=markup
    )

# =======================
# Callback handler
# =======================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        if not is_admin(call.from_user.id) and not is_bot_enabled():
            bot.answer_callback_query(
                call.id,
                "❌ Admin has disabled the bot. Please try again after some time.",
                show_alert=True
            )
            return

        # Cooldown for change_
        if call.data.startswith("change_"):
            user_id = call.from_user.id
            cooldown = check_cooldown(user_id)
            if cooldown > 0:
                bot.answer_callback_query(
                    call.id,
                    f"⏳ Please wait {cooldown} seconds before changing number",
                    show_alert=True
                )
                return

        # Process in separate thread but with try/except inside
        Thread(target=process_callback, args=(call,)).start()
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")


def process_callback(call):
    try:
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id

        # ========= Check membership button =========
        if call.data == "check_membership":
            is_member, channel_type = check_membership(user_id, force_check=True)
            if is_member:
                try:
                    bot.delete_message(chat_id, message_id)
                except Exception:
                    pass
                bot.answer_callback_query(call.id, "✅ Membership verified!")
                show_main_menu(chat_id, user_id)
            else:
                if channel_type == "public":
                    error_msg = "❌ You haven't joined the main channel yet!"
                elif channel_type == "private":
                    error_msg = "❌ You haven't joined the backup channel yet!"
                else:
                    error_msg = "❌ You haven't joined our channels yet! Please try again or contact support."

                try:
                    bot.answer_callback_query(call.id, error_msg, show_alert=True)
                except Exception:
                    pass
            return

        # ========= Admin panel =========
        if call.data == "admin_panel":
            if is_admin(user_id):
                bot.answer_callback_query(call.id)
                admin_panel(chat_id)
            else:
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return

        # ========= Channel settings panel =========
        if call.data == "admin_channel_settings":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
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
                types.InlineKeyboardButton("Backup", callback_data="set_backup"),
            )
            markup.row(
                types.InlineKeyboardButton("Backup Link", callback_data="set_backup_link"),
                types.InlineKeyboardButton("OTP", callback_data="set_otp"),
            )

            bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
            bot.answer_callback_query(call.id)
            return

        if call.data == "set_main":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(chat_id, "Send new Main Channel username (like @example):")
            bot.register_next_step_handler(msg, update_main)
            bot.answer_callback_query(call.id)
            return

        if call.data == "set_backup":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(chat_id, "Send new Backup Channel chat ID (like -10018xxxxxx):")
            bot.register_next_step_handler(msg, update_backup)
            bot.answer_callback_query(call.id)
            return

        if call.data == "set_backup_link":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(chat_id, "Send new Backup Channel invite link:")
            bot.register_next_step_handler(msg, update_backup_link)
            bot.answer_callback_query(call.id)
            return

        if call.data == "set_otp":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(chat_id, "Send new OTP Channel username (like @OtpChannel):")
            bot.register_next_step_handler(msg, update_otp)
            bot.answer_callback_query(call.id)
            return

        # ========= Restart bot =========
        if call.data == "admin_restart":
            if is_admin(user_id):
                bot.edit_message_text("🔄 Restarting bot...", chat_id, message_id)
                bot.answer_callback_query(call.id)
                os.execv(sys.executable, [sys.executable] + sys.argv)
            else:
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return

        # ========= Find number =========
        if call.data == "admin_find_number":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(
                chat_id,
                "🔍 Send the phone number to find (with country code, e.g., +1234567890):"
            )
            bot.register_next_step_handler(msg, find_number_info)
            bot.answer_callback_query(call.id)
            return

        # ========= Country status =========
        if call.data == "admin_country_status":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            check_all_countries_status(chat_id)
            bot.answer_callback_query(call.id)
            return

        # ========= Country select =========
        if call.data.startswith("country_"):
            country = call.data.split("_", 1)[1]

            is_member, channel_type = check_membership(user_id)
            if not is_member and not is_admin(user_id):
                if channel_type == "public":
                    error_msg = "❌ Please join our main channel first!"
                else:
                    error_msg = "❌ Please join our backup channel first!"
                bot.answer_callback_query(call.id, error_msg, show_alert=True)
                return

            c = db.execute(
                "SELECT number FROM numbers WHERE country = ? AND is_used = 0 LIMIT 1",
                (country,),
            )
            result = c.fetchone()

            if not result:
                bot.answer_callback_query(call.id, f"❌ No numbers available for {country}!", show_alert=True)
                return

            number = result[0]
            use_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.execute(
                "UPDATE numbers SET is_used = 1, used_by = ?, use_date = ? WHERE number = ?",
                (user_id, use_date, number),
            )

            update_user_stats(user_id)
            set_cooldown(user_id)
            check_and_notify_country_status(country)

            _, _, _, otp_channel = get_channel_settings()

            markup = types.InlineKeyboardMarkup()
            change_btn = types.InlineKeyboardButton("🔄 Change Number", callback_data=f"change_{country}")
            otp_btn = types.InlineKeyboardButton(
                "🔑 OTP GROUP",
                url=f"https://t.me/{otp_channel.lstrip('@')}"
            )
            back_btn = types.InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_countries")

            markup.row(change_btn)
            markup.row(otp_btn)
            markup.row(back_btn)

            message_text = (
                f"✅ Your Unique {country} Number:\n\n\t\t> `{number}` <\n\n"
                "• Tap on the number to copy it to clipboard\n"
                "• This is your personal one-time use number\n"
                "• Please do NOT use this number for any illegal activities ⚠️\n\n"
                "✨ Join our OTP channel to receive verification codes"
            )

            try:
                bot.edit_message_text(
                    message_text,
                    chat_id,
                    message_id,
                    parse_mode='Markdown',
                    reply_markup=markup
                )
            except Exception as e:
                logger.error(f"Error editing message: {e}")

            bot.answer_callback_query(call.id)
            return

        # ========= Change number =========
        if call.data.startswith("change_"):
            country = call.data.split("_", 1)[1]

            is_member, channel_type = check_membership(user_id)
            if not is_member and not is_admin(user_id):
                if channel_type == "public":
                    error_msg = "❌ Please join our main channel first!"
                else:
                    error_msg = "❌ Please join our backup channel first!"
                bot.answer_callback_query(call.id, error_msg, show_alert=True)
                return

            c = db.execute(
                "SELECT number FROM numbers WHERE country = ? AND used_by = ? "
                "ORDER BY use_date DESC LIMIT 1",
                (country, user_id),
            )
            old_number = c.fetchone()
            if old_number:
                db.execute("UPDATE numbers SET is_used = 2 WHERE number = ?", (old_number[0],))

            c = db.execute(
                "SELECT number FROM numbers WHERE country = ? AND is_used = 0 LIMIT 1",
                (country,),
            )
            result = c.fetchone()
            if not result:
                bot.answer_callback_query(call.id, f"❌ No numbers available for {country}!", show_alert=True)
                return

            new_number = result[0]
            use_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.execute(
                "UPDATE numbers SET is_used = 1, used_by = ?, use_date = ? WHERE number = ?",
                (user_id, use_date, new_number),
            )

            update_user_stats(user_id)
            set_cooldown(user_id)
            check_and_notify_country_status(country)

            _, _, _, otp_channel = get_channel_settings()

            markup = types.InlineKeyboardMarkup()
            change_btn = types.InlineKeyboardButton("🔄 Change Number", callback_data=f"change_{country}")
            otp_btn = types.InlineKeyboardButton(
                "🔑 OTP GROUP",
                url=f"https://t.me/{otp_channel.lstrip('@')}"
            )
            back_btn = types.InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_countries")

            markup.row(change_btn)
            markup.row(otp_btn)
            markup.row(back_btn)

            message_text = (
                f"✅ Your New {country} Number:\n\n\t\t> `{new_number}` <\n\n"
                "• Tap on the number to copy it to clipboard\n"
                "• This is your personal one-time use number\n"
                "• Please do NOT use this number for any illegal activities ⚠️\n\n"
                "✨ Join our OTP channel to receive verification codes"
            )

            try:
                bot.edit_message_text(
                    message_text,
                    chat_id,
                    message_id,
                    parse_mode='Markdown',
                    reply_markup=markup
                )
            except Exception as e:
                logger.error(f"Error editing message: {e}")

            bot.answer_callback_query(call.id)
            return

        # ========= Back to menu =========
        if call.data == "back_to_countries":
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
            show_main_menu(chat_id, user_id)
            bot.answer_callback_query(call.id)
            return

        # ========= Admin add numbers =========
        if call.data == "admin_add_numbers":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(
                chat_id,
                "🌍 Please send the country name with flag (e.g., 🇺🇸 United States):"
            )
            bot.register_next_step_handler(msg, process_country_name)
            bot.answer_callback_query(call.id)
            return

        # ========= Admin remove numbers =========
        if call.data == "admin_remove_numbers":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return

            c = db.execute("SELECT DISTINCT country FROM numbers")
            countries = c.fetchall()

            markup = types.InlineKeyboardMarkup()
            for row in countries:
                country = row[0]
                btn = types.InlineKeyboardButton(country, callback_data=f"remove_{country}")
                markup.add(btn)

            bot.send_message(
                chat_id,
                "Select a country to remove all its numbers:",
                reply_markup=markup
            )
            bot.answer_callback_query(call.id)
            return

        if call.data.startswith("remove_"):
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return

            country = call.data.split("_", 1)[1]

            markup = types.InlineKeyboardMarkup()
            confirm_btn = types.InlineKeyboardButton(
                "✅ Yes, Delete", callback_data=f"confirm_remove_{country}"
            )
            cancel_btn = types.InlineKeyboardButton(
                "❌ Cancel", callback_data="cancel_remove"
            )
            markup.row(confirm_btn, cancel_btn)

            bot.send_message(
                chat_id,
                f"Are you sure you want to delete ALL numbers for {country}?",
                reply_markup=markup
            )
            bot.answer_callback_query(call.id)
            return

        if call.data.startswith("confirm_remove_"):
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return

            country = call.data.split("_", 2)[2]

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    db.execute("DELETE FROM numbers WHERE country = ?", (country,))
                    bot.send_message(chat_id, f"✅ All numbers for {country} have been removed.")
                    break
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        logger.warning(f"Database locked, retrying {attempt+1}/{max_retries}")
                        time.sleep(1)
                    else:
                        logger.error(f"Failed to delete numbers after {max_retries} attempts: {e}")
                        bot.send_message(
                            chat_id,
                            f"❌ Error deleting numbers for {country}. Please try again."
                        )
                        break
            bot.answer_callback_query(call.id)
            return

        if call.data == "cancel_remove":
            bot.send_message(chat_id, "❌ Deletion cancelled.")
            bot.answer_callback_query(call.id)
            return

        # ========= Admin stats =========
        if call.data == "admin_stats":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return

            total_used, active_users = get_today_stats()
            country_stats = get_country_stats()

            stats_text = (
                f"📊 Today's Stats:\n\n"
                f"• Numbers Used: {total_used}\n"
                f"• Active Users: {active_users}\n\n"
                "📈 Country-wise Stats:\n"
            )

            for row in country_stats:
                country, total, used = row
                used = used if used is not None else 0
                available = total - used
                stats_text += f"• {country}: {used}/{total} (Available: {available})\n"

            low_numbers = check_low_numbers()
            if low_numbers:
                stats_text += "\n⚠️ Low Numbers Alert:\n"
                for country, available in low_numbers:
                    stats_text += f"• {country}: Only {available} numbers left!\n"

            bot.send_message(chat_id, stats_text)
            bot.answer_callback_query(call.id)
            return

        # ========= Admin users =========
        if call.data == "admin_users":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return

            markup = types.InlineKeyboardMarkup()
            btn1 = types.InlineKeyboardButton("👤 Find User", callback_data="admin_find_user")
            btn2 = types.InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban_user")
            btn3 = types.InlineKeyboardButton("✅ Unban User", callback_data="admin_unban_user")

            markup.row(btn1)
            markup.row(btn2, btn3)

            bot.send_message(
                chat_id,
                "👤 User Management\n\nSelect an option:",
                reply_markup=markup
            )
            bot.answer_callback_query(call.id)
            return

        if call.data == "admin_find_user":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(chat_id, "Send the user ID to find:")
            bot.register_next_step_handler(msg, find_user)
            bot.answer_callback_query(call.id)
            return

        if call.data == "admin_ban_user":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(chat_id, "Send the user ID to ban:")
            bot.register_next_step_handler(msg, ban_user)
            bot.answer_callback_query(call.id)
            return

        if call.data == "admin_unban_user":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(chat_id, "Send the user ID to unban:")
            bot.register_next_step_handler(msg, unban_user)
            bot.answer_callback_query(call.id)
            return

        if call.data == "admin_broadcast":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
                return
            msg = bot.send_message(chat_id, "Send the message you want to broadcast to all users:")
            bot.register_next_step_handler(msg, broadcast_message)
            bot.answer_callback_query(call.id)
            return

    except Exception as e:
        logger.error(f"Error in process_callback: {e}")

# =======================
# find_number_info
# =======================

def find_number_info(message):
    number = message.text.strip()
    cleaned_number = re.sub(r'(?!^\+)[^\d]', '', number)
    if not cleaned_number.startswith('+'):
        cleaned_number = '+' + cleaned_number

    c = db.execute(
        """
        SELECT n.number, n.country, n.use_date, n.used_by,
               u.username, u.first_name, u.last_name, u.user_id
        FROM numbers n
        LEFT JOIN users u ON n.used_by = u.user_id
        WHERE n.number = ?
        """,
        (cleaned_number,),
    )

    result = c.fetchone()
    if result:
        number, country, use_date, used_by, username, first_name, last_name, user_id = result
        if used_by:
            user_info = (
                "👤 User Information:\n\n"
                f"• User ID: {user_id}\n"
                f"• Username: @{username if username else 'N/A'}\n"
                f"• Full Name: {first_name} {last_name if last_name else ''}\n"
                f"• Number Used: {number}\n"
                f"• Country: {country}\n"
                f"• Use Date: {use_date}"
            )
        else:
            user_info = (
                "ℹ️ Number Information:\n\n"
                f"• Number: {number}\n"
                f"• Country: {country}\n"
                f"• Status: {'Available' if not used_by else 'Used'}\n"
            )
        bot.send_message(message.chat.id, user_info)
    else:
        bot.send_message(message.chat.id, f"❌ Number {number} not found in the database.")

# =======================
# Admin: add numbers
# =======================

def process_country_name(message):
    country_name = message.text
    msg = bot.send_message(
        message.chat.id,
        f"📤 Now send me a file with numbers for {country_name}"
    )
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
                db.execute(
                    "INSERT INTO numbers (country, number) VALUES (?, ?)",
                    (country_name, number),
                )
                added += 1
            except Exception:
                skipped += 1

        # Notify users
        c = db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = c.fetchall()

        for user in users:
            try:
                bot.send_message(
                    user[0],
                    f"🆕 New numbers added for {country_name}! Use /start to get one."
                )
            except Exception:
                pass

        bot.send_message(
            message.chat.id,
            f"✅ Numbers added successfully for {country_name}!\n\n"
            f"Added: {added}\nSkipped (duplicates): {skipped}\n"
            f"Total processed: {len(numbers)}"
        )

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error processing file: {str(e)}")

# =======================
# Admin: user ops
# =======================

def find_user(message):
    try:
        user_id = int(message.text)
        c = db.execute(
            "SELECT user_id, username, first_name, last_name, join_date, is_banned "
            "FROM users WHERE user_id = ?",
            (user_id,),
        )
        user = c.fetchone()
        if user:
            user_id, username, first_name, last_name, join_date, is_banned = user
            status = "Banned" if is_banned else "Active"
            user_info = (
                "👤 User Info:\n\n"
                f"ID: {user_id}\n"
                f"Username: @{username}\n"
                f"Name: {first_name} {last_name}\n"
                f"Join Date: {join_date}\n"
                f"Status: {status}"
            )
            today = datetime.now().strftime("%Y-%m-%d")
            c = db.execute(
                "SELECT numbers_today FROM user_stats WHERE user_id = ? AND date = ?",
                (user_id, today),
            )
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
            bot.send_message(user[0], f"📜\n\n{text}")
            success += 1
        except Exception:
            failed += 1
        time.sleep(0.1)

    bot.send_message(
        message.chat.id,
        f"✅ Broadcast completed!\n\nSuccess: {success}\nFailed: {failed}"
    )

# =======================
# Channel update step handlers
# =======================

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

# =======================
# Run the bot
# =======================

if __name__ == "__main__":
    print("🤖 Bot is running...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            logger.error(f"Error in polling: {e}")
            time.sleep(5)
