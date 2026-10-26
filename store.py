# -*- coding: utf-8 -*-
"""Хранилище выгруженных постов: SQLite + экспорт в JSON/CSV.

Один "пост" идентифицируется тройкой (chat_id, mid). Если пост уже был
выгружен ранее, повторная выгрузка обновит его, а не продублирует.

Потокобезопасность: соединение SQLite создаётся отдельно для каждого потока
(thread-local), потому что в GUI бот работает в фоновом потоке, а часть
вызовов (лог, автообновление) приходит из главного потока. SQLite запрещает
использовать одно соединение из разных потоков — у нас каждое соединение
принадлежит своему потоку, а данные защищены файловой блокировкой SQLite.
"""
import csv
import json
import os
import sqlite3
import threading
import time

from config import DATA_DIR, DB_FILE


def _ts_now_ms():
    return int(time.time() * 1000)


class PostStore:
    def __init__(self, db_path=None, data_dir=None):
        self.data_dir = data_dir or DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = db_path or os.path.join(self.data_dir, DB_FILE)
        # thread-local: отдельное соединение для каждого потока
        self._local = threading.local()
        # убедимся, что схема создана (соединение текущего потока)
        self.conn

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # схема создаётся один раз (CREATE TABLE IF NOT EXISTS идемпотентен)
        self._init_schema_with(conn)
        return conn

    def _init_schema_with(self, conn):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT,          -- 'chat' | 'channel'
                title TEXT,
                added_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS posts (
                chat_id INTEGER NOT NULL,
                mid TEXT NOT NULL,
                seq INTEGER,
                sender_id INTEGER,
                sender_name TEXT,
                timestamp INTEGER,       -- unix ms
                text TEXT,
                attachments_json TEXT,
                url TEXT,
                comments INTEGER DEFAULT 0,
                exported_at INTEGER,
                PRIMARY KEY (chat_id, mid)
            );
            CREATE INDEX IF NOT EXISTS idx_posts_chat_ts ON posts(chat_id, timestamp);
            CREATE TABLE IF NOT EXISTS comments (
                chat_id INTEGER NOT NULL,
                mid TEXT NOT NULL,           -- id поста
                comment_mid TEXT NOT NULL,   -- id комментария
                seq INTEGER,
                sender_id INTEGER,
                sender_name TEXT,
                timestamp INTEGER,           -- unix ms
                text TEXT,
                exported_at INTEGER,
                PRIMARY KEY (chat_id, mid, comment_mid)
            );
            CREATE INDEX IF NOT EXISTS idx_comments_mid ON comments(mid);
            """
        )
        conn.commit()

    @property
    def conn(self):
        """Соединение для текущего потока (создаётся при первом обращении)."""
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._connect()
            self._local.conn = c
        return c

    # ------------------------------------------------------------------
    # Чаты / каналы
    # ------------------------------------------------------------------
    def upsert_chat(self, chat_id, chat_type=None, title=None):
        self.conn.execute(
            """
            INSERT INTO chats (chat_id, chat_type, title, added_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type = COALESCE(EXCLUDED.chat_type, chats.chat_type),
                title = COALESCE(EXCLUDED.title, chats.title)
            """,
            (chat_id, chat_type, title, _ts_now_ms()),
        )
        self.conn.commit()

    def list_chats(self):
        cur = self.conn.execute(
            "SELECT * FROM chats ORDER BY added_at DESC"
        )
        return cur.fetchall()

    def list_all_chats(self):
        """Список чатов, объединяя таблицу chats и чаты из постов.

        Покрывает случай, когда пост сохранён до регистрации самого чата
        (например, при событии message_created). Возвращает sqlite3.Row
        с колонками таблицы chats.
        """
        cur = self.conn.execute(
            """
            SELECT ids.chat_id, c.chat_type, c.title,
                   COALESCE(c.added_at, 0) AS added_at
            FROM (
                SELECT chat_id FROM chats
                UNION
                SELECT DISTINCT chat_id FROM posts
            ) ids
            LEFT JOIN chats c ON c.chat_id = ids.chat_id
            ORDER BY added_at DESC
            """
        )
        return cur.fetchall()

    def get_chat(self, chat_id):
        cur = self.conn.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,))
        return cur.fetchone()

    # ------------------------------------------------------------------
    # Посты
    # ------------------------------------------------------------------
    def upsert_post(self, post):
        """post: dict с ключами chat_id, mid, seq, sender_id, sender_name,
        timestamp, text, attachments, url, comments"""
        self.conn.execute(
            """
            INSERT INTO posts
                (chat_id, mid, seq, sender_id, sender_name, timestamp,
                 text, attachments_json, url, comments, exported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, mid) DO UPDATE SET
                seq = EXCLUDED.seq,
                text = EXCLUDED.text,
                attachments_json = EXCLUDED.attachments_json,
                url = EXCLUDED.url,
                comments = EXCLUDED.comments,
                exported_at = EXCLUDED.exported_at
            """,
            (
                post.get("chat_id"),
                post.get("mid"),
                post.get("seq"),
                post.get("sender_id"),
                post.get("sender_name"),
                post.get("timestamp"),
                post.get("text"),
                post.get("attachments_json"),
                post.get("url"),
                post.get("comments", 0),
                _ts_now_ms(),
            ),
        )
        self.conn.commit()

    def post_exists(self, chat_id, mid):
        cur = self.conn.execute(
            "SELECT 1 FROM posts WHERE chat_id=? AND mid=?", (chat_id, mid)
        )
        return cur.fetchone() is not None

    def count_posts(self, chat_id=None):
        if chat_id is not None:
            cur = self.conn.execute(
                "SELECT COUNT(*) c FROM posts WHERE chat_id=?", (chat_id,)
            )
        else:
            cur = self.conn.execute("SELECT COUNT(*) c FROM posts")
        return cur.fetchone()["c"]

    # ------------------------------------------------------------------
    # Комментарии
    # ------------------------------------------------------------------
    def upsert_comment(self, comment):
        """comment: dict с ключами chat_id, mid, comment_mid, seq,
        sender_id, sender_name, timestamp, text"""
        self.conn.execute(
            """
            INSERT INTO comments
                (chat_id, mid, comment_mid, seq, sender_id, sender_name,
                 timestamp, text, exported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, mid, comment_mid) DO UPDATE SET
                seq = EXCLUDED.seq,
                text = EXCLUDED.text,
                exported_at = EXCLUDED.exported_at
            """,
            (
                comment.get("chat_id"),
                comment.get("mid"),
                comment.get("comment_mid"),
                comment.get("seq"),
                comment.get("sender_id"),
                comment.get("sender_name"),
                comment.get("timestamp"),
                comment.get("text"),
                _ts_now_ms(),
            ),
        )
        self.conn.commit()

    def comment_exists(self, chat_id, mid, comment_mid):
        cur = self.conn.execute(
            "SELECT 1 FROM comments WHERE chat_id=? AND mid=? AND comment_mid=?",
            (chat_id, mid, comment_mid),
        )
        return cur.fetchone() is not None

    def count_comments(self, chat_id=None):
        if chat_id is not None:
            cur = self.conn.execute(
                "SELECT COUNT(*) c FROM comments WHERE chat_id=?", (chat_id,)
            )
        else:
            cur = self.conn.execute("SELECT COUNT(*) c FROM comments")
        return cur.fetchone()["c"]

    # ------------------------------------------------------------------
    # Экспорт
    # ------------------------------------------------------------------
    def export_chat(self, chat_id, fmt="json"):
        """Экспортировать все посты чата в JSON или CSV. Возвращает путь к файлу."""
        rows = self.conn.execute(
            "SELECT * FROM posts WHERE chat_id=? ORDER BY timestamp ASC",
            (chat_id,),
        ).fetchall()

        chat = self.get_chat(chat_id)
        title = (chat["title"] if chat else None) or str(chat_id)
        safe_title = "".join(c for c in title if c.isalnum() or c in " _-") or str(chat_id)

        if fmt == "csv":
            path = os.path.join(self.data_dir, "%s_%s_posts.csv" % (chat_id, safe_title))
            self._write_csv(path, rows)
        else:
            path = os.path.join(self.data_dir, "%s_%s_posts.json" % (chat_id, safe_title))
            self._write_json(path, rows)
        return path

    def export_comments(self, chat_id, fmt="json"):
        """Экспортировать комментарии чата в JSON или CSV. Возвращает путь к файлу."""
        rows = self.conn.execute(
            "SELECT * FROM comments WHERE chat_id=? ORDER BY timestamp ASC",
            (chat_id,),
        ).fetchall()

        chat = self.get_chat(chat_id)
        title = (chat["title"] if chat else None) or str(chat_id)
        safe_title = "".join(c for c in title if c.isalnum() or c in " _-") or str(chat_id)

        if fmt == "csv":
            path = os.path.join(self.data_dir, "%s_%s_comments.csv" % (chat_id, safe_title))
            self._write_csv(path, rows, cols=[
                "chat_id", "mid", "comment_mid", "seq", "sender_id",
                "sender_name", "timestamp", "text",
            ])
        else:
            path = os.path.join(self.data_dir, "%s_%s_comments.json" % (chat_id, safe_title))
            self._write_json(path, rows)
        return path

    def _write_json(self, path, rows):
        data = []
        for r in rows:
            rec = dict(r)
            # при необходимости раскрыть вложения
            data.append(rec)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _write_csv(self, path, rows, cols=None):
        if cols is None:
            cols = [
                "chat_id", "mid", "seq", "sender_id", "sender_name",
                "timestamp", "text", "attachments_json", "url", "comments",
            ]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(dict(r))

    def close(self):
        """Закрыть соединения всех потоков (для этого хранилища)."""
        seen = set()
        # закрываем соединение текущего потока
        c = getattr(self._local, "conn", None)
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
            self._local.conn = None
        # у других потоков закрыть их локальные соединения мы не можем напрямую,
        # но они закроются по завершении потока / при сборке мусора.