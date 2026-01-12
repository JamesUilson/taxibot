import sqlite3

conn = sqlite3.connect("userbot.db", check_same_thread=False)
cursor = conn.cursor()

# Qabul qiluvchilar
cursor.execute("""
CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY
)
""")

# Kalit so‘zlar
cursor.execute("""
CREATE TABLE IF NOT EXISTS keywords (
    category TEXT,
    word TEXT
)
""")

# Duplicate xabarlar
cursor.execute("""
CREATE TABLE IF NOT EXISTS recent_messages (
    sender_id INTEGER,
    text TEXT
)
""")

conn.commit()
