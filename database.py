import sqlite3
from datetime import datetime

def create_tables():
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS students (user_id INTEGER PRIMARY KEY, ism TEXT, telefon TEXT, guruh_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT, dars_kunlari TEXT, vaqt TEXT)''')
    # YANGA: baho INTEGER qo'shildi
    cursor.execute('''CREATE TABLE IF NOT EXISTS feedbacks (id INTEGER PRIMARY KEY AUTOINCREMENT, guruh_id INTEGER, sana TEXT, baho INTEGER, matn TEXT)''')
    conn.commit()
    conn.close()

def get_student(user_id):
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE user_id = ?", (user_id,))
    student = cursor.fetchone()
    conn.close()
    return student

def add_student(user_id, ism, telefon, guruh_id):
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO students (user_id, ism, telefon, guruh_id) VALUES (?, ?, ?, ?)", (user_id, ism, telefon, guruh_id))
    conn.commit()
    conn.close()

def delete_student(user_id):
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM students WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_groups():
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, nom FROM groups")
    groups = cursor.fetchall()
    conn.close()
    return groups

def add_group(nom, dars_kunlari, vaqt):
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO groups (nom, dars_kunlari, vaqt) VALUES (?, ?, ?)", (nom, dars_kunlari, vaqt))
    conn.commit()
    conn.close()

def get_all_groups():
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, nom, dars_kunlari, vaqt FROM groups")
    groups = cursor.fetchall()
    conn.close()
    return groups

def delete_group(group_id):
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    cursor.execute("DELETE FROM students WHERE guruh_id = ?", (group_id,))
    conn.commit()
    conn.close()

def get_students_by_group(guruh_id):
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM students WHERE guruh_id = ?", (guruh_id,))
    students = cursor.fetchall()
    conn.close()
    return students

def get_all_students():
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM students")
    students = cursor.fetchall()
    conn.close()
    return students

# YANGA: baho parametri qo'shildi
def add_feedback(guruh_id, baho, matn):
    conn = sqlite3.connect("baza.db")
    cursor = conn.cursor()
    sana = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute("INSERT INTO feedbacks (guruh_id, sana, baho, matn) VALUES (?, ?, ?, ?)", (guruh_id, sana, baho, matn))
    conn.commit()
    conn.close()