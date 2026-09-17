import sqlite3
from pathlib import Path
import config

DB_FILE = config.BASE_DIR / "imagegen_bot.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        model TEXT DEFAULT 'flux',
        ratio TEXT DEFAULT '1:1',
        joined TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # History table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        prompt TEXT,
        model TEXT,
        width INTEGER,
        height INTEGER,
        seed INTEGER,
        size INTEGER,
        status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)
    
    conn.commit()
    conn.close()

def add_or_update_user(user_id: int, username: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO users (id, username, last_seen)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(id) DO UPDATE SET 
        username = excluded.username,
        last_seen = CURRENT_TIMESTAMP
    """, (user_id, username or "Anonymous"))
    conn.commit()
    conn.close()

def get_user_settings(user_id: int) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT model, ratio FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "model": row["model"] or config.DEFAULT_MODEL,
            "ratio": row["ratio"] or config.DEFAULT_RATIO
        }
    return {
        "model": config.DEFAULT_MODEL,
        "ratio": config.DEFAULT_RATIO
    }

def set_user_model(user_id: int, model: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET model = ? WHERE id = ?", (model, user_id))
    conn.commit()
    conn.close()

def set_user_ratio(user_id: int, ratio: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET ratio = ? WHERE id = ?", (ratio, user_id))
    conn.commit()
    conn.close()

def log_generation(user_id: int, prompt: str, model: str, width: int, height: int, seed: int, size: int, status: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO history (user_id, prompt, model, width, height, seed, size, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (user_id, prompt, model, width, height, seed, size, status))
    conn.commit()
    conn.close()

def get_user_history(user_id: int, limit: int = 5):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT prompt, model, width, height, seed, created_at, status 
    FROM history
    WHERE user_id = ?
    ORDER BY id DESC LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_global_stats() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM history WHERE status = 'success'")
    total_success = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM history WHERE status = 'failed'")
    total_failed = cursor.fetchone()[0]
    
    conn.close()
    return {
        "total_users": total_users,
        "total_success": total_success,
        "total_failed": total_failed
    }

# Initialize on import
init_db()
