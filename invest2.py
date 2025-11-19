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
import asyncio

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = "8441847556:AAGO_XbbN_eJJrL944JCO6uzHW7TDjS5VEQ"
ADMIN_ID = 6083895678
MIN_WITHDRAW = 100
MIN_DEPOSIT = 50
POINT_RATE = 0.10

# Database setup
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot_data.db', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_db()
    
    def init_db(self):
        cursor = self.conn.cursor()
        
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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deposit_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT UNIQUE,
                user_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending',
                payment_url TEXT,
                admin_message_id INTEGER,
                user_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        self.conn.commit()
    
    def execute(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()
        return cursor
    
    def fetchone(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
    
    def fetchall(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

# Initialize database
db = Database()

def generate_request_number():
    return str(random.randint(1000, 9999))

def generate_invoice_number():
    return str(random.randint(100000, 999999))

def get_user_data(user_id):
    user = db.fetchone('SELECT * FROM users WHERE user_id = ?', (user_id,))
    if user:
        return dict(user)
    else:
        db.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
        return {
            'user_id': user_id,
            'points': 0,
            'deposit_balance': 0,
            'wallet_address': None,
            'is_banned': False
        }

def has_pending_withdrawal(user_id):
    result = db.fetchone('SELECT id FROM withdrawal_requests WHERE user_id = ? AND status = "pending"', (user_id,))
    return result is not None

def has_pending_deposit(user_id):
    result = db.fetchone('SELECT id FROM deposit_invoices WHERE user_id = ? AND status IN ("pending", "waiting_payment")', (user_id,))
    return result is not None

def update_user_points(user_id, points):
    db.execute('UPDATE users SET points = ? WHERE user_id = ?', (points, user_id))

def update_deposit_balance(user_id, amount):
    db.execute('UPDATE users SET deposit_balance = deposit_balance + ? WHERE user_id = ?', (amount, user_id))

def add_transaction(user_id, trans_type, amount, txid=None, status='pending'):
    db.execute('INSERT INTO transactions (user_id, type, amount, txid, status) VALUES (?, ?, ?, ?, ?)',
              (user_id, trans_type, amount, txid, status))

def update_transaction_status(txid, status):
    db.execute('UPDATE transactions SET status = ? WHERE txid = ?', (status, txid))

def create_withdrawal_request(user_id, points, usd_amount, wallet_address):
    request_number = generate_request_number()
    
    # Ensure uniqueness
    while db.fetchone('SELECT id FROM withdrawal_requests WHERE request_number = ?', (request_number,)):
        request_number = generate_request_number()
    
    db.execute('''
        INSERT INTO withdrawal_requests (request_number, user_id, points, usd_amount, wallet_address, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    ''', (request_number, user_id, points, usd_amount, wallet_address))
    
    add_transaction(user_id, 'withdraw', usd_amount, f"REQ-{request_number}", 'pending')
    
    return request_number

def create_deposit_invoice(user_id, amount):
    invoice_number = generate_invoice_number()
    
    # Ensure uniqueness
    while db.fetchone('SELECT id FROM deposit_invoices WHERE invoice_number = ?', (invoice_number,)):
        invoice_number = generate_invoice_number()
    
    db.execute('''
        INSERT INTO deposit_invoices (invoice_number, user_id, amount, status)
        VALUES (?, ?, ?, 'pending')
    ''', (invoice_number, user_id, amount))
    
    return invoice_number

def update_invoice_url(invoice_number, payment_url, admin_message_id, user_message_id):
    db.execute('''
        UPDATE deposit_invoices 
        SET payment_url = ?, admin_message_id = ?, user_message_id = ?, status = 'waiting_payment'
        WHERE invoice_number = ?
    ''', (payment_url, admin_message_id, user_message_id, invoice_number))

def update_invoice_status(invoice_number, status):
    db.execute('UPDATE deposit_invoices SET status = ? WHERE invoice_number = ?', (status, invoice_number))

def get_invoice_by_number(invoice_number):
    return db.fetchone('''
        SELECT di.*, u.points, u.deposit_balance 
        FROM deposit_invoices di
        JOIN users u ON di.user_id = u.user_id
        WHERE di.invoice_number = ?
    ''', (invoice_number,))

def get_pending_deposit_invoices():
    return db.fetchall('''
        SELECT di.*, u.points, u.deposit_balance 
        FROM deposit_invoices di
        JOIN users u ON di.user_id = u.user_id
        WHERE di.status IN ('pending', 'waiting_payment')
        ORDER BY di.created_at DESC
    ''')

def get_pending_withdrawals():
    return db.fetchall('''
        SELECT wr.*, u.points as current_points, u.deposit_balance 
        FROM withdrawal_requests wr
        JOIN users u ON wr.user_id = u.user_id
        WHERE wr.status = 'pending'
        ORDER BY wr.created_at DESC
    ''')

def get_withdrawal_by_request_number(request_number):
    return db.fetchone('''
        SELECT wr.*, u.points as current_points, u.deposit_balance 
        FROM withdrawal_requests wr
        JOIN users u ON wr.user_id = u.user_id
        WHERE wr.request_number = ?
    ''', (request_number,))

def update_withdrawal_status(request_number, status):
    db.execute('UPDATE withdrawal_requests SET status = ? WHERE request_number = ?', (status, request_number))
    update_transaction_status(f"REQ-{request_number}", status)

# Safe message editing function
async def safe_edit_message(message, new_text, reply_markup=None):
    try:
        await message.edit_text(new_text, reply_markup=reply_markup)
        return True
    except Exception as e:
        logger.warning(f"Message edit failed: {e}")
        return False

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
        "🤖 **Welcome to Crypto Bot!**\n\n"
        "💎 **1 Point = $0.10**\n"
        f"💸 **Min Withdraw:** {MIN_WITHDRAW} points\n"
        f"💰 **Min Deposit:** ${MIN_DEPOSIT} USDT\n\n"
        "Use /setwallet to set your SOL wallet for withdrawals"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

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
        await safe_edit_message(query.message, f"💰 {user_data['points']:.2f} PTS", reply_markup)
        
    elif query.data == "deposit":
        if has_pending_deposit(user_id):
            await query.edit_message_text(
                "⏳ You already have a pending deposit request. "
                "Please wait for it to be processed before making a new deposit."
            )
            return
            
        await query.edit_message_text(
            "💵 **Enter Deposit Amount**\n\n"
            f"Minimum: ${MIN_DEPOSIT} USDT\n\n"
            "Send the amount as a message:\n"
            "**Example:** `50` or `100`"
        )
        context.user_data['waiting_for_deposit_amount'] = True
        
    elif query.data == "withdraw":
        if has_pending_withdrawal(user_id):
            await query.edit_message_text(
                "⏳ You already have a pending withdrawal request. "
                "Please wait for it to be processed before making a new request."
            )
            return
            
        if user_data['points'] < MIN_WITHDRAW:
            await query.edit_message_text(
                f"❌ **Minimum withdrawal is {MIN_WITHDRAW} points.**\n"
                f"Your current points: {user_data['points']:.2f}"
            )
            return
            
        if not user_data['wallet_address']:
            await query.edit_message_text(
                "❌ Please set your SOL wallet first using /setwallet"
            )
            return
        
        usd_amount = user_data['points'] * POINT_RATE
        request_number = create_withdrawal_request(user_id, user_data['points'], usd_amount, user_data['wallet_address'])
        
        # Send notification to admin
        admin_message = (
            f"🔄 **NEW WITHDRAWAL REQUEST** #{request_number}\n\n"
            f"👤 **User:** {user_id} (@{query.from_user.username or 'N/A'})\n"
            f"💰 **Amount:** ${usd_amount:.2f}\n"
            f"💎 **Points:** {user_data['points']:.2f} PTS\n"
            f"💳 **Wallet:** `{user_data['wallet_address']}`\n\n"
            f"Use: `/approve {request_number}` to approve\n"
            f"Use: `/reject {request_number}` to reject"
        )
        
        try:
            await context.bot.send_message(ADMIN_ID, text=admin_message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Admin notification failed: {e}")
            
        await query.edit_message_text(
            f"✅ **Withdrawal Request Submitted!**\n\n"
            f"📋 **Request ID:** #{request_number}\n"
            f"💰 **Amount:** ${usd_amount:.2f}\n"
            f"💎 **Points:** {user_data['points']:.2f} PTS\n\n"
            "⏳ Waiting for admin approval..."
        )
    
    elif query.data.startswith("confirm_payment_"):
        invoice_number = query.data.replace("confirm_payment_", "")
        invoice = get_invoice_by_number(invoice_number)
        
        if not invoice or invoice['user_id'] != user_id:
            await query.edit_message_text("❌ Invoice not found.")
            return
        
        update_invoice_status(invoice_number, 'paid')
        
        admin_keyboard = [
            [
                InlineKeyboardButton("✅ Approve Deposit", callback_data=f"admin_approve_{invoice_number}"),
                InlineKeyboardButton("❌ Reject Deposit", callback_data=f"admin_reject_{invoice_number}")
            ]
        ]
        admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)
        
        admin_message = (
            f"💰 **PAYMENT CONFIRMED** #{invoice_number}\n\n"
            f"👤 **User:** {user_id} (@{query.from_user.username or 'N/A'})\n"
            f"💵 **Amount:** ${invoice['amount']:.2f}\n"
            f"💎 **Points to add:** {invoice['amount'] / POINT_RATE:.2f} PTS\n\n"
            f"**Approve this deposit?**"
        )
        
        try:
            admin_msg = await context.bot.send_message(
                ADMIN_ID,
                text=admin_message,
                reply_markup=admin_reply_markup
            )
            db.execute('UPDATE deposit_invoices SET admin_message_id = ? WHERE invoice_number = ?', 
                      (admin_msg.message_id, invoice_number))
        except Exception as e:
            logger.error(f"Admin message failed: {e}")
        
        await query.edit_message_text(
            f"✅ **Payment Confirmed!**\n\n"
            f"📋 **Invoice:** #{invoice_number}\n"
            f"💰 **Amount:** ${invoice['amount']:.2f}\n\n"
            "⏳ Waiting for admin approval...\n\n"
            "If admin doesn't respond within 1 hour, please contact support."
        )
    
    elif query.data.startswith("admin_approve_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ Access denied.", show_alert=True)
            return
            
        invoice_number = query.data.replace("admin_approve_", "")
        invoice = get_invoice_by_number(invoice_number)
        
        if not invoice:
            await query.edit_message_text("❌ Invoice not found.")
            return
        
        update_invoice_status(invoice_number, 'approved')
        amount = invoice['amount']
        points_to_add = amount / POINT_RATE
        user_id = invoice['user_id']
        
        update_deposit_balance(user_id, amount)
        user_data = get_user_data(user_id)
        new_points = user_data['points'] + points_to_add
        update_user_points(user_id, new_points)
        
        add_transaction(user_id, 'deposit', amount, f"INV-{invoice_number}", 'approved')
        
        try:
            user_message = (
                f"✅ **Deposit Approved!**\n\n"
                f"📋 **Invoice:** #{invoice_number}\n"
                f"💰 **Amount:** ${amount:.2f}\n"
                f"💎 **Points Added:** {points_to_add:.2f} PTS\n"
                f"💳 **New Balance:** {new_points:.2f} PTS\n\n"
                f"Thank you for your deposit! 🎉"
            )
            await context.bot.send_message(user_id, text=user_message)
        except Exception as e:
            logger.error(f"User notification failed: {e}")
        
        await query.edit_message_text(f"✅ Deposit #{invoice_number} approved! User balance updated.")
    
    elif query.data.startswith("admin_reject_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ Access denied.", show_alert=True)
            return
            
        invoice_number = query.data.replace("admin_reject_", "")
        invoice = get_invoice_by_number(invoice_number)
        
        if not invoice:
            await query.edit_message_text("❌ Invoice not found.")
            return
        
        update_invoice_status(invoice_number, 'rejected')
        user_id = invoice['user_id']
        
        try:
            user_message = (
                f"❌ **Deposit Rejected**\n\n"
                f"📋 **Invoice:** #{invoice_number}\n"
                f"💰 **Amount:** ${invoice['amount']:.2f}\n\n"
                f"Your deposit request has been rejected.\n"
                f"Please contact admin for more information."
            )
            await context.bot.send_message(user_id, text=user_message)
        except Exception as e:
            logger.error(f"User notification failed: {e}")
        
        await query.edit_message_text(f"❌ Deposit #{invoice_number} rejected. User notified.")

# Handle deposit amount input
async def handle_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    if not context.user_data.get('waiting_for_deposit_amount'):
        return
    
    try:
        amount = float(update.message.text)
        
        if amount < MIN_DEPOSIT:
            await update.message.reply_text(f"❌ Minimum deposit is ${MIN_DEPOSIT}")
            return
        
        invoice_number = create_deposit_invoice(user_id, amount)
        context.user_data['waiting_for_deposit_amount'] = False
        
        # Send creating message
        creating_msg = await update.message.reply_text(f"🔄 Creating invoice for ${amount:.2f}")
        
        # Simple animation without multiple edits
        await asyncio.sleep(2)
        
        # Send to admin
        admin_keyboard = [[InlineKeyboardButton("📤 Send Payment URL", callback_data=f"send_url_{invoice_number}")]]
        admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)
        
        admin_message = (
            f"💰 **NEW DEPOSIT INVOICE** #{invoice_number}\n\n"
            f"👤 **User:** {user_id} (@{update.effective_user.username or 'N/A'})\n"
            f"💵 **Amount:** ${amount:.2f}\n"
            f"💎 **Points to add:** {amount / POINT_RATE:.2f} PTS\n\n"
            f"**Click below to send payment URL:**"
        )
        
        try:
            admin_msg = await context.bot.send_message(
                ADMIN_ID,
                text=admin_message,
                reply_markup=admin_reply_markup
            )
            db.execute('UPDATE deposit_invoices SET admin_message_id = ? WHERE invoice_number = ?', 
                      (admin_msg.message_id, invoice_number))
        except Exception as e:
            logger.error(f"Admin message failed: {e}")
            await creating_msg.edit_text("❌ Failed to create invoice. Please try again.")
            return
        
        await creating_msg.edit_text(
            f"✅ **Invoice Created!**\n\n"
            f"📋 **Invoice Number:** #{invoice_number}\n"
            f"💰 **Amount:** ${amount:.2f}\n"
            f"💎 **Points:** {amount / POINT_RATE:.2f} PTS\n\n"
            "⏳ Admin will send payment URL shortly..."
        )
        
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number (e.g., 50, 100, 150)")

# Handle admin URL sending
async def admin_send_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Access denied.", show_alert=True)
        return
    
    invoice_number = query.data.replace("send_url_", "")
    invoice = get_invoice_by_number(invoice_number)
    
    if not invoice:
        await query.edit_message_text("❌ Invoice not found.")
        return
    
    await query.edit_message_text(
        f"📤 **Send Payment URL**\n\n"
        f"📋 **Invoice:** #{invoice_number}\n"
        f"👤 **User:** {invoice['user_id']}\n"
        f"💵 **Amount:** ${invoice['amount']:.2f}\n\n"
        "**Please reply with the payment URL:**"
    )
    
    context.user_data['waiting_url_for'] = invoice_number

# Handle admin URL input
async def handle_admin_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    if not context.user_data.get('waiting_url_for'):
        return
    
    invoice_number = context.user_data['waiting_url_for']
    payment_url = update.message.text.strip()
    
    if not payment_url.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ Please provide a valid URL starting with http:// or https://")
        return
    
    invoice = get_invoice_by_number(invoice_number)
    
    if not invoice:
        await update.message.reply_text("❌ Invoice not found.")
        return
    
    user_id = invoice['user_id']
    
    # Send URL to user
    user_keyboard = [
        [InlineKeyboardButton("📥 Pay Now", url=payment_url)],
        [InlineKeyboardButton("✅ I've Completed Payment", callback_data=f"confirm_payment_{invoice_number}")]
    ]
    user_reply_markup = InlineKeyboardMarkup(user_keyboard)
    
    user_message = (
        f"🔄 **Please Complete Deposit**\n\n"
        f"📋 **Invoice:** #{invoice_number}\n"
        f"💵 **Amount:** ${invoice['amount']:.2f}\n"
        f"💎 **Points:** {invoice['amount'] / POINT_RATE:.2f} PTS\n\n"
        f"**Click the button below to make payment:**"
    )
    
    try:
        user_msg = await context.bot.send_message(
            user_id,
            text=user_message,
            reply_markup=user_reply_markup
        )
        update_invoice_url(invoice_number, payment_url, update.message.message_id, user_msg.message_id)
    except Exception as e:
        logger.error(f"User message failed: {e}")
        await update.message.reply_text("❌ Failed to send URL to user. User may have blocked the bot.")
        return
    
    await update.message.reply_text(
        f"✅ **Payment URL Sent!**\n\n"
        f"📋 **Invoice:** #{invoice_number}\n"
        f"👤 **User:** {user_id}\n"
        f"✅ User notified successfully"
    )
    context.user_data['waiting_url_for'] = None

# Admin commands
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    commands = """
👑 **ADMIN PANEL COMMANDS**

📊 **Statistics:**
/stats - Bot statistics

📥 **Deposit Management:**
/deposits - Pending deposits

💸 **Withdrawal Management:**
/withdrawals - Pending withdrawals
/approve <request_id> - Approve withdrawal
/reject <request_id> - Reject withdrawal

👥 **User Management:**
/users - All users
/ban <user_id> - Ban user
/unban <user_id> - Unban user
/setpoints <user_id> <points> - Set user points

📢 **Broadcast:**
/broadcast <message> - Broadcast to all users
"""
    await update.message.reply_text(commands, parse_mode='Markdown')

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    users = db.fetchall('SELECT COUNT(*) as count, SUM(points) as total_points, SUM(deposit_balance) as total_deposit FROM users')
    pending_deposits = db.fetchall('SELECT COUNT(*) as count FROM deposit_invoices WHERE status IN ("pending", "waiting_payment")')
    pending_withdrawals = db.fetchall('SELECT COUNT(*) as count FROM withdrawal_requests WHERE status = "pending"')
    
    stats_text = (
        f"📊 **BOT STATISTICS**\n\n"
        f"👥 **Total Users:** {users[0]['count']}\n"
        f"💎 **Total Points:** {users[0]['total_points'] or 0:.2f}\n"
        f"💰 **Total Deposit:** ${users[0]['total_deposit'] or 0:.2f}\n"
        f"📥 **Pending Deposits:** {pending_deposits[0]['count']}\n"
        f"📤 **Pending Withdrawals:** {pending_withdrawals[0]['count']}\n"
        f"💵 **Total Value:** ${(users[0]['total_points'] or 0) * POINT_RATE:.2f}"
    )
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    invoices = get_pending_deposit_invoices()
    
    if not invoices:
        await update.message.reply_text("✅ No pending deposits")
        return
    
    for invoice in invoices:
        status_text = "🟡 Waiting URL" if invoice['status'] == 'pending' else "🟠 Waiting Payment"
        
        message = (
            f"💰 **INVOICE** #{invoice['invoice_number']}\n"
            f"👤 **User:** {invoice['user_id']}\n"
            f"💵 **Amount:** ${invoice['amount']:.2f}\n"
            f"📊 **Status:** {status_text}\n"
            f"📅 **Created:** {invoice['created_at']}\n"
            f"💎 **User Points:** {invoice['points']:.2f} PTS"
        )
        
        keyboard = [[InlineKeyboardButton("📤 Send URL", callback_data=f"send_url_{invoice['invoice_number']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    withdrawals = get_pending_withdrawals()
    
    if not withdrawals:
        await update.message.reply_text("✅ No pending withdrawals")
        return
    
    for withdrawal in withdrawals:
        message = (
            f"💸 **WITHDRAWAL** #{withdrawal['request_number']}\n"
            f"👤 **User:** {withdrawal['user_id']}\n"
            f"💵 **Amount:** ${withdrawal['usd_amount']:.2f}\n"
            f"💎 **Points:** {withdrawal['points']:.2f} PTS\n"
            f"💳 **Wallet:** {withdrawal['wallet_address']}\n"
            f"📅 **Created:** {withdrawal['created_at']}"
        )
        
        await update.message.reply_text(message, parse_mode='Markdown')

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /approve REQUEST_NUMBER")
        return
    
    request_number = context.args[0]
    withdrawal = get_withdrawal_by_request_number(request_number)
    
    if not withdrawal:
        await update.message.reply_text("❌ Withdrawal not found")
        return
    
    update_withdrawal_status(request_number, 'approved')
    user_data = get_user_data(withdrawal['user_id'])
    new_points = user_data['points'] - withdrawal['points']
    update_user_points(withdrawal['user_id'], new_points)
    
    try:
        user_message = (
            f"✅ **Withdrawal Approved!**\n\n"
            f"📋 **Request:** #{request_number}\n"
            f"💵 **Amount:** ${withdrawal['usd_amount']:.2f}\n"
            f"💎 **New Balance:** {new_points:.2f} PTS\n\n"
            f"Funds will be sent to your wallet shortly."
        )
        await context.bot.send_message(withdrawal['user_id'], text=user_message)
    except Exception as e:
        logger.error(f"User notification failed: {e}")
    
    await update.message.reply_text(f"✅ Withdrawal #{request_number} approved! User balance updated.")

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /reject REQUEST_NUMBER")
        return
    
    request_number = context.args[0]
    withdrawal = get_withdrawal_by_request_number(request_number)
    
    if not withdrawal:
        await update.message.reply_text("❌ Withdrawal not found")
        return
    
    update_withdrawal_status(request_number, 'rejected')
    
    try:
        user_message = f"❌ Withdrawal #{request_number} rejected. Contact admin."
        await context.bot.send_message(withdrawal['user_id'], text=user_message)
    except Exception as e:
        logger.error(f"User notification failed: {e}")
    
    await update.message.reply_text(f"❌ Withdrawal #{request_number} rejected. User notified.")

async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    all_users = db.fetchall('SELECT user_id, points, deposit_balance, is_banned FROM users ORDER BY points DESC LIMIT 50')
    
    if not all_users:
        await update.message.reply_text("❌ No users found")
        return
    
    users_text = "👥 **ALL USERS** (Top 50 by points)\n\n"
    
    for user in all_users:
        status = "❌ BANNED" if user['is_banned'] else "✅ ACTIVE"
        users_text += f"👤 **User:** {user['user_id']}\n"
        users_text += f"💎 **Points:** {user['points']:.2f}\n"
        users_text += f"💰 **Deposit:** ${user['deposit_balance']:.2f}\n"
        users_text += f"📊 **Status:** {status}\n"
        users_text += "─" * 20 + "\n"
    
    await update.message.reply_text(users_text, parse_mode='Markdown')

# User commands
async def set_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /setwallet YOUR_SOL_WALLET_ADDRESS")
        return
    
    wallet_address = ' '.join(context.args)
    db.execute('UPDATE users SET wallet_address = ? WHERE user_id = ?', (wallet_address, user_id))
    
    await update.message.reply_text(f"✅ **SOL Wallet Set!**\n\n`{wallet_address}`", parse_mode='Markdown')

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    pending_withdrawal = has_pending_withdrawal(user_id)
    pending_deposit = has_pending_deposit(user_id)
    
    status = "⏳ Pending deposit" if pending_deposit else "⏳ Pending withdrawal" if pending_withdrawal else "✅ Active"
    
    balance_text = (
        f"💰 **YOUR BALANCE**\n\n"
        f"💎 **Points:** {user_data['points']:.2f} PTS\n"
        f"💵 **Value:** ${user_data['points'] * POINT_RATE:.2f}\n"
        f"📥 **Deposited:** ${user_data['deposit_balance']:.2f}\n"
        f"📊 **Status:** {status}\n"
        f"💳 **Wallet:** {user_data['wallet_address'] or 'Not set'}"
    )
    
    await update.message.reply_text(balance_text, parse_mode='Markdown')

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    transactions = db.fetchall('''
        SELECT type, amount, txid, status, created_at 
        FROM transactions 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT 10
    ''', (user_id,))
    
    if not transactions:
        await update.message.reply_text("📊 No transactions found")
        return
    
    history_text = "📊 **TRANSACTION HISTORY**\n\n"
    for trans in transactions:
        emoji = "📥" if trans['type'] == 'deposit' else "📤"
        status_emoji = "✅" if trans['status'] == 'approved' else "❌" if trans['status'] == 'rejected' else "⏳"
        
        history_text += f"{emoji} **{trans['type'].upper()}:** ${trans['amount']:.2f}\n"
        history_text += f"**Status:** {status_emoji} {trans['status'].upper()}\n"
        
        if trans['txid']:
            if trans['txid'].startswith("REQ-"):
                history_text += f"**Request:** #{trans['txid'].replace('REQ-', '')}\n"
            elif trans['txid'].startswith("INV-"):
                history_text += f"**Invoice:** #{trans['txid'].replace('INV-', '')}\n"
        
        history_text += f"**Date:** {trans['created_at']}\n"
        history_text += "─" * 20 + "\n"
    
    await update.message.reply_text(history_text, parse_mode='Markdown')

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

def main():
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add all handlers with proper command names
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setwallet", set_wallet))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("cancel", cancel))
    
    # Admin commands - fixed command names
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("deposits", deposits))
    application.add_handler(CommandHandler("withdrawals", withdrawals))
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(CommandHandler("reject", reject))
    application.add_handler(CommandHandler("users", users))
    
    # Callback queries
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CallbackQueryHandler(admin_send_url, pattern="^send_url_"))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deposit_amount))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_url))
    
    # Start bot
    print("🤖 Bot is starting...")
    print("✅ Database initialized")
    print("🔄 Bot is running...")
    
    # Run with restart capability
    while True:
        try:
            application.run_polling(
                poll_interval=1,
                timeout=30,
                drop_pending_updates=True
            )
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
            print(f"🔄 Restarting bot in 5 seconds...")
            time.sleep(5)

if __name__ == '__main__':
    main()