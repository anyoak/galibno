import os
import logging
import requests
import time
import json
import random
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# -----------------------
# CONFIG (change or use env vars)
# -----------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8441847556:AAGO_XbbN_eJJrL944JCO6uzHW7TDjS5VEQ")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "AEUYN4PZ5XMBK5CFWHZ8MY7VZ83SGAWZSX")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6083895678"))
DEPOSIT_ADDRESS = os.getenv("DEPOSIT_ADDRESS", "0x61d08Ba6CE508970C7b651953f0936fA8050Bd9B").lower()
USDT_CONTRACT_ADDRESS = os.getenv("USDT_CONTRACT_ADDRESS", "0x55d398326f99059fF775485246999027B3197955").lower()
MIN_WITHDRAW = float(os.getenv("MIN_WITHDRAW", "100"))
MIN_DEPOSIT = float(os.getenv("MIN_DEPOSIT", "50"))
POINT_RATE = float(os.getenv("POINT_RATE", "0.10"))  # 1 point = $0.10
TIME_WINDOW_MINUTES = int(os.getenv("TIME_WINDOW_MINUTES", "60"))  # max age for tx

DB_FILE = os.getenv("DB_FILE", "bot_data.db")

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------
# Database helpers
# -----------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            points REAL DEFAULT 0,
            deposit_balance REAL DEFAULT 0,
            wallet_address TEXT,
            is_banned BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL,
            txid TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_txids (
            txid TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawal_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_number TEXT UNIQUE,
            user_id INTEGER,
            points REAL,
            usd_amount REAL,
            wallet_address TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    conn.commit()
    conn.close()

def query_db(query, params=(), fetchone=False, commit=False):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = None
    if fetchone:
        result = cursor.fetchone()
    else:
        result = cursor.fetchall()
    if commit:
        conn.commit()
    conn.close()
    return result

# Basic user helpers
def get_user_data(user_id):
    row = query_db("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if row:
        return {
            'user_id': row[0],
            'points': row[1] or 0.0,
            'deposit_balance': row[2] or 0.0,
            'wallet_address': row[3],
            'is_banned': bool(row[4])
        }
    # create user
    query_db("INSERT INTO users (user_id) VALUES (?)", (user_id,), commit=True)
    return {
        'user_id': user_id,
        'points': 0.0,
        'deposit_balance': 0.0,
        'wallet_address': None,
        'is_banned': False
    }

def update_user_points(user_id, points):
    query_db("UPDATE users SET points = ? WHERE user_id = ?", (points, user_id), commit=True)

def update_deposit_balance(user_id, amount):
    query_db("UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?", (amount, user_id), commit=True)

def set_user_wallet(user_id, wallet):
    query_db("UPDATE users SET wallet_address = ? WHERE user_id = ?", (wallet, user_id), commit=True)

def set_user_points(user_id, points):
    query_db("UPDATE users SET points = ? WHERE user_id = ?", (points, user_id), commit=True)

def set_user_deposit(user_id, amount):
    query_db("UPDATE users SET deposit_balance = ? WHERE user_id = ?", (amount, user_id), commit=True)

def ban_user(user_id):
    query_db("UPDATE users SET is_banned = TRUE WHERE user_id = ?", (user_id,), commit=True)

def unban_user(user_id):
    query_db("UPDATE users SET is_banned = FALSE WHERE user_id = ?", (user_id,), commit=True)

def get_all_users():
    return query_db("SELECT user_id, points, deposit_balance, is_banned FROM users")

def add_transaction(user_id, trans_type, amount, txid=None, status='pending'):
    query_db("INSERT INTO transactions (user_id, type, amount, txid, status) VALUES (?, ?, ?, ?, ?)",
             (user_id, trans_type, amount, txid, status), commit=True)

def update_transaction_status(txid, status):
    query_db("UPDATE transactions SET status = ? WHERE txid = ?", (status, txid), commit=True)

def create_withdrawal_request(user_id, points, usd_amount, wallet_address):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # unique 4-digit
    request_number = str(random.randint(1000, 9999))
    while True:
        cursor.execute('SELECT id FROM withdrawal_requests WHERE request_number = ?', (request_number,))
        if cursor.fetchone():
            request_number = str(random.randint(1000, 9999))
        else:
            break
    cursor.execute('''
        INSERT INTO withdrawal_requests (request_number, user_id, points, usd_amount, wallet_address, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    ''', (request_number, user_id, points, usd_amount, wallet_address))
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    add_transaction(user_id, 'withdraw', usd_amount, f"REQ-{request_number}", 'pending')
    return request_number

def get_pending_withdrawals():
    return query_db('''
        SELECT wr.*, u.points as current_points, u.deposit_balance
        FROM withdrawal_requests wr
        JOIN users u ON wr.user_id = u.user_id
        WHERE wr.status = 'pending'
        ORDER BY wr.created_at DESC
    ''')

def get_withdrawal_by_request_number(request_number):
    return query_db('''
        SELECT wr.*, u.points as current_points, u.deposit_balance
        FROM withdrawal_requests wr
        JOIN users u ON wr.user_id = u.user_id
        WHERE wr.request_number = ?
    ''', (request_number,), fetchone=True)

def update_withdrawal_status(request_number, status):
    query_db("UPDATE withdrawal_requests SET status = ? WHERE request_number = ?", (status, request_number), commit=True)
    update_transaction_status(f"REQ-{request_number}", status)

def is_txid_processed(txid):
    row = query_db("SELECT * FROM processed_txids WHERE txid = ?", (txid,), fetchone=True)
    return row is not None

def mark_txid_processed(txid, user_id, amount):
    query_db("INSERT OR IGNORE INTO processed_txids (txid, user_id, amount) VALUES (?, ?, ?)", (txid, user_id, amount), commit=True)

# -----------------------
# USDT-BSC verification (robust)
# -----------------------
def verify_usdt_transaction(txid: str):
    """
    Verify USDT (BEP20) deposit by checking `tokentx` by txhash.
    - Confirms contract address is USDT contract
    - Confirms 'to' equals DEPOSIT_ADDRESS
    - Uses 6 decimals for USDT on BSC
    - Ensures TX is recent (TIME_WINDOW_MINUTES)
    Returns: (success: bool, amount: float, message: str, from_address: str)
    """
    try:
        api_url = "https://api.bscscan.com/api"
        params = {
            'module': 'account',
            'action': 'tokentx',
            'txhash': txid,
            'apikey': BSCSCAN_API_KEY
        }
        resp = requests.get(api_url, params=params, timeout=20)
        data = resp.json()
    except requests.exceptions.Timeout:
        return False, 0.0, "BscScan API timeout - please try again later", None
    except requests.exceptions.RequestException as e:
        return False, 0.0, f"Network error: {str(e)}", None

    if not data or data.get('status') != '1' or not data.get('result'):
        return False, 0.0, "Transaction not found or not confirmed on BscScan", None

    transfers = data.get('result', [])
    # Find a transfer entry that matches our USDT contract and deposit address
    chosen = None
    for t in transfers:
        # Normalize addresses
        contract = (t.get('contractAddress') or "").lower()
        to_addr = (t.get('to') or "").lower()
        if contract == USDT_CONTRACT_ADDRESS and to_addr == DEPOSIT_ADDRESS:
            chosen = t
            break

    if not chosen:
        # Not found matching USDT->DEPOSIT_ADDRESS in tokentx results
        return False, 0.0, "Token transfer not to deposit address or not USDT (BEP20)", None

    # Parse amount — USDT on BSC uses 6 decimals
    try:
        value_int = int(chosen.get('value', '0'))
        usdt_amount = float(value_int) / (10 ** 6)
    except Exception:
        return False, 0.0, "Invalid transfer value", None

    # Minimum deposit check
    if usdt_amount < MIN_DEPOSIT:
        return False, usdt_amount, f"Amount ${usdt_amount:.2f} below minimum ${MIN_DEPOSIT}", chosen.get('from')

    # Timestamp / age check
    try:
        tx_timestamp = int(chosen.get('timeStamp', 0))
        if TIME_WINDOW_MINUTES and TIME_WINDOW_MINUTES > 0:
            current_time = int(time.time())
            if current_time - tx_timestamp > TIME_WINDOW_MINUTES * 60:
                minutes_old = (current_time - tx_timestamp) // 60
                return False, usdt_amount, f"Transaction is {minutes_old} minutes old (max {TIME_WINDOW_MINUTES} minutes)", chosen.get('from')
    except Exception:
        logger.warning("Could not parse transaction timestamp; skipping time-window check.")

    # Check processed txids to avoid double-credit
    if is_txid_processed(txid):
        return False, usdt_amount, "This transaction has already been processed", chosen.get('from')

    # Optional: double-check receipt success with eth_getTransactionReceipt (proxy)
    try:
        r2 = requests.get("https://api.bscscan.com/api", params={
            'module': 'proxy',
            'action': 'eth_getTransactionReceipt',
            'txhash': txid,
            'apikey': BSCSCAN_API_KEY
        }, timeout=10).json()
        if 'result' in r2 and r2['result'] is not None:
            # status should be "0x1"
            status = r2['result'].get('status')
            if status and status != "0x1":
                return False, usdt_amount, "Transaction failed on-chain (status != success)", chosen.get('from')
    except Exception:
        # don't block if this check fails; it's optional
        logger.debug("Optional receipt check failed or timed out.")

    return True, usdt_amount, "Transaction verified successfully", chosen.get('from')

# -----------------------
# Telegram command handlers
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    keyboard = [
        [InlineKeyboardButton(f"💰 {user_data['points']:.2f} PTS", callback_data="points_display")],
        [InlineKeyboardButton("Deposit", callback_data="deposit"),
         InlineKeyboardButton("Withdraw", callback_data="withdraw")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        "Welcome to the Bot!\n\n"
        f"💎 1 Point = ${POINT_RATE:.2f}\n"
        f"💸 Min Withdraw: {MIN_WITHDRAW} points\n"
        f"💰 Min Deposit: ${MIN_DEPOSIT} USDT\n\n"
        "Use /setwallet to set your SOL wallet for withdrawals"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    if user_data['is_banned']:
        await query.edit_message_text("❌ You are banned from using this bot.")
        return

    if query.data == "points_display":
        keyboard = [
            [InlineKeyboardButton(f"💰 {user_data['points']:.2f} PTS", callback_data="points_display")],
            [InlineKeyboardButton("Deposit", callback_data="deposit"),
             InlineKeyboardButton("Withdraw", callback_data="withdraw")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_reply_markup(reply_markup)

    elif query.data == "deposit":
        deposit_text = (
            f"📥 Deposit Instructions:\n\n"
            f"Send USDT (BEP-20) to this BSC address:\n`{DEPOSIT_ADDRESS}`\n\n"
            f"Minimum deposit: ${MIN_DEPOSIT} USDT\n"
            f"⏰ Transaction must be less than {TIME_WINDOW_MINUTES} minutes old\n\n"
            "After sending, please provide your TXID to verify the transaction.\n"
            "Use: /txid YOUR_TXID_HERE"
        )
        await query.edit_message_text(deposit_text, parse_mode='Markdown')

    elif query.data == "withdraw":
        if has_pending_withdrawal(user_id):
            await query.edit_message_text("⏳ You already have a pending withdrawal request. Please wait.")
            return
        if user_data['points'] < MIN_WITHDRAW:
            await query.edit_message_text(f"❌ Minimum withdrawal is {MIN_WITHDRAW} points.\nYour current points: {user_data['points']:.2f}")
            return
        if not user_data['wallet_address']:
            await query.edit_message_text("❌ Please set your SOL wallet first using /setwallet")
            return

        usd_amount = user_data['points'] * POINT_RATE
        request_number = create_withdrawal_request(user_id, user_data['points'], usd_amount, user_data['wallet_address'])

        admin_message = (
            f"🔄 NEW WITHDRAWAL REQUEST #{request_number}\n\n"
            f"👤 User ID: {user_id}\n"
            f"Username: @{query.from_user.username if query.from_user.username else 'N/A'}\n"
            f"Full Name: {query.from_user.full_name}\n\n"
            f"💰 Points: {user_data['points']:.2f} PTS\n"
            f"💵 USD Amount: ${usd_amount:.2f}\n"
            f"Deposit Balance: ${user_data['deposit_balance']:.2f}\n\n"
            f"🔐 Wallet Address:\n`{user_data['wallet_address']}`\n\n"
            f"Use /approve {request_number} to approve\nUse /reject {request_number} to reject"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to send admin notification: {e}")

        withdraw_text = (
            f"✅ Withdrawal Request Submitted!\n\n"
            f"📋 Request ID: #{request_number}\n"
            f"💰 Points: {user_data['points']:.2f} PTS\n"
            f"💵 Amount: ${usd_amount:.2f}\n"
            f"🔐 Wallet: {user_data['wallet_address']}\n\n"
            "⏳ Your request has been sent to admin for processing."
        )
        await query.edit_message_text(withdraw_text)

async def txid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    if not context.args:
        await update.message.reply_text("Please provide your TXID:\n/txid YOUR_TXID_HERE")
        return

    txid = ' '.join(context.args).strip()
    if is_txid_processed(txid):
        await update.message.reply_text("❌ This TXID has already been processed.")
        return

    await update.message.reply_text("🔍 Verifying your transaction with BscScan...")
    success, amount, message, from_address = verify_usdt_transaction(txid)
    if success:
        # Points calculation
        points_to_add = amount / POINT_RATE
        # Update DB
        update_deposit_balance(user_id, amount)
        current_points = get_user_data(user_id)['points']
        new_points = current_points + points_to_add
        update_user_points(user_id, new_points)
        add_transaction(user_id, 'deposit', amount, txid, 'approved')
        mark_txid_processed(txid, user_id, amount)
        await update.message.reply_text(
            f"✅ Deposit verified!\n"
            f"Amount: ${amount:.2f} USDT\n"
            f"Points added: {points_to_add:.2f} PTS\n"
            f"New balance: {new_points:.2f} PTS"
        )
    else:
        await update.message.reply_text(f"❌ Deposit verification failed: {message}")

async def set_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    if not context.args:
        await update.message.reply_text("Please provide your SOL wallet address:\n/setwallet YOUR_SOL_WALLET_ADDRESS")
        return
    wallet_address = ' '.join(context.args).strip()
    set_user_wallet(user_id, wallet_address)
    await update.message.reply_text(f"✅ SOL wallet set to:\n`{wallet_address}`", parse_mode='Markdown')

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    rows = query_db('''
        SELECT type, amount, txid, status, created_at
        FROM transactions
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 10
    ''', (user_id,))
    if not rows:
        await update.message.reply_text("📊 No transaction history found.")
        return
    history_text = "📊 Your Transaction History:\n\n"
    for trans in rows:
        trans_type, amount, txid, status, created_at = trans
        emoji = "📥" if trans_type == "deposit" else "📤" if trans_type == "withdraw" else "🔄"
        status_emoji = "✅" if status == "approved" else "❌" if status == "rejected" else "⏳"
        history_text += f"{emoji} {trans_type.upper()}: ${amount:.2f}\n"
        history_text += f"Status: {status_emoji} {status.upper()}\n"
        history_text += f"Date: {created_at}\n"
        if txid:
            if txid.startswith("REQ-"):
                history_text += f"Request ID: #{txid.replace('REQ-', '')}\n"
            else:
                history_text += f"TXID: {txid[:10]}...\n"
        history_text += "─" * 20 + "\n"
    await update.message.reply_text(history_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    cancel_text = "To cancel your investment and for any other inquiries, please contact @Symbioticl directly."
    await update.message.reply_text(cancel_text)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    pending_withdrawal = has_pending_withdrawal(user_id)
    withdrawal_status = "⏳ Pending withdrawal" if pending_withdrawal else "✅ Can withdraw"
    balance_text = (
        f"💰 Your Balance:\n\n"
        f"Points: {user_data['points']:.2f} PTS\n"
        f"Equivalent: ${user_data['points'] * POINT_RATE:.2f}\n"
        f"Deposit Balance: ${user_data['deposit_balance']:.2f} USDT\n\n"
        f"Withdraw Status: {withdrawal_status}\n"
        f"Wallet: {user_data['wallet_address'] or 'Not set'}"
    )
    await update.message.reply_text(balance_text)

# -----------------------
# Admin handlers
# -----------------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    admin_commands = """
👑 Admin Panel Commands:
/pending - Show pending withdrawal requests
/approve <request_id> - Approve withdrawal request
/reject <request_id> - Reject withdrawal request
/setpoints <user_id> <points> - Set user points
/setdeposit <user_id> <amount> - Set user deposit balance
/ban <user_id> - Ban a user
/unban <user_id> - Unban a user
/setwallet_admin <user_id> <wallet> - Change user wallet
/broadcast <message> - Broadcast to all users
/stats - Show bot statistics
/allusers - List all users
"""
    await update.message.reply_text(admin_commands)

def has_pending_withdrawal(user_id):
    row = query_db("SELECT id FROM withdrawal_requests WHERE user_id = ? AND status = 'pending'", (user_id,), fetchone=True)
    return row is not None

async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    rows = get_pending_withdrawals()
    if not rows:
        await update.message.reply_text("✅ No pending withdrawal requests.")
        return
    for withdrawal in rows:
        (request_id, request_number, uid, points, usd_amount, wallet_address, status, created_at, current_points, deposit_balance) = withdrawal
        withdrawal_text = (
            f"🔄 PENDING WITHDRAWAL #{request_number}\n\n"
            f"👤 User ID: {uid}\n"
            f"📅 Requested: {created_at}\n\n"
            f"💰 Points: {points:.2f} PTS\n"
            f"💵 USD Amount: ${usd_amount:.2f}\n\n"
            f"📊 Current Points: {current_points:.2f} PTS\n"
            f"Deposit Balance: ${deposit_balance:.2f}\n\n"
            f"🔐 Wallet Address:\n`{wallet_address}`\n\n"
            f"Use /approve {request_number} to approve\nUse /reject {request_number} to reject"
        )
        await update.message.reply_text(withdrawal_text, parse_mode='Markdown')

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /approve <request_number>")
        return
    request_number = context.args[0]
    withdrawal = get_withdrawal_by_request_number(request_number)
    if not withdrawal:
        await update.message.reply_text("❌ Withdrawal request not found.")
        return
    if withdrawal[6] != 'pending':
        await update.message.reply_text(f"❌ Withdrawal request already {withdrawal[6]}.")
        return
    # Approve
    update_withdrawal_status(request_number, 'approved')
    target_user_id = withdrawal[2]
    new_points = float(withdrawal[8]) - float(withdrawal[3]) if withdrawal[8] is not None else 0.0
    # In most cases you'd want to set to current_points - points; safer:
    user_data = get_user_data(target_user_id)
    updated_points = max(0.0, user_data['points'] - withdrawal[3])
    update_user_points(target_user_id, updated_points)
    try:
        user_message = (
            f"✅ Withdrawal Approved!\n\n"
            f"Request ID: #{request_number}\n"
            f"Amount: ${withdrawal[4]:.2f}\n"
            f"Points Deducted: {withdrawal[3]:.2f} PTS\n"
            f"New Balance: {updated_points:.2f} PTS\n\n"
            f"Funds will be sent to your wallet shortly:\n`{withdrawal[5]}`"
        )
        await context.bot.send_message(chat_id=target_user_id, text=user_message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")
    await update.message.reply_text(f"✅ Withdrawal #{request_number} approved!")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /reject <request_number>")
        return
    request_number = context.args[0]
    withdrawal = get_withdrawal_by_request_number(request_number)
    if not withdrawal:
        await update.message.reply_text("❌ Withdrawal request not found.")
        return
    if withdrawal[6] != 'pending':
        await update.message.reply_text(f"❌ Withdrawal request already {withdrawal[6]}.")
        return
    update_withdrawal_status(request_number, 'rejected')
    try:
        user_message = (
            f"❌ Withdrawal Rejected\n\n"
            f"Request ID: #{request_number}\n"
            f"Amount: ${withdrawal[4]:.2f}\n"
            f"Points: {withdrawal[3]:.2f} PTS\n\n"
            f"Your withdrawal request has been rejected. Please contact admin for more information."
        )
        await context.bot.send_message(chat_id=withdrawal[2], text=user_message)
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")
    await update.message.reply_text(f"✅ Withdrawal #{request_number} rejected.")

# Admin utility commands
async def setpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setpoints <user_id> <points>")
        return
    target = int(context.args[0])
    points = float(context.args[1])
    set_user_points(target, points)
    await update.message.reply_text(f"✅ Set points for {target} -> {points:.2f}")

async def setdeposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setdeposit <user_id> <amount>")
        return
    target = int(context.args[0])
    amount = float(context.args[1])
    set_user_deposit(target, amount)
    await update.message.reply_text(f"✅ Set deposit for {target} -> ${amount:.2f}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    target = int(context.args[0])
    ban_user(target)
    await update.message.reply_text(f"✅ Banned user {target}")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    target = int(context.args[0])
    unban_user(target)
    await update.message.reply_text(f"✅ Unbanned user {target}")

async def setwallet_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setwallet_admin <user_id> <wallet>")
        return
    target = int(context.args[0])
    wallet = ' '.join(context.args[1:])
    set_user_wallet(target, wallet)
    await update.message.reply_text(f"✅ Set wallet for {target}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    message = ' '.join(context.args)
    users = query_db("SELECT user_id FROM users")
    count = 0
    for row in users:
        try:
            await context.bot.send_message(chat_id=row[0], text=message)
            count += 1
        except Exception:
            continue
    await update.message.reply_text(f"✅ Broadcast sent to {count} users")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    total_users = query_db("SELECT COUNT(*) FROM users", fetchone=True)[0]
    total_processed = query_db("SELECT COUNT(*) FROM processed_txids", fetchone=True)[0]
    total_deposits = query_db("SELECT IFNULL(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='approved'", fetchone=True)[0] or 0.0
    await update.message.reply_text(f"📊 Stats:\nUsers: {total_users}\nProcessed TXs: {total_processed}\nTotal Deposited: ${total_deposits:.2f}")

async def allusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    users = get_all_users()
    out = "👥 Users:\n"
    for u in users:
        out += f"ID: {u[0]} | Points: {u[1]:.2f} | Deposit: ${u[2]:.2f} | Banned: {u[3]}\n"
    await update.message.reply_text(out)

# -----------------------
# Main
# -----------------------
def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # User commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setwallet", set_wallet))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("txid", txid_handler))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Admin commands
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("pending", pending))
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(CommandHandler("reject", reject))
    application.add_handler(CommandHandler("setpoints", setpoints))
    application.add_handler(CommandHandler("setdeposit", setdeposit))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("setwallet_admin", setwallet_admin))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("allusers", allusers))

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
