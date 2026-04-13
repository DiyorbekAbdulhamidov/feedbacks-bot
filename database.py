import sqlite3
from datetime import datetime

# --- YAGONA ULANISH (WAL rejimi — parallel read, tez yozuv) ---
_conn: sqlite3.Connection | None = None

def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect("baza.db", check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")       # parallel read/write
        _conn.execute("PRAGMA synchronous=NORMAL")     # tezroq flush
        _conn.execute("PRAGMA cache_size=-16000")      # 16 MB RAM cache
        _conn.execute("PRAGMA temp_store=MEMORY")      # temp jadvallar RAMda
    return _conn


def create_tables():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            nom      TEXT    NOT NULL,
            dars_kunlari TEXT    NOT NULL,
            vaqt         TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS students (
            user_id  INTEGER PRIMARY KEY,
            ism      TEXT    NOT NULL,
            telefon  TEXT    NOT NULL,
            guruh_id INTEGER REFERENCES groups(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS feedbacks (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            guruh_id INTEGER,
            sana     TEXT    NOT NULL,
            baho     INTEGER NOT NULL,
            matn     TEXT    DEFAULT ''
        );

        -- Tez qidirish uchun indekslar
        CREATE INDEX IF NOT EXISTS idx_students_guruh   ON students(guruh_id);
        CREATE INDEX IF NOT EXISTS idx_feedbacks_guruh  ON feedbacks(guruh_id);
        CREATE INDEX IF NOT EXISTS idx_feedbacks_sana   ON feedbacks(sana);
    """)
    conn.commit()


# ==================== GURUHLAR ====================

def add_group(nom: str, dars_kunlari: str, vaqt: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO groups (nom, dars_kunlari, vaqt) VALUES (?, ?, ?)",
        (nom, dars_kunlari, vaqt)
    )
    conn.commit()


def get_groups() -> list[tuple]:
    """(id, nom) — faqat ro'yxatdan o'tishda tanlash uchun."""
    return get_conn().execute("SELECT id, nom FROM groups").fetchall()


def get_all_groups() -> list[tuple]:
    """(id, nom, dars_kunlari, vaqt) — to'liq ma'lumot."""
    return get_conn().execute(
        "SELECT id, nom, dars_kunlari, vaqt FROM groups"
    ).fetchall()


def delete_group(group_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM feedbacks WHERE guruh_id = ?", (group_id,))
    conn.execute("DELETE FROM students  WHERE guruh_id = ?", (group_id,))
    conn.execute("DELETE FROM groups    WHERE id = ?",       (group_id,))
    conn.commit()


# ==================== O'QUVCHILAR ====================

def get_student(user_id: int) -> tuple | None:
    return get_conn().execute(
        "SELECT * FROM students WHERE user_id = ?", (user_id,)
    ).fetchone()


def add_student(user_id: int, ism: str, telefon: str, guruh_id: int):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO students (user_id, ism, telefon, guruh_id) "
        "VALUES (?, ?, ?, ?)",
        (user_id, ism, telefon, guruh_id)
    )
    conn.commit()


def delete_student(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM students WHERE user_id = ?", (user_id,))
    conn.commit()


def get_students_by_group(guruh_id: int) -> list[tuple]:
    """(user_id,) — broadcast uchun."""
    return get_conn().execute(
        "SELECT user_id FROM students WHERE guruh_id = ?", (guruh_id,)
    ).fetchall()


def get_students_list(guruh_id: int) -> list[tuple]:
    """(ism, telefon) — ko'rsatish uchun."""
    return get_conn().execute(
        "SELECT ism, telefon FROM students WHERE guruh_id = ?", (guruh_id,)
    ).fetchall()


def get_all_students() -> list[tuple]:
    """(user_id,) — hammaga broadcast."""
    return get_conn().execute("SELECT user_id FROM students").fetchall()


def get_student_count() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM students").fetchone()[0]


# ==================== BAHOLASH ====================

def add_feedback(guruh_id: int, baho: int, matn: str):
    conn = get_conn()
    sana = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn.execute(
        "INSERT INTO feedbacks (guruh_id, sana, baho, matn) VALUES (?, ?, ?, ?)",
        (guruh_id, sana, baho, matn)
    )
    conn.commit()


def get_feedback_stats(guruh_id: int) -> dict:
    """Guruh bo'yicha statistika: o'rtacha baho, jami, so'nggi 5 fikr."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*), ROUND(AVG(baho), 1) FROM feedbacks WHERE guruh_id = ?",
        (guruh_id,)
    ).fetchone()
    last = conn.execute(
        "SELECT sana, baho, matn FROM feedbacks WHERE guruh_id = ? "
        "ORDER BY id DESC LIMIT 5",
        (guruh_id,)
    ).fetchall()
    return {
        "count": row[0] or 0,
        "avg":   row[1] or 0.0,
        "last":  last,
    }


def get_global_stats() -> dict:
    """Barcha guruhlar bo'yicha umumiy statistika."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT g.nom,
               COUNT(f.id)        AS jami,
               ROUND(AVG(f.baho), 1) AS ortacha
        FROM groups g
        LEFT JOIN feedbacks f ON f.guruh_id = g.id
        GROUP BY g.id
        ORDER BY ortacha DESC NULLS LAST
    """).fetchall()
    total_students = get_student_count()
    return {"groups": rows, "total_students": total_students}