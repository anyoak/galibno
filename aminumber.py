import logging
import sqlite3
import asyncio
import threading
import time
import subprocess
import sys
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telethon import TelegramClient, functions, types
from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError
from tronpy import Tron
from tronpy.providers import HTTPProvider
import requests
import schedule
import json
import os
from tronpy.keys import PrivateKey

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = "7604987358:AAGtEVsvV6wrE1yRPf_4l9s-WpFE9M0EWH8"
ADMIN_IDS = [7903239321]  # Admin ID as integer
TRON_NODE = "https://api.trongrid.io"
TRON_HEADERS = {
    "TRON-PRO-API-KEY": "22239e39-909a-4633-b56c-a807aacd7792"
}
TRON_USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"  # USDT TRC20 contract
MAX_NUMBERS_PER_REQUEST = 500
DAILY_LIMIT = 2000
SUBSCRIPTION_PRICE = 3  # USD
SUBSCRIPTION_DAYS = 7

# Database setup
def init_db():
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        tron_address TEXT,
        private_key TEXT,
        subscription_end DATETIME,
        daily_checks INTEGER DEFAULT 0,
        total_checks INTEGER DEFAULT 0,
        max_checks INTEGER DEFAULT 10010,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Payments table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tron_address TEXT,
        amount REAL,
        tx_hash TEXT,
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Telegram accounts table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS telegram_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone_number TEXT,
        api_id INTEGER,
        api_hash TEXT,
        session_file TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        last_used DATETIME,
        use_count INTEGER DEFAULT 0
    )
    ''')
    
    # Checked numbers table (for caching)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS checked_numbers (
        phone_number TEXT PRIMARY KEY,
        has_account BOOLEAN,
        is_banned BOOLEAN,
        checked_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Admin withdrawal table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admin_withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        tron_address TEXT,
        amount REAL,
        tx_hash TEXT,
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# Telegram client manager
class TelegramClientManager:
    def __init__(self):
        self.clients = {}
        self.current_index = 0
        self.load_accounts()
    
    def load_accounts(self):
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM telegram_accounts WHERE is_active = TRUE")
        accounts = cursor.fetchall()
        conn.close()
        
        for account in accounts:
            acc_id, phone, api_id, api_hash, session_file, is_active, last_used, use_count = account
            try:
                client = TelegramClient(session_file, api_id, api_hash)
                client.connect()
                if not client.is_user_authorized():
                    logger.warning(f"Session {session_file} is not authorized. Please authorize it first.")
                    continue
                self.clients[acc_id] = {
                    'client': client,
                    'use_count': use_count,
                    'last_used': last_used
                }
            except Exception as e:
                logger.error(f"Error loading account {acc_id}: {e}")
    
    def get_client(self):
        if not self.clients:
            return None
        
        # Round-robin client selection
        account_ids = list(self.clients.keys())
        account_id = account_ids[self.current_index]
        self.current_index = (self.current_index + 1) % len(account_ids)
        
        # Update usage count
        client_data = self.clients[account_id]
        client_data['use_count'] += 1
        client_data['last_used'] = datetime.now()
        
        # Update database
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("UPDATE telegram_accounts SET use_count = ?, last_used = ? WHERE id = ?", 
                      (client_data['use_count'], client_data['last_used'], account_id))
        conn.commit()
        conn.close()
        
        return client_data['client']

client_manager = TelegramClientManager()

# Tron blockchain utility functions
def generate_tron_address():
    client = Tron(provider=HTTPProvider(TRON_NODE))
    private_key = client.generate_address()
    return private_key['base58check_address'], private_key['private_key']

def get_trx_price():
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tron&vs_currencies=usd")
        data = response.json()
        return data['tron']['usd']
    except Exception as e:
        logger.error(f"Error fetching TRX price: {e}")
        return None

# Live TRX → USD rate আনবে
def get_trx_price_usd():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=tron&vs_currencies=usd"
        response = requests.get(url).json()
        return float(response["tron"]["usd"])
    except:
        return 0.11  # fallback যদি API না চলে

def check_tron_payment(address, amount=SUBSCRIPTION_PRICE):
    try:
        client = Tron(provider=HTTPProvider(TRON_NODE, headers=TRON_HEADERS))
        
        # ইউজারের TRX ব্যালেন্স
        trx_balance = client.get_account_balance(address)
        
        # TRX → USD কনভার্ট
        trx_price = get_trx_price_usd()
        trx_in_usd = trx_balance * trx_price
        
        logger.info(f"[CHECK] Balance={trx_balance} TRX ≈ ${trx_in_usd:.2f}")
        
        # 0.5% margin
        min_amount = amount * 0.995
        max_amount = amount * 1.005
        
        if min_amount <= trx_in_usd <= max_amount:
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"Error checking TRON payment: {e}")
        return False

def get_total_balance(address):
    try:
        client = Tron(provider=HTTPProvider(TRON_NODE, headers=TRON_HEADERS))
        
        # Get TRX balance
        trx_balance = client.get_account_balance(address)
        
        # Get USDT balance
        contract = client.get_contract(TRON_USDT_CONTRACT)
        usdt_balance = contract.functions.balanceOf(address) / 1000000
        
        return trx_balance, usdt_balance
    except Exception as e:
        logger.error(f"Error getting total balance: {e}")
        return 0, 0

def send_trx(from_private_key, to_address, amount):
    try:
        client = Tron(provider=HTTPProvider(TRON_NODE, headers=TRON_HEADERS))
        priv_key = PrivateKey(bytes.fromhex(from_private_key))
        
        txn = (
            client.trx.transfer(priv_key.public_key.to_base58check_address(), to_address, int(amount * 1000000))
            .build()
            .sign(priv_key)
        )
        result = txn.broadcast()
        return result['txid']
    except Exception as e:
        logger.error(f"Error sending TRX: {e}")
        return None

def send_usdt(from_private_key, to_address, amount):
    try:
        client = Tron(provider=HTTPProvider(TRON_NODE, headers=TRON_HEADERS))
        priv_key = PrivateKey(bytes.fromhex(from_private_key))
        contract = client.get_contract(TRON_USDT_CONTRACT)
        
        txn = (
            contract.functions.transfer(to_address, int(amount * 1000000))
            .with_owner(priv_key.public_key.to_base58check_address())
            .fee_limit(10_000_000)
            .build()
            .sign(priv_key)
        )
        result = txn.broadcast()
        return result['txid']
    except Exception as e:
        logger.error(f"Error sending USDT: {e}")
        return None

# Utility functions
def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_user_data(user_id):
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_user_checks(user_id, checks_used=1):
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET daily_checks = daily_checks + ?, total_checks = total_checks + ? WHERE user_id = ?", 
                  (checks_used, checks_used, user_id))
    conn.commit()
    conn.close()

def reset_daily_checks():
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET daily_checks = 0")
    conn.commit()
    conn.close()
    logger.info("Daily checks reset")

def add_telegram_account(phone_number, api_id, api_hash):
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # Create sessions directory if it doesn't exist
    os.makedirs("sessions", exist_ok=True)
    session_file = f"sessions/{phone_number}"
    
    cursor.execute("INSERT INTO telegram_accounts (phone_number, api_id, api_hash, session_file) VALUES (?, ?, ?, ?)",
                  (phone_number, api_id, api_hash, session_file))
    conn.commit()
    conn.close()
    
    # Try to connect and authorize the new account
    try:
        client = TelegramClient(session_file, api_id, api_hash)
        client.connect()
        
        if not client.is_user_authorized():
            # Send authorization request
            client.send_code_request(phone_number)
            return "code_requested"
        else:
            client_manager.load_accounts()
            return "authorized"
    except Exception as e:
        logger.error(f"Error adding Telegram account: {e}")
        return f"error: {str(e)}"

def get_all_user_addresses():
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT tron_address, private_key FROM users WHERE tron_address IS NOT NULL")
    addresses = cursor.fetchall()
    conn.close()
    return addresses

# Scheduler to reset daily checks
def schedule_reset_daily_checks():
    schedule.every().day.at("00:00").do(reset_daily_checks)
    while True:
        schedule.run_pending()
        time.sleep(60)

# Start background thread
reset_thread = threading.Thread(target=schedule_reset_daily_checks, daemon=True)
reset_thread.start()

# Function to check phone numbers
async def check_phone_number(phone_number):
    # First check cache
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM checked_numbers WHERE phone_number = ?", (phone_number,))
    cached_result = cursor.fetchone()
    
    if cached_result:
        conn.close()
        return {
            'has_account': bool(cached_result[1]),
            'is_banned': bool(cached_result[2]),
            'cached': True
        }
    
    client = client_manager.get_client()
    if not client:
        return {'error': 'No available Telegram clients'}
    
    try:
        # Phone number validation
        if not phone_number.startswith('+'):
            phone_number = '+' + phone_number
        
        # Check phone number
        result = await client(functions.contacts.ImportContactsRequest(
            contacts=[types.InputPhoneContact(
                client_id=0,
                phone=phone_number,
                first_name="Check",
                last_name="User"
            )]
        ))
        
        has_account = len(result.users) > 0
        is_banned = False
        
        if has_account:
            user = result.users[0]
            if hasattr(user, 'restricted') and user.restricted:
                is_banned = True
            elif hasattr(user, 'deleted') and user.deleted:
                has_account = False
        
        # Cache the result
        cursor.execute("INSERT OR REPLACE INTO checked_numbers (phone_number, has_account, is_banned) VALUES (?, ?, ?)",
                      (phone_number, int(has_account), int(is_banned)))
        conn.commit()
        conn.close()
        
        return {
            'has_account': has_account,
            'is_banned': is_banned,
            'cached': False
        }
        
    except Exception as e:
        conn.close()
        logger.error(f"Error checking phone number {phone_number}: {e}")
        return {'error': str(e)}

# Bot command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    
    if user:
        subscription_end = datetime.strptime(user[3], '%Y-%m-%d %H:%M:%S') if user[3] else None
        if subscription_end and subscription_end > datetime.now():
            remaining_days = (subscription_end - datetime.now()).days
            await update.message.reply_text(
                f"Welcome back! Your subscription is active for {remaining_days} more days.\n\n"
                f"Daily checks: {user[4]}/{DAILY_LIMIT}\n"
                f"Total checks: {user[5]}/{user[6]}\n\n"
                f"You can send me up to {MAX_NUMBERS_PER_REQUEST} phone numbers at once, "
                f"and I'll check if they have Telegram accounts."
            )
        else:
            # Payment needed
            tron_address, private_key = generate_tron_address()
            
            conn = sqlite3.connect('bot_database.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET tron_address = ?, private_key = ? WHERE user_id = ?", 
                          (tron_address, private_key, user_id))
            conn.commit()
            conn.close()
            
            # Get TRX price
            trx_price = get_trx_price()
            trx_amount = SUBSCRIPTION_PRICE / trx_price if trx_price else "N/A"
            
            keyboard = [
                [InlineKeyboardButton("Check Payment", callback_data=f"check_payment_{user_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                f"To activate your subscription, please send {SUBSCRIPTION_PRICE} USDT (TRC20) to the following address:\n\n"
                f"`{tron_address}`\n\n"
            )
            
            if trx_price:
                message += f"Approximately {trx_amount:.2f} TRX (based on current price)\n\n"
            
            message += (
                f"We accept a 0.5% variance ({SUBSCRIPTION_PRICE*0.995:.3f} - {SUBSCRIPTION_PRICE*1.005:.3f} USDT)\n\n"
                f"Your subscription will be activated for {SUBSCRIPTION_DAYS} days after payment verification.\n"
                f"Click 'Check Payment' after completing the transaction."
            )
            
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    else:
        # New user
        tron_address, private_key = generate_tron_address()
        
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (user_id, tron_address, private_key, max_checks) VALUES (?, ?, ?, ?)", 
                      (user_id, tron_address, private_key, DAILY_LIMIT * SUBSCRIPTION_DAYS))
        conn.commit()
        conn.close()
        
        # Get TRX price
        trx_price = get_trx_price()
        trx_amount = SUBSCRIPTION_PRICE / trx_price if trx_price else "N/A"
        
        keyboard = [
            [InlineKeyboardButton("Check Payment", callback_data=f"check_payment_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            f"Welcome to Phone Number Checker Bot! 🤖\n\n"
            f"This bot can check if phone numbers have Telegram accounts.\n\n"
            f"To activate your subscription, please send {SUBSCRIPTION_PRICE} USDT (TRC20) to the following address:\n\n"
            f"`{tron_address}`\n\n"
        )
        
        if trx_price:
            message += f"Approximately {trx_amount:.2f} TRX (based on current price)\n\n"
        
        message += (
            f"We accept a 0.5% variance ({SUBSCRIPTION_PRICE*0.995:.3f} - {SUBSCRIPTION_PRICE*1.005:.3f} USDT)\n\n"
            f"Your subscription will be activated for {SUBSCRIPTION_DAYS} days after payment verification.\n"
            f"Click 'Check Payment' after completing the transaction."
        )
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    
    if not user:
        await update.message.reply_text("Sorry, you are not registered. Please use /start to begin.")
        return
    
    # Check subscription
    subscription_end = datetime.strptime(user[3], '%Y-%m-%d %H:%M:%S') if user[3] else None
    if not subscription_end or subscription_end <= datetime.now():
        await update.message.reply_text("Your subscription has expired. Please renew your payment using /start.")
        return
    
    # Check daily limit
    if user[4] >= DAILY_LIMIT:
        await update.message.reply_text(f"You have reached your daily limit of {DAILY_LIMIT} checks. Please try again tomorrow.")
        return
    
    # Check total limit
    if user[5] >= user[6]:
        await update.message.reply_text("You have reached your total check limit.")
        return
    
    message_text = update.message.text
    phone_numbers = [line.strip() for line in message_text.split('\n') if line.strip()]
    
    if not phone_numbers:
        await update.message.reply_text("Sorry, no valid phone numbers found.")
        return
    
    if len(phone_numbers) > MAX_NUMBERS_PER_REQUEST:
        await update.message.reply_text(f"You can check up to {MAX_NUMBERS_PER_REQUEST} numbers at once.")
        return
    
    # Check limits
    remaining_daily_checks = DAILY_LIMIT - user[4]
    remaining_total_checks = user[6] - user[5]
    max_possible_checks = min(remaining_daily_checks, remaining_total_checks, len(phone_numbers))
    
    if max_possible_checks <= 0:
        await update.message.reply_text("You have no checks remaining.")
        return
    
    if len(phone_numbers) > max_possible_checks:
        await update.message.reply_text(
            f"You can only check {max_possible_checks} numbers with your current limits.\n"
            f"Daily remaining: {remaining_daily_checks}\n"
            f"Total remaining: {remaining_total_checks}"
        )
        return
    
    processing_msg = await update.message.reply_text(f"Processing {len(phone_numbers)} numbers...")
    
    has_account_list = []
    no_account_list = []
    banned_list = []
    error_list = []
    
    checked_count = 0
    
    for phone in phone_numbers:
        if checked_count >= max_possible_checks:
            break
            
        result = await check_phone_number(phone)
        if 'error' in result:
            error_list.append(f"{phone}: Error - {result['error']}")
        else:
            if result['is_banned']:
                banned_list.append(phone)
            elif result['has_account']:
                has_account_list.append(phone)
            else:
                no_account_list.append(phone)
        
        checked_count += 1
        # Wait 1 second between checks
        await asyncio.sleep(1)
    
    # Update user check count
    update_user_checks(user_id, checked_count)
    
    # Create result files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Has account file
    if has_account_list:
        has_account_filename = f"has_account_{user_id}_{timestamp}.txt"
        with open(has_account_filename, 'w', encoding='utf-8') as f:
            f.write("Phone Numbers with Telegram Accounts\n")
            f.write(f"Check Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total: {len(has_account_list)}\n")
            f.write("="*50 + "\n\n")
            f.write("\n".join(has_account_list))
    
    # No account file
    if no_account_list:
        no_account_filename = f"no_account_{user_id}_{timestamp}.txt"
        with open(no_account_filename, 'w', encoding='utf-8') as f:
            f.write("Phone Numbers without Telegram Accounts\n")
            f.write(f"Check Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total: {len(no_account_list)}\n")
            f.write("="*50 + "\n\n")
            f.write("\n".join(no_account_list))
    
    # Banned account file
    if banned_list:
        banned_filename = f"banned_{user_id}_{timestamp}.txt"
        with open(banned_filename, 'w', encoding='utf-8') as f:
            f.write("Banned Phone Numbers\n")
            f.write(f"Check Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total: {len(banned_list)}\n")
            f.write("="*50 + "\n\n")
            f.write("\n".join(banned_list))
    
    # Error file
    if error_list:
        error_filename = f"error_{user_id}_{timestamp}.txt"
        with open(error_filename, 'w', encoding='utf-8') as f:
            f.write("Phone Numbers with Errors\n")
            f.write(f"Check Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total: {len(error_list)}\n")
            f.write("="*50 + "\n\n")
            f.write("\n".join(error_list))
    
    # Send files to user
    caption = (
        f"Results for {checked_count} numbers\n\n"
        f"Has account: {len(has_account_list)}\n"
        f"No account: {len(no_account_list)}\n"
        f"Banned: {len(banned_list)}\n"
        f"Errors: {len(error_list)}\n\n"
        f"Remaining daily checks: {DAILY_LIMIT - (user[4] + checked_count)}\n"
        f"Remaining total checks: {user[6] - (user[5] + checked_count)}"
    )
    
    if has_account_list:
        with open(has_account_filename, 'rb') as f:
            await update.message.reply_document(document=f, caption=caption if not no_account_list and not banned_list else None)
        os.remove(has_account_filename)
    
    if no_account_list:
        with open(no_account_filename, 'rb') as f:
            await update.message.reply_document(document=f, caption=caption if not banned_list else None)
        os.remove(no_account_filename)
    
    if banned_list:
        with open(banned_filename, 'rb') as f:
            await update.message.reply_document(document=f, caption=caption)
        os.remove(banned_filename)
    
    if error_list:
        with open(error_filename, 'rb') as f:
            await update.message.reply_document(document=f)
        os.remove(error_filename)
    
    # Delete processing message
    await processing_msg.delete()

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('check_payment_'):
        user_id = int(query.data.split('_')[2])
        
        if query.from_user.id != user_id:
            await query.message.reply_text("You are not authorized to check this payment.")
            return
        
        user = get_user_data(user_id)
        if not user or not user[1]:  # user[1] is tron_address
            await query.message.reply_text("Sorry, no payment address found. Please try /start again.")
            return
        
        checking_msg = await query.message.reply_text("Checking payment...")
        
        payment_received = check_tron_payment(user[1])
        
        if payment_received:
            # Payment successful
            subscription_end = datetime.now() + timedelta(days=SUBSCRIPTION_DAYS)
            
            conn = sqlite3.connect('bot_database.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET subscription_end = ?, daily_checks = 0, total_checks = 0 WHERE user_id = ?",
                          (subscription_end.strftime('%Y-%m-%d %H:%M:%S'), user_id))
            
            # Record payment
            cursor.execute("INSERT INTO payments (user_id, tron_address, amount, status) VALUES (?, ?, ?, ?)",
                          (user_id, user[1], SUBSCRIPTION_PRICE, 'completed'))
            conn.commit()
            conn.close()
            
            await checking_msg.edit_text(
                f"Payment verified successfully! ✅\n\n"
                f"Your subscription is active until {subscription_end.strftime('%Y-%m-%d %H:%M:%S')}.\n"
                f"You can now check phone numbers by sending them to me.\n\n"
                f"Daily limit: {DAILY_LIMIT} numbers\n"
                f"Total limit: {DAILY_LIMIT * SUBSCRIPTION_DAYS} numbers"
            )
        else:
            await checking_msg.edit_text("Payment not received yet. Please check again later.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("You are not an admin.")
        return
    
    # Admin panel dashboard
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # Total users
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # Active subscriptions
    cursor.execute("SELECT COUNT(*) FROM users WHERE subscription_end > datetime('now')")
    active_users = cursor.fetchone()[0]
    
    # Total revenue
    cursor.execute("SELECT SUM(amount) FROM payments WHERE status = 'completed'")
    total_revenue = cursor.fetchone()[0] or 0
    
    # Today's revenue
    cursor.execute("SELECT SUM(amount) FROM payments WHERE status = 'completed' AND date(created_at) = date('now')")
    today_revenue = cursor.fetchone()[0] or 0
    
    conn.close()
    
    keyboard = [
        [InlineKeyboardButton("User List", callback_data="admin_users")],
        [InlineKeyboardButton("Payment List", callback_data="admin_payments")],
        [InlineKeyboardButton("Telegram Accounts", callback_data="admin_accounts")],
        [InlineKeyboardButton("Withdraw Balance", callback_data="admin_withdraw")],
        [InlineKeyboardButton("Add Subscription", callback_data="admin_add_sub")],
        [InlineKeyboardButton("Remove Subscription", callback_data="admin_remove_sub")],
        [InlineKeyboardButton("Export Private Keys", callback_data="admin_export_keys")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Admin Panel\n\n"
        f"Total Users: {total_users}\n"
        f"Active Users: {active_users}\n"
        f"Total Revenue: ${total_revenue}\n"
        f"Today's Revenue: ${today_revenue}",
        reply_markup=reply_markup
    )

async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        await query.message.reply_text("You are not an admin.")
        return
    
    if query.data == "admin_users":
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, tron_address, subscription_end, daily_checks, total_checks, max_checks FROM users ORDER BY created_at DESC LIMIT 10")
        users = cursor.fetchall()
        conn.close()
        
        users_list = "\n".join([f"ID: {u[0]}, Sub End: {u[2]}, Daily: {u[3]}/{DAILY_LIMIT}, Total: {u[4]}/{u[5]}" for u in users])
        await query.message.reply_text(f"Last 10 users:\n\n{users_list}")
    
    elif query.data == "admin_payments":
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount, status, created_at FROM payments ORDER BY created_at DESC LIMIT 10")
        payments = cursor.fetchall()
        conn.close()
        
        payments_list = "\n".join([f"User: {p[0]}, Amount: ${p[1]}, Status: {p[2]}, Date: {p[3]}" for p in payments])
        await query.message.reply_text(f"Last 10 payments:\n\n{payments_list}")
    
    elif query.data == "admin_accounts":
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT id, phone_number, is_active, last_used, use_count FROM telegram_accounts")
        accounts = cursor.fetchall()
        conn.close()
        
        accounts_list = "\n".join([f"ID: {a[0]}, Phone: {a[1]}, Active: {a[2]}, Last: {a[3]}, Count: {a[4]}" for a in accounts])
        await query.message.reply_text(f"Telegram accounts:\n\n{accounts_list}")
    
    elif query.data == "admin_withdraw":
        # Ask for withdrawal address
        await query.message.reply_text("Please send the TRON address where you want to withdraw funds:")
        context.user_data['awaiting_withdrawal_address'] = True
    
    elif query.data == "admin_add_sub":
        # Ask for user ID and days
        await query.message.reply_text("Please send user ID and days in format: user_id days")
        context.user_data['awaiting_add_sub'] = True
    
    elif query.data == "admin_remove_sub":
        # Ask for user ID
        await query.message.reply_text("Please send the user ID to remove subscription:")
        context.user_data['awaiting_remove_sub'] = True
    
    elif query.data == "admin_export_keys":
        # Export all private keys
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, tron_address, private_key FROM users WHERE private_key IS NOT NULL")
        keys = cursor.fetchall()
        conn.close()
        
        if keys:
            keys_filename = f"private_keys_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(keys_filename, 'w', encoding='utf-8') as f:
                f.write("User Private Keys\n")
                f.write(f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("="*50 + "\n\n")
                for key in keys:
                    f.write(f"User ID: {key[0]}\n")
                    f.write(f"Address: {key[1]}\n")
                    f.write(f"Private Key: {key[2]}\n")
                    f.write("-"*30 + "\n")
            
            with open(keys_filename, 'rb') as f:
                await query.message.reply_document(document=f, caption="All user private keys")
            
            os.remove(keys_filename)
        else:
            await query.message.reply_text("No private keys found.")

async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    
    message_text = update.message.text
    
    if context.user_data.get('awaiting_withdrawal_address'):
        withdrawal_address = message_text.strip()
        context.user_data['awaiting_withdrawal_address'] = False
        
        # Validate TRON address
        if not withdrawal_address.startswith('T') or len(withdrawal_address) != 34:
            await update.message.reply_text("Invalid TRON address. Please try again.")
            return
        
        processing_msg = await update.message.reply_text("Withdrawing funds... This may take a while.")
        
        # Get all user addresses
        addresses = get_all_user_addresses()
        total_trx = 0
        total_usdt = 0
        
        for address, private_key in addresses:
            trx_balance, usdt_balance = get_total_balance(address)
            
            if usdt_balance > 0:
                tx_hash = send_usdt(private_key, withdrawal_address, usdt_balance)
                if tx_hash:
                    total_usdt += usdt_balance
            
            if trx_balance > 1:  # Leave some TRX for fees
                amount_to_send = trx_balance - 1  # Leave 1 TRX for future transactions
                tx_hash = send_trx(private_key, withdrawal_address, amount_to_send)
                if tx_hash:
                    total_trx += amount_to_send
        
        # Record withdrawal
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO admin_withdrawals (admin_id, tron_address, amount) VALUES (?, ?, ?)",
                      (user_id, withdrawal_address, total_usdt))
        conn.commit()
        conn.close()
        
        await processing_msg.edit_text(
            f"Withdrawal completed successfully! ✅\n\n"
            f"Withdrawn to: {withdrawal_address}\n"
            f"Total USDT: {total_usdt}\n"
            f"Total TRX: {total_trx}"
        )
    
    elif context.user_data.get('awaiting_add_sub'):
        try:
            user_id_str, days_str = message_text.split()
            target_user_id = int(user_id_str)
            days = int(days_str)
            
            conn = sqlite3.connect('bot_database.db', check_same_thread=False)
            cursor = conn.cursor()
            
            # Get current subscription end
            cursor.execute("SELECT subscription_end FROM users WHERE user_id = ?", (target_user_id,))
            current_end = cursor.fetchone()
            
            if current_end and current_end[0]:
                new_end = datetime.strptime(current_end[0], '%Y-%m-%d %H:%M:%S') + timedelta(days=days)
            else:
                new_end = datetime.now() + timedelta(days=days)
            
            cursor.execute("UPDATE users SET subscription_end = ? WHERE user_id = ?",
                          (new_end.strftime('%Y-%m-%d %H:%M:%S'), target_user_id))
            conn.commit()
            conn.close()
            
            await update.message.reply_text(f"Subscription added for user {target_user_id}. New end date: {new_end}")
        except ValueError:
            await update.message.reply_text("Invalid format. Please use: user_id days")
        finally:
            context.user_data['awaiting_add_sub'] = False
    
    elif context.user_data.get('awaiting_remove_sub'):
        try:
            target_user_id = int(message_text.strip())
            
            conn = sqlite3.connect('bot_database.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET subscription_end = NULL WHERE user_id = ?", (target_user_id,))
            conn.commit()
            conn.close()
            
            await update.message.reply_text(f"Subscription removed for user {target_user_id}.")
        except ValueError:
            await update.message.reply_text("Invalid user ID. Please enter a numeric user ID.")
        finally:
            context.user_data['awaiting_remove_sub'] = False

async def add_account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("You are not an admin.")
        return
    
    if not context.args or len(context.args) < 3:
        await update.message.reply_text("Usage: /addaccount phone_number api_id api_hash")
        return
    
    phone_number = context.args[0]
    api_id = context.args[1]
    api_hash = context.args[2]
    
    result = add_telegram_account(phone_number, api_id, api_hash)
    
    if result == "code_requested":
        await update.message.reply_text("Account added. Please check the phone for verification code and use /authcode to complete authorization.")
    elif result == "authorized":
        await update.message.reply_text("Account added and authorized successfully.")
    else:
        await update.message.reply_text(f"Error adding account: {result}")

async def auth_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("You are not an admin.")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /authcode phone_number code")
        return
    
    phone_number = context.args[0]
    code = context.args[1]
    
    # Find the account
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT api_id, api_hash, session_file FROM telegram_accounts WHERE phone_number = ?", (phone_number,))
    account = cursor.fetchone()
    conn.close()
    
    if not account:
        await update.message.reply_text("Account not found.")
        return
    
    api_id, api_hash, session_file = account
    
    try:
        client = TelegramClient(session_file, api_id, api_hash)
        await client.connect()
        
        # Sign in with the code
        await client.sign_in(phone=phone_number, code=code)
        
        # Reload clients
        client_manager.load_accounts()
        
        await update.message.reply_text("Account authorized successfully.")
    except Exception as e:
        await update.message.reply_text(f"Error authorizing account: {str(e)}")

# Function to start admin panel
def start_admin_panel():
    # Import and run the admin panel
    import amiadmin
    amiadmin.app.run(host='0.0.0.0', port=5000, debug=False)

def main():
    # Start admin panel in a separate thread
    admin_thread = threading.Thread(target=start_admin_panel, daemon=True)
    admin_thread.start()
    
    # Create bot application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("addaccount", add_account_command))
    application.add_handler(CommandHandler("authcode", auth_code_command))
    
    # Add message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^check_payment_"))
    application.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^admin_"))
    
    # Add admin command handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_commands))
    
    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()
