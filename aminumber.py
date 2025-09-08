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

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = "7604987358:AAGtEVsvV6wrE1yRPf_4l9s-WpFE9M0EWH8"
ADMIN_IDS = [7903239321]  # Admin ID as integer
TRON_NODE = "22239e39-909a-4633-b56c-a807aacd7792"
TRON_USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"  # USDT TRC20 contract
MAX_NUMBERS_PER_REQUEST = 500

# Database setup
def init_db():
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        tron_address TEXT,
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

def check_tron_payment(address, amount=5):
    try:
        client = Tron(provider=HTTPProvider(TRON_NODE))
        balance = client.get_account_balance(address)
        usdt_balance = 0
        
        # Check USDT balance
        contract = client.get_contract(TRON_USDT_CONTRACT)
        usdt_balance = contract.functions.balanceOf(address) / 1000000
        
        # Allow 0.5% variance
        min_amount = amount * 0.995
        max_amount = amount * 1.005
        
        return min_amount <= usdt_balance <= max_amount
    except Exception as e:
        logger.error(f"Error checking TRON payment: {e}")
        return False

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
        subscription_end = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S') if user[2] else None
        if subscription_end and subscription_end > datetime.now():
            remaining_days = (subscription_end - datetime.now()).days
            await update.message.reply_text(
                f"Your subscription is active. {remaining_days} days remaining.\n\n"
                f"You can check {1430 - user[3]}/1430 numbers today.\n"
                f"Total checks done: {user[4]}/{user[5]}"
            )
        else:
            # Payment needed
            tron_address, private_key = generate_tron_address()
            
            conn = sqlite3.connect('bot_database.db', check_same_thread=False)
            cursor = conn.cursor()
            if user:
                cursor.execute("UPDATE users SET tron_address = ? WHERE user_id = ?", (tron_address, user_id))
            else:
                cursor.execute("INSERT INTO users (user_id, tron_address) VALUES (?, ?)", (user_id, tron_address))
            conn.commit()
            conn.close()
            
            # Get TRX price
            trx_price = get_trx_price()
            trx_amount = 5 / trx_price if trx_price else "N/A"
            
            keyboard = [
                [InlineKeyboardButton("Check Payment", callback_data=f"check_payment_{user_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                f"To use the service, please pay 5 USD (USDT-TRC20) to the following address:\n\n"
                f"`{tron_address}`\n\n"
            )
            
            if trx_price:
                message += f"Approximately {trx_amount:.2f} TRX (based on current price)\n\n"
            
            message += (
                f"We accept a 0.5% variance (4.975 - 5.025 USDT)\n\n"
                f"Click 'Check Payment' after completing the payment.\n"
                f"You will get access for 7 days after payment verification."
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
        cursor.execute("INSERT INTO users (user_id, tron_address) VALUES (?, ?)", (user_id, tron_address))
        conn.commit()
        conn.close()
        
        # Get TRX price
        trx_price = get_trx_price()
        trx_amount = 5 / trx_price if trx_price else "N/A"
        
        keyboard = [
            [InlineKeyboardButton("Check Payment", callback_data=f"check_payment_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            f"To use the service, please pay 5 USD (USDT-TRC20) to the following address:\n\n"
            f"`{tron_address}`\n\n"
        )
        
        if trx_price:
            message += f"Approximately {trx_amount:.2f} TRX (based on current price)\n\n"
        
        message += (
            f"We accept a 0.5% variance (4.975 - 5.025 USDT)\n\n"
            f"Click 'Check Payment' after completing the payment.\n"
            f"You will get access for 7 days after payment verification."
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
    subscription_end = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S') if user[2] else None
    if not subscription_end or subscription_end <= datetime.now():
        await update.message.reply_text("Your subscription has expired. Please renew your payment.")
        return
    
    # Check daily limit
    if user[3] >= 1430:
        await update.message.reply_text("You have reached your daily limit. Please try again tomorrow.")
        return
    
    # Check total limit
    if user[4] >= user[5]:
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
    remaining_daily_checks = 1430 - user[3]
    remaining_total_checks = user[5] - user[4]
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
    
    results = []
    checked_count = 0
    
    for phone in phone_numbers:
        if checked_count >= max_possible_checks:
            break
            
        result = await check_phone_number(phone)
        if 'error' in result:
            results.append(f"{phone}: Error - {result['error']}")
        else:
            status = "Has account" if result['has_account'] else "No account"
            if result['is_banned']:
                status += " (Banned)"
            if result['cached']:
                status += " [Cached]"
            results.append(f"{phone}: {status}")
        
        checked_count += 1
        # Wait 1 second between checks
        await asyncio.sleep(1)
    
    # Update user check count
    update_user_checks(user_id, checked_count)
    
    # Create result file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"results_{user_id}_{timestamp}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("Phone Number Check Results\n")
        f.write(f"Check Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total Numbers Checked: {checked_count}\n")
        f.write("="*50 + "\n\n")
        f.write("\n".join(results))
    
    # Send file to user
    with open(filename, 'rb') as f:
        await update.message.reply_document(
            document=f,
            caption=f"Results for {checked_count} numbers\n\n"
                   f"Remaining daily checks: {1430 - (user[3] + checked_count)}\n"
                   f"Remaining total checks: {user[5] - (user[4] + checked_count)}"
        )
    
    # Delete processing message
    await processing_msg.delete()
    
    # Delete temporary file
    os.remove(filename)

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
            subscription_end = datetime.now() + timedelta(days=7)
            
            conn = sqlite3.connect('bot_database.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET subscription_end = ?, daily_checks = 0, total_checks = 0 WHERE user_id = ?",
                          (subscription_end.strftime('%Y-%m-%d %H:%M:%S'), user_id))
            
            # Record payment
            cursor.execute("INSERT INTO payments (user_id, tron_address, amount, status) VALUES (?, ?, ?, ?)",
                          (user_id, user[1], 5.0, 'completed'))
            conn.commit()
            conn.close()
            
            await checking_msg.edit_text(
                f"Payment verified successfully!\n\n"
                f"Your subscription is active until {subscription_end.strftime('%Y-%m-%d %H:%M:%S')}.\n"
                f"You can now check phone numbers.\n\n"
                f"You can check up to 1430 numbers per day with a total of 10010 checks."
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
        [InlineKeyboardButton("Withdraw Balance", callback_data="admin_withdraw")]
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
        cursor.execute("SELECT user_id, tron_address, subscription_end, total_checks FROM users ORDER BY created_at DESC LIMIT 10")
        users = cursor.fetchall()
        conn.close()
        
        users_list = "\n".join([f"ID: {u[0]}, Address: {u[1]}, End: {u[2]}, Checks: {u[3]}" for u in users])
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
        # Add withdrawal logic here
        await query.message.reply_text("This feature will be added soon.")

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
    
    # Add message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^check_payment_"))
    application.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^admin_"))
    
    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()
