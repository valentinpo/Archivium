# -*- coding: utf-8 -*-
"""Статистика по контенту чата/канала для отчёта и ведения каналов.

Считает по сохранённым в БД данным:
  - общее число постов и комментариев;
  - активность по дням (сколько постов в день);
  - топ авторов по числу постов и комментариев;
  - самые частые слова в тексте постов (для понимания ключевых тем);
  - распределение типов вложений.
Возвращает обычные структуры (списки кортежей), которые потом пишутся в Excel.
"""
import re
import sqlite3
from collections import Counter

# Стоп-слова русского и английского (служебные, не несущие тему)
STOPWORDS = set(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
    только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если
    уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей
    может они тут где есть надо ней для мы тебя их чем бывает раз самый себе
    the a an and of to in for on with as at by from or is are was were be been it that this
    these those i you he she we they my your his her our their not no do does did have has had
    would will can could should may might just very about more than so then if but
    """.split()
)

# Если текст короче этого, слова не считаем (неинформативно)
MIN_WORD_LEN = 3
TOP_WORDS = 30


def strip_text(text):
    """Очистить текст: нижний регистр, вытащить слова."""
    if not text:
        return ""
    return re.sub(r"[^а-яёa-z0-9\s-]", " ", text.lower())


def _iter_values(cur):
    for row in cur:
        yield row[0]


def _words_from_texts(texts):
    """Подсчитать частоту слов по коллекции текстов (генератор)."""
    counter = Counter()
    for t in texts:
        for w in strip_text(t).split():
            w = w.strip("-")
            if len(w) >= MIN_WORD_LEN and w not in STOPWORDS:
                counter[w] += 1
    return counter


class StatsBuilder:
    def __init__(self, store):
        self.store = store

    def build(self, chat_id):
        """Полная статистика по чату. Возвращает dict с данными для отчёта."""
        conn = self.store.conn

        # --- базовые счётчики ---
        total_posts = self.store.count_posts(chat_id)
        total_comments = self.store.count_comments(chat_id)
        first_ts, last_ts = self._post_bounds(conn, chat_id)

        # --- активность по дням ---
        by_day = self._posts_per_day(conn, chat_id)

        # --- топ авторов постов ---
        top_post_authors = self._top_authors_posts(conn, chat_id)

        # --- топ авторов комментариев ---
        top_comment_authors = self._top_authors_comments(conn, chat_id)

        # --- слова в постах ---
        words = self._words_in_posts(conn, chat_id)

        # --- типы вложений ---
        attachment_types = self._attachment_types(conn, chat_id)

        return {
            "total_posts": total_posts,
            "total_comments": total_comments,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "days": by_day,               # [(дата, count)]
            "top_post_authors": top_post_authors,      # [(name, count)]
            "top_comment_authors": top_comment_authors,  # [(name, count)]
            "top_words": words,           # [("слово", count)]
            "attachments": attachment_types,  # [("тип", count)]
            "avg_per_day": self._avg(total_posts, by_day),
        }

    # ------------------------------------------------------------------
    def _post_bounds(self, conn, chat_id):
        cur = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM posts WHERE chat_id=?",
            (chat_id,),
        )
        row = cur.fetchone()
        return row[0], row[1]

    def _posts_per_day(self, conn, chat_id):
        cur = conn.execute(
            """
            SELECT date(timestamp/1000, 'unixepoch') as d, COUNT(*)
            FROM posts WHERE chat_id=?
            GROUP BY d ORDER BY d
            """,
            (chat_id,),
        )
        return [(d, c) for d, c in cur.fetchall()]

    def _top_authors_posts(self, conn, chat_id):
        cur = conn.execute(
            """
            SELECT COALESCE(sender_name, 'unknown'), COUNT(*) as cnt
            FROM posts WHERE chat_id=?
            GROUP BY sender_name ORDER BY cnt DESC LIMIT 20
            """,
            (chat_id,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]

    def _top_authors_comments(self, conn, chat_id):
        cur = conn.execute(
            """
            SELECT COALESCE(sender_name, 'unknown'), COUNT(*) as cnt
            FROM comments WHERE chat_id=?
            GROUP BY sender_name ORDER BY cnt DESC LIMIT 20
            """,
            (chat_id,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]

    def _words_in_posts(self, conn, chat_id):
        cur = conn.execute(
            "SELECT text FROM posts WHERE chat_id=? AND text IS NOT NULL AND text != ''",
            (chat_id,),
        )
        counter = _words_from_texts(_iter_values(cur))
        return counter.most_common(TOP_WORDS)

    def _attachment_types(self, conn, chat_id):
        import json
        cur = conn.execute(
            "SELECT attachments_json FROM posts WHERE chat_id=? AND attachments_json IS NOT NULL",
            (chat_id,),
        )
        counter = Counter()
        for raw in _iter_values(cur):
            try:
                atts = json.loads(raw)
            except (TypeError, ValueError):
                continue
            for a in atts:
                t = a.get("type")
                if t:
                    counter[t] += 1
        return counter.most_common()

    @staticmethod
    def _avg(total, by_day):
        if total == 0:
            return 0.0
        return round(total / max(len(by_day), 1), 2)