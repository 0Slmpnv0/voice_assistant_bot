import sqlite3
import config


def init():
    sql_prompts = '''CREATE TABLE IF NOT EXISTS prompts(
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    role TEXT,
    text TEXT
    );'''

    sql_users = '''CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    gpt_tokens INTEGER,
    tts_characters INTEGER,
    stt_blocks INTEGER
    )'''

    conn = sqlite3.connect('db.sqlite3')
    cur = conn.cursor()
    cur.execute(sql_prompts)
    cur.execute(sql_users)
    conn.commit()
    conn.close()


def insert_into_prompts(user_id, role, text):
    sql = '''INSERT INTO prompts(user_id, role, text) VALUES (?, ?, ?)'''
    conn = sqlite3.connect('db.sqlite3')
    cur = conn.cursor()
    cur.execute(sql, (user_id, role, text))


def insert_into_users(
        user_id: int,
        tokens_remaining: int = config.MAX_USER_TOKENS,
        tts_characters: int = config.MAX_TTS_CHARS,
        stt_blocks: int = config.MAX_STT_BLOCKS):

    sql = '''INSERT INTO users(user_id, tokens_remaining, tts_characters, stt_blocks) VALUES (?, ?, ?, ?)'''
    conn = sqlite3.connect('db.sqlite3')
    cur = conn.cursor()
    cur.execute(sql, (user_id, tokens_remaining, tts_characters, stt_blocks))
    conn.commit()
    conn.close()


def update_user_limits(user_id, column, value):
    sql = f'''UPDATE users SET {column} = ? WHERE user_id = ?'''
    conn = sqlite3.connect('db.sqlite3')
    cur = conn.cursor()
    cur.execute(sql, (value, user_id))
    conn.commit()
    conn.close()


def get_user_context(user_id):
    sql = '''SELECT * FROM prompts WHERE user_id = ?'''
    conn = sqlite3.connect('db.sqlite3')
    cur = conn.cursor()
    conn.row_factory = sqlite3.Row

    res = []
    for i in cur.execute(sql, (user_id,)):
        res.append(dict(i))

    return res


def get_user_limits(user_id):
    sql = '''SELECT gpt_tokens, tts_characters, stt_blocks FROM users WHERE user_id = ?'''
    conn = sqlite3.connect('db.sqlite3')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    res = []

    for i in cur.execute(sql, (user_id,)):
        res.append(dict(i))

    return res
