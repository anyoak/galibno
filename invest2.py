import os
import logging
import requests
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import sqlite3

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
BSCSCAN_API_KEY = "AEUYN4PZ5XMBK5CFWHZ8MY7VZ83SGAWZSX"  # Your BscScan API key
ADMIN_ID = 6083895678
DEPOSIT_ADDRESS = "0x61d08Ba6CE508970C7b651953f0936fA8050Bd9B"
USDT_CONTRACT_ADDRESS = "0x55d398326f99059fF775485246999027B3197955"  # USDT BEP-20 contract
MIN_WITHDRAW = 100
MIN_DEPOSIT = 50
POINT_RATE = 0.10  # 1 point = $0.10
TIME_WINDOW_MINUTES = 2  # 2-minute time window for valid TX

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

def add_transaction(user_id, trans_type, amount, txid=None):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO transactions (user_id, type, amount, txid) VALUES (?, ?, ?, ?)',
                  (user_id, trans_type, amount, txid))
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
        # First, get transaction details
        tx_url = "https://api.bscscan.com/api"
        tx_params = {
            'module': 'proxy',
            'action': 'eth_getTransactionByHash',
            'txhash': txid,
            'apikey': BSCSCAN_API_KEY
        }
        
        response = requests.get(tx_url, params=tx_params, timeout=30)
        tx_data = response.json()
        
        if 'error' in tx_data or not tx_data.get('result'):
            return False, 0, "Transaction not found or invalid TXID"
        
        transaction = tx_data['result']
        
        # Check if transaction is to our deposit address
        if transaction.get('to', '').lower() != DEPOSIT_ADDRESS.lower():
            return False, 0, "Transaction not sent to correct deposit address"
        
        # Get transaction receipt to check status and get block number
        receipt_params = {
            'module': 'proxy',
            'action': 'eth_getTransactionReceipt',
            'txhash': txid,
            'apikey': BSCSCAN_API_KEY
        }
        
        receipt_response = requests.get(tx_url, params=receipt_params, timeout=30)
        receipt_data = receipt_response.json()
        
        if 'error' in receipt_data or not receipt_data.get('result'):
            return False, 0, "Transaction receipt not available"
        
        receipt = receipt_data['result']
        
        # Check if transaction was successful
        if receipt.get('status') != '0x1':
            return False, 0, "Transaction failed on blockchain"
        
        # Get block details to check timestamp
        block_number = receipt['blockNumber']
        block_params = {
            'module': 'proxy',
            'action': 'eth_getBlockByNumber',
            'tag': block_number,
            'boolean': 'true',
            'apikey': BSCSCAN_API_KEY
        }
        
        block_response = requests.get(tx_url, params=block_params, timeout=30)
        block_data = block_response.json()
        
        if 'error' in block_data or not block_data.get('result'):
            return False, 0, "Could not fetch block details"
        
        block = block_data['result']
        block_timestamp_hex = block['timestamp']
        block_timestamp = int(block_timestamp_hex, 16)
        
        # Check if transaction is within 2 minutes
        current_time = int(time.time())
        transaction_time = block_timestamp
        
        if current_time - transaction_time > TIME_WINDOW_MINUTES * 60:
            return False, 0, f"Transaction is older than {TIME_WINDOW_MINUTES} minutes"
        
        # Now check for USDT token transfer using token transfer API
        token_tx_params = {
            'module': 'account',
            'action': 'tokentx',
            'address': DEPOSIT_ADDRESS,
            'startblock': 0,
            'endblock': 99999999,
            'sort': 'desc',
            'apikey': BSCSCAN_API_KEY
        }
        
        token_response = requests.get(tx_url, params=token_tx_params, timeout=30)
        token_data = token_response.json()
        
        if 'error' in token_data or not token_data.get('result'):
            return False, 0, "Could not fetch token transfers"
        
        # Find our specific transaction in token transfers
        usdt_amount = 0
        for token_tx in token_data['result']:
            if (token_tx['hash'].lower() == txid.lower() and 
                token_tx['contractAddress'].lower() == USDT_CONTRACT_ADDRESS.lower() and
                token_tx['to'].lower() == DEPOSIT_ADDRESS.lower()):
                
                # Convert from wei (18 decimals for USDT on BSC)
                usdt_amount = float(token_tx['value']) / 10**18
                break
        
        if usdt_amount == 0:
            return False, 0, "No USDT transfer found in transaction"
        
        if usdt_amount < MIN_DEPOSIT:
            return False, 0, f"Amount ${usdt_amount:.2f} below minimum ${MIN_DEPOSIT}"
        
        return True, usdt_amount, "Transaction verified successfully"
        
    except requests.exceptions.Timeout:
        return False, 0, "BscScan API timeout - please try again later"
    except requests.exceptions.RequestException as e:
        return False, 0, f"Network error: {str(e)}"
    except Exception as e:
        logger.error(f"Error verifying transaction: {str(e)}")
        return False, 0, f"Verification error: {str(e)}"

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
            
        withdraw_text = (
            f"📤 Withdrawal Request\n\n"
            f"Points: {user_data['points']:.2f}\n"
            f"Wallet: {user_data['wallet_address']}\n"
            f"Amount: ${user_data['points'] * POINT_RATE:.2f}\n\n"
            "To proceed with withdrawal, please contact admin."
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
        update_user_points(user_id, user_data['points'] + points_to_add)
        add_transaction(user_id, 'deposit', amount, txid)
        mark_txid_processed(txid, user_id)
        
        await update.message.reply_text(
            f"✅ Deposit verified!\n"
            f"Amount: ${amount:.2f} USDT\n"
            f"Points added: {points_to_add:.2f} PTS\n"
            f"New balance: {user_data['points'] + points_to_add:.2f} PTS"
        )
    else:
        await update.message.reply_text(f"❌ Deposit verification failed: {message}")

# Other command handlers (setwallet, history, cancel, balance) remain the same as previous implementation
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

def main():
    # Initialize database
    init_db()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setwallet", set_wallet))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("txid", txid_handler))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start bot
    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()