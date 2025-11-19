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
            status TEXT DEFAULT 'pending', -- pending, waiting_payment, paid, approved, rejected
            payment_url TEXT,
            admin_message_id INTEGER,
            user_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

def generate_request_number():
    """Generate 4-digit random request number"""
    return str(random.randint(1000, 9999))

def generate_invoice_number():
    """Generate 6-digit random invoice number"""
    return str(random.randint(100000, 999999))

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

def has_pending_deposit(user_id):
    """Check if user has pending deposit invoice"""
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM deposit_invoices WHERE user_id = ? AND status IN ("pending", "waiting_payment")', (user_id,))
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

def create_deposit_invoice(user_id, amount):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    # Generate unique invoice number
    invoice_number = generate_invoice_number()
    
    # Ensure uniqueness
    cursor.execute('SELECT id FROM deposit_invoices WHERE invoice_number = ?', (invoice_number,))
    while cursor.fetchone():
        invoice_number = generate_invoice_number()
        cursor.execute('SELECT id FROM deposit_invoices WHERE invoice_number = ?', (invoice_number,))
    
    cursor.execute('''
        INSERT INTO deposit_invoices (invoice_number, user_id, amount, status)
        VALUES (?, ?, ?, 'pending')
    ''', (invoice_number, user_id, amount))
    
    invoice_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return invoice_number

def update_invoice_url(invoice_number, payment_url, admin_message_id, user_message_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE deposit_invoices 
        SET payment_url = ?, admin_message_id = ?, user_message_id = ?, status = 'waiting_payment'
        WHERE invoice_number = ?
    ''', (payment_url, admin_message_id, user_message_id, invoice_number))
    conn.commit()
    conn.close()

def update_invoice_status(invoice_number, status):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE deposit_invoices SET status = ? WHERE invoice_number = ?', (status, invoice_number))
    conn.commit()
    conn.close()

def get_invoice_by_number(invoice_number):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT di.*, u.points, u.deposit_balance 
        FROM deposit_invoices di
        JOIN users u ON di.user_id = u.user_id
        WHERE di.invoice_number = ?
    ''', (invoice_number,))
    invoice = cursor.fetchone()
    conn.close()
    return invoice

def get_pending_deposit_invoices():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT di.*, u.points, u.deposit_balance 
        FROM deposit_invoices di
        JOIN users u ON di.user_id = u.user_id
        WHERE di.status IN ('pending', 'waiting_payment')
        ORDER BY di.created_at DESC
    ''')
    invoices = cursor.fetchall()
    conn.close()
    return invoices

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
        # Check if user has pending deposit
        if has_pending_deposit(user_id):
            await query.edit_message_text(
                "⏳ You already have a pending deposit request. "
                "Please wait for it to be processed before making a new deposit."
            )
            return
            
        await query.edit_message_text(
            "💵 Please enter the amount you want to deposit (minimum $50):\n\n"
            "Send the amount as a message (e.g., 50 or 100)"
        )
        context.user_data['waiting_for_deposit_amount'] = True
        
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
    
    # Handle deposit payment confirmation
    elif query.data.startswith("confirm_payment_"):
        invoice_number = query.data.replace("confirm_payment_", "")
        invoice = get_invoice_by_number(invoice_number)
        
        if not invoice:
            await query.edit_message_text("❌ Invoice not found.")
            return
            
        if invoice[3] != user_id:  # user_id field
            await query.edit_message_text("❌ This is not your invoice.")
            return
        
        # Update invoice status to paid
        update_invoice_status(invoice_number, 'paid')
        
        # Send approval request to admin
        admin_keyboard = [
            [
                InlineKeyboardButton("✅ Approve Deposit", callback_data=f"admin_approve_deposit_{invoice_number}"),
                InlineKeyboardButton("❌ Reject Deposit", callback_data=f"admin_reject_deposit_{invoice_number}")
            ]
        ]
        admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)
        
        admin_message = (
            f"💰 DEPOSIT PAYMENT CONFIRMED\n\n"
            f"Invoice: #{invoice_number}\n"
            f"User: {user_id} (@{query.from_user.username or 'N/A'})\n"
            f"Amount: ${invoice[2]:.2f}\n\n"
            f"User claims to have completed the payment.\n\n"
            f"Approve to add ${invoice[2]:.2f} to user balance?"
        )
        
        admin_msg = await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            reply_markup=admin_reply_markup,
            parse_mode='Markdown'
        )
        
        # Store admin message ID for later reference
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE deposit_invoices SET admin_message_id = ? WHERE invoice_number = ?', 
                      (admin_msg.message_id, invoice_number))
        conn.commit()
        conn.close()
        
        await query.edit_message_text(
            f"✅ Payment confirmation sent!\n\n"
            f"Invoice: #{invoice_number}\n"
            f"Amount: ${invoice[2]:.2f}\n\n"
            "⏳ Waiting for admin approval. This usually takes a few minutes.\n\n"
            "If admin doesn't respond within 1 hour, please contact support."
        )
    
    # Handle admin deposit approval
    elif query.data.startswith("admin_approve_deposit_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ Access denied.", show_alert=True)
            return
            
        invoice_number = query.data.replace("admin_approve_deposit_", "")
        invoice = get_invoice_by_number(invoice_number)
        
        if not invoice:
            await query.edit_message_text("❌ Invoice not found.")
            return
        
        # Update invoice status
        update_invoice_status(invoice_number, 'approved')
        
        # Calculate points and update user balance
        amount = invoice[2]  # amount field
        points_to_add = amount / POINT_RATE
        user_id = invoice[3]  # user_id field
        
        update_deposit_balance(user_id, amount)
        user_data = get_user_data(user_id)
        new_points = user_data['points'] + points_to_add
        update_user_points(user_id, new_points)
        
        # Add transaction record
        add_transaction(user_id, 'deposit', amount, f"INV-{invoice_number}", 'approved')
        
        # Notify user
        try:
            user_message = (
                f"✅ Deposit Approved!\n\n"
                f"Invoice: #{invoice_number}\n"
                f"Amount: ${amount:.2f}\n"
                f"Points Added: {points_to_add:.2f} PTS\n"
                f"New Balance: {new_points:.2f} PTS\n\n"
                f"Thank you for your deposit!"
            )
            await context.bot.send_message(chat_id=user_id, text=user_message)
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await query.edit_message_text(
            f"✅ Deposit approved!\n\n"
            f"Invoice: #{invoice_number}\n"
            f"User: {user_id}\n"
            f"Amount: ${amount:.2f}\n"
            f"Points Added: {points_to_add:.2f}\n"
            f"User balance updated successfully."
        )
    
    # Handle admin deposit rejection
    elif query.data.startswith("admin_reject_deposit_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ Access denied.", show_alert=True)
            return
            
        invoice_number = query.data.replace("admin_reject_deposit_", "")
        invoice = get_invoice_by_number(invoice_number)
        
        if not invoice:
            await query.edit_message_text("❌ Invoice not found.")
            return
        
        # Update invoice status
        update_invoice_status(invoice_number, 'rejected')
        
        # Notify user
        user_id = invoice[3]  # user_id field
        amount = invoice[2]  # amount field
        
        try:
            user_message = (
                f"❌ Deposit Rejected\n\n"
                f"Invoice: #{invoice_number}\n"
                f"Amount: ${amount:.2f}\n\n"
                f"Your deposit request has been rejected. "
                f"Please contact admin for more information."
            )
            await context.bot.send_message(chat_id=user_id, text=user_message)
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await query.edit_message_text(
            f"❌ Deposit rejected!\n\n"
            f"Invoice: #{invoice_number}\n"
            f"User: {user_id}\n"
            f"Amount: ${amount:.2f}\n\n"
            f"User has been notified."
        )

# Handle text messages for deposit amount
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if user_data['is_banned']:
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    
    # Check if we're waiting for deposit amount
    if context.user_data.get('waiting_for_deposit_amount'):
        try:
            amount = float(update.message.text)
            
            if amount < MIN_DEPOSIT:
                await update.message.reply_text(
                    f"❌ Minimum deposit is ${MIN_DEPOSIT}. Please enter a higher amount."
                )
                return
            
            # Create invoice
            invoice_number = create_deposit_invoice(user_id, amount)
            
            # Clear the flag
            context.user_data['waiting_for_deposit_amount'] = False
            
            # Send creating invoice message with animation
            creating_msg = await update.message.reply_text(
                f"🔄 Creating invoice for ${amount:.2f}...\n\n"
                "Please wait while we generate your payment details."
            )
            
            # Simulate processing animation
            for i in range(3):
                await asyncio.sleep(1)
                dots = "." * (i + 1)
                await creating_msg.edit_text(
                    f"🔄 Creating invoice for ${amount:.2f}{dots}\n\n"
                    "Please wait while we generate your payment details."
                )
            
            # Send invoice details to admin with reply button
            admin_keyboard = [
                [InlineKeyboardButton("📤 Send Payment URL", callback_data=f"send_url_{invoice_number}")]
            ]
            admin_reply_markup = InlineKeyboardMarkup(admin_keyboard)
            
            admin_message = (
                f"💰 NEW DEPOSIT INVOICE\n\n"
                f"Invoice: #{invoice_number}\n"
                f"User: {user_id} (@{update.effective_user.username or 'N/A'})\n"
                f"Amount: ${amount:.2f}\n"
                f"Points to add: {amount / POINT_RATE:.2f} PTS\n\n"
                f"Click the button below to send payment URL to user."
            )
            
            admin_msg = await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_message,
                reply_markup=admin_reply_markup,
                parse_mode='Markdown'
            )
            
            # Store admin message ID
            conn = sqlite3.connect('bot_data.db')
            cursor = conn.cursor()
            cursor.execute('UPDATE deposit_invoices SET admin_message_id = ? WHERE invoice_number = ?', 
                          (admin_msg.message_id, invoice_number))
            conn.commit()
            conn.close()
            
            await creating_msg.edit_text(
                f"✅ Invoice Created!\n\n"
                f"Invoice: #{invoice_number}\n"
                f"Amount: ${amount:.2f}\n\n"
                "⏳ Waiting for admin to send payment URL...\n"
                "You will receive the payment link shortly."
            )
            
        except ValueError:
            await update.message.reply_text(
                "❌ Please enter a valid number for the deposit amount."
            )

# Handle admin sending payment URL
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
    
    # Ask admin for payment URL
    await query.edit_message_text(
        f"📤 Send Payment URL for Invoice #{invoice_number}\n\n"
        f"Amount: ${invoice[2]:.2f}\n"
        f"User: {invoice[3]}\n\n"
        "Please reply with the payment URL:"
    )
    
    # Store context for the next message
    context.user_data['waiting_for_payment_url'] = invoice_number

# Handle admin's payment URL response
async def handle_admin_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    if context.user_data.get('waiting_for_payment_url'):
        invoice_number = context.user_data['waiting_for_payment_url']
        payment_url = update.message.text
        
        invoice = get_invoice_by_number(invoice_number)
        if not invoice:
            await update.message.reply_text("❌ Invoice not found.")
            return
        
        user_id = invoice[3]  # user_id field
        
        # Send payment URL to user with confirmation button
        user_keyboard = [
            [InlineKeyboardButton("📥 To Pay", url=payment_url)],
            [InlineKeyboardButton("✅ I done payment", callback_data=f"confirm_payment_{invoice_number}")]
        ]
        user_reply_markup = InlineKeyboardMarkup(user_keyboard)
        
        user_message = (
            f"🔄 Please Complete Deposit\n\n"
            f"Invoice: #{invoice_number}\n"
            f"Amount: ${invoice[2]:.2f}\n\n"
            f"Click the button below to make payment:\n"
        )
        
        user_msg = await context.bot.send_message(
            chat_id=user_id,
            text=user_message,
            reply_markup=user_reply_markup
        )
        
        # Update invoice with URL and message IDs
        update_invoice_url(invoice_number, payment_url, update.message.message_id, user_msg.message_id)
        
        # Clear the flag
        context.user_data['waiting_for_payment_url'] = False
        
        await update.message.reply_text(
            f"✅ Payment URL sent to user!\n\n"
            f"Invoice: #{invoice_number}\n"
            f"User: {user_id}\n"
            f"URL: {payment_url}"
        )

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
            elif txid.startswith("INV-"):
                history_text += f"Invoice: #{txid.replace('INV-', '')}\n"
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
    
    # Check if user has pending withdrawal or deposit
    pending_withdrawal = has_pending_withdrawal(user_id)
    pending_deposit = has_pending_deposit(user_id)
    
    if pending_withdrawal:
        withdraw_status = "⏳ Pending withdrawal"
    elif pending_deposit:
        withdraw_status = "⏳ Pending deposit"
    else:
        withdraw_status = "✅ Can withdraw"
    
    balance_text = (
        f"💰 Your Balance:\n\n"
        f"Points: {user_data['points']:.2f} PTS\n"
        f"Equivalent: ${user_data['points'] * POINT_RATE:.2f}\n"
        f"Deposit Balance: ${user_data['deposit_balance']:.2f} USDT\n\n"
        f"Status: {withdraw_status}\n"
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

**Deposit Management:**
/pending_deposits - Show pending deposit invoices
/send_url <invoice_number> <url> - Send payment URL to user

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

async def pending_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access denied.")
        return
    
    invoices = get_pending_deposit_invoices()
    
    if not invoices:
        await update.message.reply_text("✅ No pending deposit invoices.")
        return
    
    for invoice in invoices:
        (invoice_id, invoice_number, user_id, amount, status, payment_url, 
         admin_message_id, user_message_id, created_at, user_points, user_deposit) = invoice
        
        status_text = "⏳ Waiting URL" if status == "pending" else "💰 Waiting Payment"
        
        invoice_text = (
            f"💰 PENDING DEPOSIT #{invoice_number}\n\n"
            f"👤 User ID: {user_id}\n"
            f"📅 Created: {created_at}\n"
            f"💰 Amount: ${amount:.2f}\n"
            f"📊 Status: {status_text}\n\n"
            f"User Balance:\n"
            f"Points: {user_points:.2f} PTS\n"
            f"Deposit: ${user_deposit:.2f}\n\n"
        )
        
        if payment_url:
            invoice_text += f"Payment URL: {payment_url}\n\n"
        
        keyboard = [[InlineKeyboardButton("📤 Send Payment URL", callback_data=f"send_url_{invoice_number}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(invoice_text, reply_markup=reply_markup)

# [Keep all other admin commands from previous code - pending, approve, reject, setpoints, etc.]

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
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("pending_deposits", pending_deposits))
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(points_display|deposit|withdraw|confirm_payment_.*|admin_approve_deposit_.*|admin_reject_deposit_.*)$"))
    application.add_handler(CallbackQueryHandler(admin_send_url, pattern="^send_url_.*$"))
    
    # Add message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_url))
    
    # Start bot
    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
