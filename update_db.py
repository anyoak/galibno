import sqlite3

def update_database_schema():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Check if private_key column exists in users table
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'private_key' not in columns:
        print("Adding private_key column to users table...")
        cursor.execute("ALTER TABLE users ADD COLUMN private_key TEXT")
    
    # Check if admin_withdrawals table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_withdrawals'")
    if not cursor.fetchone():
        print("Creating admin_withdrawals table...")
        cursor.execute('''
        CREATE TABLE admin_withdrawals (
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
    print("Database schema updated successfully!")

if __name__ == '__main__':
    update_database_schema()
