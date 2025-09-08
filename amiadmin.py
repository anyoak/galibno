from flask import Flask, render_template, request, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)

# Function to get data from database
def get_db_data(query, params=()):
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(query, params)
    data = cursor.fetchall()
    conn.close()
    return data

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
    
    return render_template('dashboard.html', 
                         total_users=total_users,
                         active_users=active_users,
                         total_revenue=total_revenue,
                         today_revenue=today_revenue)

@app.route('/users')
def users():
    users_data = get_db_data("SELECT user_id, tron_address, subscription_end, daily_checks, total_checks, created_at FROM users ORDER BY created_at DESC")
    return render_template('users.html', users=users_data)

@app.route('/payments')
def payments():
    payments_data = get_db_data("SELECT user_id, tron_address, amount, status, created_at FROM payments ORDER BY created_at DESC")
    return render_template('payments.html', payments=payments_data)

@app.route('/accounts')
def accounts():
    accounts_data = get_db_data("SELECT id, phone_number, api_id, is_active, last_used, use_count FROM telegram_accounts")
    return render_template('accounts.html', accounts=accounts_data)

@app.route('/add_account', methods=['POST'])
def add_account():
    phone = request.form.get('phone')
    api_id = request.form.get('api_id')
    api_hash = request.form.get('api_hash')
    
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO telegram_accounts (phone_number, api_id, api_hash, session_file) VALUES (?, ?, ?, ?)",
                  (phone, api_id, api_hash, f"sessions/{phone}"))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'success', 'message': 'Account added successfully'})

@app.route('/withdraw', methods=['POST'])
def withdraw():
    amount = request.form.get('amount')
    address = request.form.get('address')
    
    # Add withdrawal logic here
    # Create transaction on TRON network
    
    return jsonify({'status': 'success', 'message': 'Withdrawal processed successfully'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)