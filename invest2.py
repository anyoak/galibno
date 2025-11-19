import os
import logging
import requests
import time
import json
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

def add_transaction(user_id, trans_type, amount, txid=None):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO transactions (user_id, type, amount, txid) VALUES (?, ?, ?, ?)',
                  (user_id, trans_type, amount, txid))
    conn.commit()
    conn.close()

def create_withdrawal_request(user_id, points, usd_amount, wallet_address):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO withdrawal_requests (user_id, points, usd_amount, wallet_address, status)
        VALUES (?, ?, ?, ?, 'pending')
    ''', (user_id, points, usd_amount, wallet_address))
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return request_id

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

def get_withdrawal_by_id(request_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT wr.*, u.points as current_points, u.deposit_balance 
        FROM withdrawal_requests wr
        JOIN users u ON wr.user_id = u.user_id
        WHERE wr.id = ?
    ''', (request_id,))
    withdrawal = cursor.fetchone()
    conn.close()
    return withdrawal

def update_withdrawal_status(request_id, status):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE withdrawal_requests SET status = ? WHERE id = ?', (status, request_id))
    conn.commit()
    conn.close()

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
    Verify USDT transaction using BscScan API
    Returns: (success, amount, message)
    """
    try:
        # First, check token transfers to find USDT transaction
        api_url = "https://api.bscscan.com/api"
        
        # Check token transfers for our deposit address
        token_params = {
            'module': 'account',
            'action': 'tokentx',
            'address': DEPOSIT_ADDRESS,
            'startblock': 0,
            'endblock': 99999999,
            'sort': 'desc',
            'apikey': BSCSCAN_API_KEY
        }
        
        response = requests.get(api_url, params=token_params, timeout=30)
        data = response.json()
        
        logger.info(f"BscScan API Response: {data}")
        
        # Check if API returned valid response
        if data.get('status') != '1':
            error_message = data.get('message', 'Unknown API error')
            return False, 0, f"API Error: {error_message}"
        
        if 'result' not in data:
            return False, 0, "No transaction data found"
        
        # Find our specific transaction
        target_tx = None
        for tx in data['result']:
            if (tx.get('hash', '').lower() == txid.lower() and 
                tx.get('contractAddress', '').lower() == USDT_CONTRACT_ADDRESS.lower() and
                tx.get('to', '').lower() == DEPOSIT_ADDRESS.lower()):
                target_tx = tx
                break
        
        if not target_tx:
            return False, 0, "USDT transaction not found for this TXID"
        
        # Convert USDT amount from wei (18 decimals)
        usdt_amount = float(target_tx['value']) / 10**18
        
        # Check minimum deposit
        if usdt_amount < MIN_DEPOSIT:
            return False, 0, f"Amount ${usdt_amount:.2f} below minimum ${MIN_DEPOSIT}"
        
        # Check transaction time (within 2 minutes)
        tx_timestamp = int(target_tx['timeStamp'])
        current_time = int(time.time())
        
        if current_time - tx_timestamp > TIME_WINDOW_MINUTES * 60:
            time_diff = (current_time - tx_timestamp) // 60
            return False, 0, f"Transaction is {time_diff} minutes old (max {TIME_WINDOW_MINUTES} minutes allowed)"
        
        # Verify transaction success using transaction receipt
        receipt_params = {
            'module': 'transaction',
            'action': 'gettxreceiptstatus',
            'txhash': txid,
            'apikey': BSCSCAN_API_KEY
        }
        
        receipt_response = requests.get(api_url, params=receipt_params, timeout=30)
        receipt_data = receipt_response.json()
        
        if receipt_data.get('status') == '1' and receipt_data.get('result', {}).get('status') == '1':
            return True, usdt_amount, "Transaction verified successfully"
        else:
            return False, 0, "Transaction failed on blockchain"
        
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
        request_id = create_withdrawal_request(user_id, user_data['points'], usd_amount, user_data['wallet_address'])
        
        # Send notification to admin
        admin_message = (
            f"🔄 NEW WITHDRAWAL REQUEST #{request_id}\n\n"
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
            f"Use /approve {request_id} to approve\n"
            f"Use /reject {request_id} to reject"
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
            f"Request ID: #{request_id}\n"
            f"Points: {user_data['points']:.2f} PTS\n"
            f"Amount: ${usd_amount:.2f}\n"
            f"Wallet: {user_data['wallet_address']}\n\n"
            "Your request has been sent to admin for processing. "
            "You will be notified once it's processed."
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
        add_transaction(user_id, 'deposit', amount, txid)
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
        history_text += f"{emoji} {trans_type.upper()}: ${amount:.2f}\n"
        history_text += f"Status: {status}\n"
        history_text += f"Date: {created_at}\n"
        if txid:
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
    
    balance_text = (
        f"💰 Your Balance:\n\n"
        f"Points: {user_data['points']:.2f} PTS\n"
        f"Equivalent: ${user_data['points'] * POINT_RATE:.2f}\n"
        f"Deposit Balance: ${user_data['deposit_balance']:.2f} USDT\n\n"
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
        request_id, user_id, points, usd_amount, wallet_address, status, created_at, current_points, deposit_balance = withdrawal
        
        withdrawal_text = (
            f"🔄 PENDING WITHDRAWAL #{request_id}\n\n"
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
            f"Use /approve {request_id} to approve\n"
            f"Use /reject {request_id} to reject"
        )
        
        await update.message.reply_text(withdrawal_text, parse_mode='Markdown')

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /approve <request_id>")
        return
    
    try:
        request_id = int(context.args[0])
        withdrawal = get_withdrawal_by_id(request_id)
        
        if not withdrawal:
            await update.message.reply_text("❌ Withdrawal request not found.")
            return
        
        if withdrawal[5] != 'pending':  # status field
            await update.message.reply_text(f"❌ Withdrawal request already {withdrawal[5]}.")
            return
        
        # Update withdrawal status
        update_withdrawal_status(request_id, 'approved')
        
        # Deduct points from user
        user_data = get_user_data(withdrawal[1])
        new_points = user_data['points'] - withdrawal[2]  # Subtract withdrawal points
        update_user_points(withdrawal[1], new_points)
        
        # Add transaction record
        add_transaction(withdrawal[1], 'withdraw', withdrawal[3])  # usd_amount
        
        # Notify user
        try:
            user_message = (
                f"✅ Withdrawal Approved!\n\n"
                f"Request ID: #{request_id}\n"
                f"Amount: ${withdrawal[3]:.2f}\n"
                f"Points Deducted: {withdrawal[2]:.2f} PTS\n"
                f"New Balance: {new_points:.2f} PTS\n\n"
                f"Funds will be sent to your wallet shortly:\n"
                f"`{withdrawal[4]}`"
            )
            await context.bot.send_message(
                chat_id=withdrawal[1],
                text=user_message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await update.message.reply_text(
            f"✅ Withdrawal #{request_id} approved!\n"
            f"User {withdrawal[1]} points updated: {new_points:.2f} PTS"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Invalid request ID.")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /reject <request_id>")
        return
    
    try:
        request_id = int(context.args[0])
        withdrawal = get_withdrawal_by_id(request_id)
        
        if not withdrawal:
            await update.message.reply_text("❌ Withdrawal request not found.")
            return
        
        if withdrawal[5] != 'pending':
            await update.message.reply_text(f"❌ Withdrawal request already {withdrawal[5]}.")
            return
        
        # Update withdrawal status
        update_withdrawal_status(request_id, 'rejected')
        
        # Notify user
        try:
            user_message = (
                f"❌ Withdrawal Rejected\n\n"
                f"Request ID: #{request_id}\n"
                f"Amount: ${withdrawal[3]:.2f}\n"
                f"Points: {withdrawal[2]:.2f} PTS\n\n"
                f"Your withdrawal request has been rejected. "
                f"Please contact admin for more information."
            )
            await context.bot.send_message(
                chat_id=withdrawal[1],
                text=user_message
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await update.message.reply_text(f"✅ Withdrawal #{request_id} rejected.")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid request ID.")

# Other admin commands (setpoints, setdeposit, ban, unban, setwallet_admin, broadcast, stats, allusers)
# ... [Keep all the previous admin commands from the last code]

async def setpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /setpoints <user_id> <points>")
        return
    
    try:
        target_user_id = int(context.args[0])
        points = float(context.args[1])
        
        set_user_points(target_user_id, points)
        await update.message.reply_text(f"✅ Points set to {points} for user {target_user_id}")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID or points format")

async def setdeposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /setdeposit <user_id> <amount>")
        return
    
    try:
        target_user_id = int(context.args[0])
        amount = float(context.args[1])
        
        set_user_deposit(target_user_id, amount)
        await update.message.reply_text(f"✅ Deposit balance set to ${amount} for user {target_user_id}")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID or amount format")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
        ban_user(target_user_id)
        await update.message.reply_text(f"✅ User {target_user_id} banned")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
        unban_user(target_user_id)
        await update.message.reply_text(f"✅ User {target_user_id} unbanned")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def setwallet_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setwallet_admin <user_id> <wallet_address>")
        return
    
    try:
        target_user_id = int(context.args[0])
        wallet_address = ' '.join(context.args[1:])
        
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET wallet_address = ? WHERE user_id = ?', (wallet_address, target_user_id))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Wallet set for user {target_user_id}: {wallet_address}")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message = ' '.join(context.args)
    users = get_all_users()
    
    success_count = 0
    fail_count = 0
    
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=f"📢 Broadcast:\n\n{message}")
            success_count += 1
        except Exception as e:
            fail_count += 1
            logger.error(f"Failed to send broadcast to {user[0]}: {e}")
    
    await update.message.reply_text(f"✅ Broadcast sent:\nSuccess: {success_count}\nFailed: {fail_count}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    users = get_all_users()
    total_users = len(users)
    total_points = sum(user[1] for user in users)
    total_deposit = sum(user[2] for user in users)
    banned_users = sum(1 for user in users if user[3])
    
    # Get pending withdrawals count
    pending_withdrawals = get_pending_withdrawals()
    
    stats_text = (
        f"📊 Bot Statistics:\n\n"
        f"Total Users: {total_users}\n"
        f"Banned Users: {banned_users}\n"
        f"Pending Withdrawals: {len(pending_withdrawals)}\n"
        f"Total Points: {total_points:.2f}\n"
        f"Total Deposit: ${total_deposit:.2f}\n"
        f"Equivalent Value: ${total_points * POINT_RATE:.2f}"
    )
    
    await update.message.reply_text(stats_text)

async def allusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    users = get_all_users()
    
    if not users:
        await update.message.reply_text("No users found.")
        return
    
    users_text = "👥 All Users:\n\n"
    for user in users[:20]:  # Show first 20 users
        user_id, points, deposit, is_banned = user
        status = "❌ BANNED" if is_banned else "✅ ACTIVE"
        users_text += f"ID: {user_id}\nPoints: {points:.2f}\nDeposit: ${deposit:.2f}\nStatus: {status}\n"
        users_text += "─" * 20 + "\n"
    
    if len(users) > 20:
        users_text += f"\n... and {len(users) - 20} more users"
    
    await update.message.reply_text(users_text)

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
    application.add_handler(CommandHandler("setpoints", setpoints))
    application.add_handler(CommandHandler("setdeposit", setdeposit))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("setwallet_admin", setwallet_admin))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("allusers", allusers))
    
    # Start bot
    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
