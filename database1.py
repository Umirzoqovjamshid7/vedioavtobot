import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("videos.db")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                file_unique_id TEXT NOT NULL UNIQUE,
                caption TEXT,
                sent INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS target_chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                approved INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                approved_at DATETIME
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_deliveries (
                video_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (video_id, chat_id),
                FOREIGN KEY (video_id) REFERENCES videos(id),
                FOREIGN KEY (chat_id) REFERENCES target_chats(chat_id)
            )
        """)


def add_video(file_id, file_unique_id, caption=None):
    try:
        with connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO videos
                (file_id, file_unique_id, caption)
                VALUES (?, ?, ?)
                """,
                (file_id, file_unique_id, caption),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_next_videos(limit=1):
    with connect() as conn:
        return conn.execute(
            """
            SELECT *
            FROM videos
            WHERE sent = 0
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_next_videos_for_chat(chat_id, limit=10):
    with connect() as conn:
        return conn.execute(
            """
            SELECT v.*
            FROM videos AS v
            WHERE NOT EXISTS (
                SELECT 1
                FROM video_deliveries AS d
                WHERE d.video_id = v.id AND d.chat_id = ?
            )
            ORDER BY v.id ASC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()


def mark_delivered(video_id, chat_id):
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO video_deliveries (video_id, chat_id)
            VALUES (?, ?)
            """,
            (video_id, chat_id),
        )


def register_chat(chat_id, title=None):
    with connect() as conn:
        row = conn.execute(
            "SELECT approved FROM target_chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if row:
            return "approved" if row[0] else "pending"
        conn.execute(
            "INSERT INTO target_chats (chat_id, title) VALUES (?, ?)",
            (chat_id, title),
        )
        return "new"


def approve_chat(chat_id):
    with connect() as conn:
        conn.execute(
            """
            UPDATE target_chats
            SET approved = 1, approved_at = CURRENT_TIMESTAMP
            WHERE chat_id = ?
            """,
            (chat_id,),
        )


def reject_chat(chat_id):
    with connect() as conn:
        conn.execute(
            "DELETE FROM target_chats WHERE chat_id = ? AND approved = 0",
            (chat_id,),
        )


def get_approved_chats():
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM target_chats WHERE approved = 1 ORDER BY created_at ASC"
        ).fetchall()


def is_chat_approved(chat_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT approved FROM target_chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return bool(row and row[0])


def mark_sent(video_id):
    with connect() as conn:
        conn.execute(
            "UPDATE videos SET sent = 1 WHERE id = ?",
            (video_id,),
        )


def get_stats():
    with connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM videos"
        ).fetchone()[0]

        sent = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE sent = 1"
        ).fetchone()[0]

        waiting = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE sent = 0"
        ).fetchone()[0]

    return total, sent, waiting


def reset_queue():
    with connect() as conn:
        conn.execute("UPDATE videos SET sent = 0")
