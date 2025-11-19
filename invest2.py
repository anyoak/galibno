import os
import logging
import requests
import time
import json
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import sqlite3

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = "8441847556:AAGO_XbbN_eJJrL944JCO6uzHW7TDjS5VEQ"
BSCSCAN_API_KEY = "AEUYN4PZ5XMBK5CFWHZ8MY7VZ83SGAWZSX"
ADMIN_ID = 6083895678
DEPOSIT_ADDRESS = "0x61d08Ba6CE508970C7b651953f0936fA8050Bd9B"
USDT_CONTRACT_ADDRESS = "0x55d398326f99059fF775485246999027B3197955"
MIN_WITHDRAW = 100
MIN_DEPOSIT = 50
POINT_RATE = 0.10
TIME_WINDOW_MINUTES = 2

# Database setup
def init_db():
    conn = sqlite3.connect('bot_data.db')
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

def generate_request_number():
    """Generate 4-digit random request number"""
    return str(random.randint(1000, 9999))

def get_user_data(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return {
            'user_id': user[0],
            'points': user[1],
            'deposit_balance': user[2],
            'wallet_address': user[3],
            'is_banned': user[4]
        }
    else:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
        conn.commit()
        conn.close()
        return {
            'user_id': user_id,
            'points': 0,
            'deposit_balance': 0,
            'wallet_address': None,
            'is_banned': False
        }

def has_pending_withdrawal(user_id):
    """Check if user has pending withdrawal request"""
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM withdrawal_requests WHERE user_id = ? AND status = "pending"', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def update_user_points(user_id, points):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET points = ? WHERE user_id = ?', (points, user_id))
    conn.commit()
    conn.close()

def update_deposit_balance(user_id, amount):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def set_user_points(user_id, points):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET points = ? WHERE user_id = ?', (points, user_id))
    conn.commit()
    conn.close()

def set_user_deposit(user_id, amount):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET deposit_balance = ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def ban_user(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_banned = TRUE WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_banned = FALSE WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, points, deposit_balance, is_banned FROM users')
    users = cursor.fetchall()
    conn.close()
    return users

def add_transaction(user_id, trans_type, amount, txid=None, status='pending'):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO transactions (user_id, type, amount, txid, status) VALUES (?, ?, ?, ?, ?)',
                  (user_id, trans_type, amount, txid, status))
    conn.commit()
    conn.close()

def update_transaction_status(txid, status):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE transactions SET status = ? WHERE txid = ?', (status, txid))
    conn.commit()
    conn.close()

def create_withdrawal_request(user_id, points, usd_amount, wallet_address):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    # Generate unique request number
    request_number = generate_request_number()
    
    # Ensure uniqueness
    cursor.execute('SELECT id FROM withdrawal_requests WHERE request_number = ?', (request_number,))
    while cursor.fetchone():
        request_number = generate_request_number()
        cursor.execute('SELECT id FROM withdrawal_requests WHERE request_number = ?', (request_number,))
    
    cursor.execute('''
        INSERT INTO withdrawal_requests (request_number, user_id, points, usd_amount, wallet_address, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    ''', (request_number, user_id, points, usd_amount, wallet_address))
    
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # Add to transactions with request number as txid
    add_transaction(user_id, 'withdraw', usd_amount, f"REQ-{request_number}", 'pending')
    
    return request_number

def get_pending_withdrawals():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT wr.*, u.points as current_points, u.deposit_balance 
        FROM withdrawal_requests wr
        JOIN users u ON wr.user_id = u.user_id
        WHERE wr.status = 'pending'
        ORDER BY wr.created_at DESC
    ''')
    withdrawals = cursor.fetchall()
    conn.close()
    return withdrawals

def get_withdrawal_by_request_number(request_number):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT wr.*, u.points as current_points, u.deposit_balance 
        FROM withdrawal_requests wr
        JOIN users u ON wr.user_id = u.user_id
        WHERE wr.request_number = ?
    ''', (request_number,))
    withdrawal = cursor.fetchone()
    conn.close()
    return withdrawal

def update_withdrawal_status(request_number, status):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE withdrawal_requests SET status = ? WHERE request_number = ?', (status, request_number))
    conn.commit()
    conn.close()
    
    # Update transaction status
    update_transaction_status(f"REQ-{request_number}", status)

def is_txid_processed(txid):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM processed_txids WHERE txid = ?', (txid,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_txid_processed(txid, user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO processed_txids (txid, user_id) VALUES (?, ?)', (txid, user_id))
    conn.commit()
    conn.close()

def verify_usdt_transaction(txid):
    """
    Verify USDT transaction using BscScan API - FIXED VERSION
    Returns: (success, amount, message)
    """
    try:
        # Use the transaction-specific endpoint first
        api_url = "https://api.bscscan.com/api"
        
        # First, get transaction receipt status
        receipt_params = {
            'module': 'transaction',
            'action': 'gettxreceiptstatus',
            'txhash': txid,
            'apikey': BSCSCAN_API_KEY
        }
        
        receipt_response = requests.get(api_url, params=receipt_params, timeout=30)
        receipt_data = receipt_response.json()
        
        logger.info(f"Receipt Response: {receipt_data}")
        
        if receipt_data.get('status') != '1':
            return False, 0, "Transaction failed or not found on blockchain"
        
        # Now get transaction details using proxy
        tx_params = {
            'module': 'proxy',
            'action': 'eth_getTransactionByHash',
            'txhash': txid,
            'apikey': BSCSCAN_API_KEY
        }
        
        tx_response = requests.get(api_url, params=tx_params, timeout=30)
        tx_data = tx_response.json()
        
        logger.info(f"Transaction Response: {tx_data}")
        
        if 'error' in tx_data or not tx_data.get('result'):
            return False, 0, "Transaction details not found"
        
        transaction = tx_data['result']
        
        # Check if transaction is to our deposit address
        if transaction.get('to', '').lower() != DEPOSIT_ADDRESS.lower():
            return False, 0, "Transaction not sent to correct deposit address"
        
        # For USDT, we need to check token transfers
        # Get recent token transfers to our address
        token_params = {
            'module': 'account',
            'action': 'tokentx',
            'address': DEPOSIT_ADDRESS,
            'page': 1,
            'offset': 100,
            'sort': 'desc',
            'apikey': BSCSCAN_API_KEY
        }
        
        token_response = requests.get(api_url, params=token_params, timeout=30)
        token_data = token_response.json()
        
        logger.info(f"Token Tx Status: {token_data.get('status')}, Message: {token_data.get('message')}")
        
        if token_data.get('status') == '1' and 'result' in token_data:
            # Find our transaction in token transfers
            for transfer in token_data['result']:
                if (transfer['hash'].lower() == txid.lower() and 
                    transfer['contractAddress'].lower() == USDT_CONTRACT_ADDRESS.lower() and
                    transfer['to'].lower() == DEPOSIT_ADDRESS.lower()):
                    
                    # Convert from wei to USDT
                    usdt_amount = float(transfer['value']) / 10**18
                    
                    # Check minimum deposit
                    if usdt_amount < MIN_DEPOSIT:
                        return False, 0, f"Amount ${usdt_amount:.2f} below minimum ${MIN_DEPOSIT}"
                    
                    # Check transaction time
                    tx_timestamp = int(transfer['timeStamp'])
                    current_time = int(time.time())
                    
                    if current_time - tx_timestamp > TIME_WINDOW_MINUTES * 60:
                        time_diff = (current_time - tx_timestamp) // 60
                        return False, 0, f"Transaction is {time_diff} minutes old (max {TIME_WINDOW_MINUTES} minutes)"
                    
                    return True, usdt_amount, "Transaction verified successfully"
        
        return False, 0, "USDT transfer not found in transaction"
        
    except requests.exceptions.Timeout:
        return False, 0, "BscScan API timeout - please try again later"
    except requests.exceptions.RequestException as e:
        return False, 0, f"Network error: {str(e)}"
    except Exception as e:
        logger.error(f"Error verifying transaction: {str(e)}")
        return False, 0, f"Verification error: {str(e)}"

# User commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    keyboard = [
        [InlineKeyboardButton(f"💰 {user_data['points']:.2f} PTS", callback_data="points_display")],
        [
            InlineKeyboardButton("Deposit", callback_data="deposit"),
            InlineKeyboardButton("Withdraw", callback_data="withdraw"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "Welcome to the Bot!\n\n"
        "💎 1 Point = $0.10\n"
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
            [
                InlineKeyboardButton("Deposit", callback_data="deposit"),
                InlineKeyboardButton("Withdraw", callback_data="withdraw"),
            ]
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
        # Check if user has pending withdrawal
        if has_pending_withdrawal(user_id):
            await query.edit_message_text(
                "⏳ You already have a pending withdrawal request. "
                "Please wait for it to be processed before making a new request."
            )
            return
            
        if user_data['points'] < MIN_WITHDRAW:
            await query.edit_message_text(
                f"❌ Minimum withdrawal is {MIN_WITHDRAW} points.\n"
                f"Your current points: {user_data['points']:.2f}"
            )
            return
            
        if not user_data['wallet_address']:
            await query.edit_message_text(
                "❌ Please set your SOL wallet first using /setwallet"
            )
            return
        
        # Create withdrawal request
        usd_amount = user_data['points'] * POINT_RATE
        request_number = create_withdrawal_request(user_id, user_data['points'], usd_amount, user_data['wallet_address'])
        
        # Send notification to admin
        admin_message = (
            f"🔄 NEW WITHDRAWAL REQUEST #{request_number}\n\n"
            f"👤 User Details:\n"
            f"User ID: {user_id}\n"
            f"Username: @{query.from_user.username if query.from_user.username else 'N/A'}\n"
            f"Full Name: {query.from_user.full_name}\n\n"
            f"💰 Financial Details:\n"
            f"Points: {user_data['points']:.2f} PTS\n"
            f"USD Amount: ${usd_amount:.2f}\n"
            f"Deposit Balance: ${user_data['deposit_balance']:.2f}\n\n"
            f"🔐 Wallet Address:\n"
            f"`{user_data['wallet_address']}`\n\n"
            f"Use /approve {request_number} to approve\n"
            f"Use /reject {request_number} to reject"
        )
        
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID, 
                text=admin_message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send admin notification: {e}")
            
        # Confirm to user
        withdraw_text = (
            f"✅ Withdrawal Request Submitted!\n\n"
            f"📋 Request ID: #{request_number}\n"
            f"💰 Points: {user_data['points']:.2f} PTS\n"
            f"💵 Amount: ${usd_amount:.2f}\n"
            f"🔐 Wallet: {user_data['wallet_address']}\n\n"
            "⏳ Your request has been sent to admin for processing. "
            "You will be notified once it's approved or rejected.\n\n"
            "⚠️ You cannot submit another withdrawal until this request is processed."
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
    
    # Check if TXID was already processed
    if is_txid_processed(txid):
        await update.message.reply_text("❌ This TXID has already been processed.")
        return
    
    await update.message.reply_text("🔍 Verifying your transaction with BscScan...")
    
    # Verify transaction using BscScan API
    success, amount, message = verify_usdt_transaction(txid)
    
    if success:
        # Calculate points based on deposit amount
        points_to_add = amount / POINT_RATE
        
        # Update user balance
        update_deposit_balance(user_id, amount)
        new_points = user_data['points'] + points_to_add
        update_user_points(user_id, new_points)
        add_transaction(user_id, 'deposit', amount, txid, 'approved')
        mark_txid_processed(txid, user_id)
        
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
    
    wallet_address = ' '.join(context.args)
    
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET wallet_address = ? WHERE user_id = ?', (wallet_address, user_id))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ SOL wallet set to:\n`{wallet_address}`", parse_mode='Markdown')

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT type, amount, txid, status, created_at 
        FROM transactions 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT 10
    ''', (user_id,))
    
    transactions = cursor.fetchall()
    conn.close()
    
    if not transactions:
        await update.message.reply_text("📊 No transaction history found.")
        return
    
    history_text = "📊 Your Transaction History:\n\n"
    for trans in transactions:
        trans_type, amount, txid, status, created_at = trans
        emoji = "📥" if trans_type == "deposit" else "📤" if trans_type == "withdraw" else "🔄"
        
        # Status emoji
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
    
    cancel_text = (
        "To cancel your investment and for any other inquiries, "
        "please contact @Symbioticl directly.\n\n"
        "We're here to help you!"
    )
    await update.message.reply_text(cancel_text)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    # Check if user has pending withdrawal
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

# Admin commands
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    admin_commands = """
👑 **Admin Panel Commands**

**Withdrawal Management:**
/pending - Show pending withdrawal requests
/approve <request_id> - Approve withdrawal request
/reject <request_id> - Reject withdrawal request

**User Management:**
/setpoints <user_id> <points> - Set user points
/setdeposit <user_id> <amount> - Set user deposit balance
/ban <user_id> - Ban a user
/unban <user_id> - Unban a user
/setwallet_admin <user_id> <wallet> - Change user wallet

**System Commands:**
/broadcast <message> - Broadcast to all users
/stats - Show bot statistics
/allusers - List all users

**Use /admin to see this help again**
"""
    await update.message.reply_text(admin_commands, parse_mode='Markdown')

async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    withdrawals = get_pending_withdrawals()
    
    if not withdrawals:
        await update.message.reply_text("✅ No pending withdrawal requests.")
        return
    
    for withdrawal in withdrawals:
        (request_id, request_number, user_id, points, usd_amount, 
         wallet_address, status, created_at, current_points, deposit_balance) = withdrawal
        
        withdrawal_text = (
            f"🔄 PENDING WITHDRAWAL #{request_number}\n\n"
            f"👤 User ID: {user_id}\n"
            f"📅 Requested: {created_at}\n\n"
            f"💰 Request Details:\n"
            f"Points: {points:.2f} PTS\n"
            f"USD Amount: ${usd_amount:.2f}\n\n"
            f"📊 Current Balance:\n"
            f"Current Points: {current_points:.2f} PTS\n"
            f"Deposit Balance: ${deposit_balance:.2f}\n\n"
            f"🔐 Wallet Address:\n"
            f"`{wallet_address}`\n\n"
            f"Use /approve {request_number} to approve\n"
            f"Use /reject {request_number} to reject"
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
    
    try:
        request_number = context.args[0]
        withdrawal = get_withdrawal_by_request_number(request_number)
        
        if not withdrawal:
            await update.message.reply_text("❌ Withdrawal request not found.")
            return
        
        if withdrawal[6] != 'pending':  # status field
            await update.message.reply_text(f"❌ Withdrawal request already {withdrawal[6]}.")
            return
        
        # Update withdrawal status
        update_withdrawal_status(request_number, 'approved')
        
        # Deduct points from user
        user_data = get_user_data(withdrawal[2])  # user_id
        new_points = user_data['points'] - withdrawal[3]  # Subtract withdrawal points
        update_user_points(withdrawal[2], new_points)
        
        # Notify user
        try:
            user_message = (
                f"✅ Withdrawal Approved!\n\n"
                f"Request ID: #{request_number}\n"
                f"Amount: ${withdrawal[4]:.2f}\n"
                f"Points Deducted: {withdrawal[3]:.2f} PTS\n"
                f"New Balance: {new_points:.2f} PTS\n\n"
                f"Funds will be sent to your wallet shortly:\n"
                f"`{withdrawal[5]}`"
            )
            await context.bot.send_message(
                chat_id=withdrawal[2],
                text=user_message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await update.message.reply_text(
            f"✅ Withdrawal #{request_number} approved!\n"
            f"User {withdrawal[2]} points updated: {new_points:.2f} PTS"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Invalid request number.")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /reject <request_number>")
        return
    
    try:
        request_number = context.args[0]
        withdrawal = get_withdrawal_by_request_number(request_number)
        
        if not withdrawal:
            await update.message.reply_text("❌ Withdrawal request not found.")
            return
        
        if withdrawal[6] != 'pending':
            await update.message.reply_text(f"❌ Withdrawal request already {withdrawal[6]}.")
            return
        
        # Update withdrawal status
        update_withdrawal_status(request_number, 'rejected')
        
        # Notify user
        try:
            user_message = (
                f"❌ Withdrawal Rejected\n\n"
                f"Request ID: #{request_number}\n"
                f"Amount: ${withdrawal[4]:.2f}\n"
                f"Points: {withdrawal[3]:.2f} PTS\n\n"
                f"Your withdrawal request has been rejected. "
                f"Please contact admin for more information."
            )
            await context.bot.send_message(
                chat_id=withdrawal[2],
                text=user_message
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await update.message.reply_text(f"✅ Withdrawal #{request_number} rejected.")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid request number.")

# [Keep all other admin commands from previous code - setpoints, setdeposit, ban, unban, etc.]

def main():
    # Initialize database
    init_db()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add user command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setwallet", set_wallet))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("txid", txid_handler))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Add admin command handlers
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("pending", pending))
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(CommandHandler("reject", reject))
    
    # Start bot
    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
