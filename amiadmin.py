from flask import Flask, render_template, request, jsonify
import sqlite3
from datetime import datetime
import requests

app = Flask(__name__)

# Function to get data from database
def get_db_data(query, params=()):
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(query, params)
    data = cursor.fetchall()
    conn.close()
    return data

def execute_db(query, params=()):
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    conn.close()

@app.route('/')
def dashboard():
    # Total users
    total_users = get_db_data("SELECT COUNT(*) FROM users")[0][0]
    
    # Active subscriptions
    active_users = get_db_data("SELECT COUNT(*) FROM users WHERE subscription_end > datetime('now')")[0][0]
    
    # Total revenue
    total_revenue = get_db_data("SELECT SUM(amount) FROM payments WHERE status = 'completed'")[0][0] or 0
    
    # Today's revenue
    today_revenue = get_db_data("SELECT SUM(amount) FROM payments WHERE status = 'completed' AND date(created_at) = date('now')")[0][0] or 0
    
    # Total withdrawals
    total_withdrawals = get_db_data("SELECT SUM(amount) FROM admin_withdrawals WHERE status = 'completed'")[0][0] or 0
    
    # Telegram accounts count
    telegram_accounts = get_db_data("SELECT COUNT(*) FROM telegram_accounts WHERE is_active = TRUE")[0][0]
    
    return render_template('dashboard.html', 
                         total_users=total_users,
                         active_users=active_users,
                         total_revenue=total_revenue,
                         today_revenue=today_revenue,
                         total_withdrawals=total_withdrawals,
                         telegram_accounts=telegram_accounts)

@app.route('/users')
def users():
    users_data = get_db_data("""
        SELECT user_id, tron_address, subscription_end, daily_checks, total_checks, max_checks, created_at 
        FROM users 
        ORDER BY created_at DESC
    """)
    return render_template('users.html', users=users_data)

@app.route('/payments')
def payments():
    payments_data = get_db_data("""
        SELECT user_id, tron_address, amount, status, created_at 
        FROM payments 
        ORDER BY created_at DESC
    """)
    return render_template('payments.html', payments=payments_data)

@app.route('/accounts')
def accounts():
    accounts_data = get_db_data("""
        SELECT id, phone_number, api_id, api_hash, is_active, last_used, use_count 
        FROM telegram_accounts
    """)
    return render_template('accounts.html', accounts=accounts_data)

@app.route('/withdrawals')
def withdrawals():
    withdrawals_data = get_db_data("""
        SELECT admin_id, tron_address, amount, status, created_at 
        FROM admin_withdrawals 
        ORDER BY created_at DESC
    """)
    return render_template('withdrawals.html', withdrawals=withdrawals_data)

@app.route('/add_account', methods=['POST'])
def add_account():
    phone = request.form.get('phone')
    api_id = request.form.get('api_id')
    api_hash = request.form.get('api_hash')
    
    # Create sessions directory if it doesn't exist
    import os
    os.makedirs("sessions", exist_ok=True)
    session_file = f"sessions/{phone}"
    
    execute_db(
        "INSERT INTO telegram_accounts (phone_number, api_id, api_hash, session_file) VALUES (?, ?, ?, ?)",
        (phone, api_id, api_hash, session_file)
    )
    
    return jsonify({'status': 'success', 'message': 'Account added successfully'})

@app.route('/toggle_account/<int:account_id>')
def toggle_account(account_id):
    current_status = get_db_data("SELECT is_active FROM telegram_accounts WHERE id = ?", (account_id,))[0][0]
    new_status = not current_status
    
    execute_db(
        "UPDATE telegram_accounts SET is_active = ? WHERE id = ?",
        (new_status, account_id)
    )
    
    return jsonify({'status': 'success', 'message': f'Account {"activated" if new_status else "deactivated"}'})

@app.route('/withdraw', methods=['POST'])
def withdraw():
    address = request.form.get('address')
    
    # Get all user addresses
    addresses = get_db_data("SELECT tron_address, private_key FROM users WHERE tron_address IS NOT NULL")
    
    total_usdt = 0
    total_trx = 0
    
    for user_address, private_key in addresses:
        # Get balances (implementation depends on your TRON setup)
        trx_balance, usdt_balance = get_total_balance(user_address)
        
        if usdt_balance > 0:
            # Send USDT (implementation depends on your TRON setup)
            tx_hash = send_usdt(private_key, address, usdt_balance)
            if tx_hash:
                total_usdt += usdt_balance
        
        if trx_balance > 1:  # Leave 1 TRX for fees
            amount_to_send = trx_balance - 1
            tx_hash = send_trx(private_key, address, amount_to_send)
            if tx_hash:
                total_trx += amount_to_send
    
    # Record withdrawal
    execute_db(
        "INSERT INTO admin_withdrawals (admin_id, tron_address, amount, status) VALUES (?, ?, ?, ?)",
        (1, address, total_usdt, 'completed')
    )
    
    return jsonify({
        'status': 'success', 
        'message': f'Withdrawal completed: {total_usdt} USDT, {total_trx} TRX'
    })

@app.route('/add_subscription', methods=['POST'])
def add_subscription():
    user_id = request.form.get('user_id')
    days = int(request.form.get('days'))
    
    # Get current subscription end
    current_end = get_db_data("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    
    if current_end and current_end[0]:
        from datetime import datetime, timedelta
        new_end = datetime.strptime(current_end[0], '%Y-%m-%d %H:%M:%S') + timedelta(days=days)
    else:
        new_end = datetime.now() + timedelta(days=days)
    
    execute_db(
        "UPDATE users SET subscription_end = ? WHERE user_id = ?",
        (new_end.strftime('%Y-%m-%d %H:%M:%S'), user_id)
    )
    
    return jsonify({'status': 'success', 'message': f'Subscription added for {days} days'})

@app.route('/remove_subscription/<int:user_id>')
def remove_subscription(user_id):
    execute_db(
        "UPDATE users SET subscription_end = NULL WHERE user_id = ?",
        (user_id,)
    )
    
    return jsonify({'status': 'success', 'message': 'Subscription removed'})

@app.route('/export_keys')
def export_keys():
    keys = get_db_data("SELECT user_id, tron_address, private_key FROM users WHERE private_key IS NOT NULL")
    
    keys_content = "User ID,Address,Private Key\n"
    for key in keys:
        keys_content += f"{key[0]},{key[1]},{key[2]}\n"
    
    return jsonify({'status': 'success', 'data': keys_content})

# Helper functions (these should be implemented based on your TRON setup)
def get_total_balance(address):
    # Implement based on your TRON setup
    return 0, 0

def send_usdt(private_key, to_address, amount):
    # Implement based on your TRON setup
    return "tx_hash"

def send_trx(private_key, to_address, amount):
    # Implement based on your TRON setup
    return "tx_hash"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)