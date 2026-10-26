# -*- coding: utf-8 -*-
"""Поиск по выгруженным постам и комментариям.

Поддерживает поиск по:
  - тексту (без учёта регистра, работает и для кириллицы);
  - автору (имя пользователя);
  - диапазону дат;
  - конкретному чату (или по всем чатам).

Регистронезависимый поиск по кириллице реализован на стороне Python
(встроенный LOWER()/LIKE в SQLite не обрабатывает не-ASCII корректно).
Для скорости сначала выбираем кандидатов по chat_id/дате, затем фильтруем.
"""
import datetime


def _date_to_day_start_ms(day_str):
    """'2026-01-01' -> unix ms начала дня. Raised ValueError если неверный формат."""
    if not day_str:
        return None
    try:
        dt = datetime.datetime.strptime(day_str.strip(), "%Y-%m-%d")
    except ValueError:
        raise ValueError("Дата должна быть в формате ГГГГ-ММ-ДД, например 2026-01-01")
    return int(dt.timestamp() * 1000)


def _day_end_ms(day_str):
    dt = datetime.datetime.strptime(day_str.strip(), "%Y-%m-%d")
    end = dt.replace(hour=23, minute=59, second=59, microsecond=0)
    return int(end.timestamp() * 1000)


def _row_matches(row, query_lower=None, author_lower=None):
    """Проверить строку на совпадение с текстом и автором (регистронезависимо)."""
    if query_lower:
        text = (row["text"] or "").lower()
        mid = (row["mid"] or "").lower()
        if query_lower not in text and query_lower not in mid:
            return False
    if author_lower:
        name = (row["sender_name"] or "").lower()
        if author_lower not in name:
            return False
    return True


class Searcher:
    def __init__(self, store):
        self.store = store

    def _candidates(self, table, chat_id, date_from, date_to, limit):
        """Выбрать строки по чату и дате (без фильтра по тексту/автору)."""
        sql = "SELECT * FROM %s WHERE 1=1" % table
        params = []
        if chat_id is not None:
            sql += " AND chat_id=?"
            params.append(chat_id)
        f = _date_to_day_start_ms(date_from) if date_from else None
        t = _day_end_ms(date_to) if date_to else None
        if f is not None:
            sql += " AND timestamp >= ?"
            params.append(f)
        if t is not None:
            sql += " AND timestamp <= ?"
            params.append(t)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(max(limit * 10, limit + 100))
        return self.store.conn.execute(sql, params).fetchall()

    def search_posts(self, query=None, chat_id=None, author=None,
                     date_from=None, date_to=None, limit=200):
        """Искать посты. Возвращает список sqlite3.Row."""
        rows = self._candidates("posts", chat_id, date_from, date_to, limit)
        query_lower = query.lower() if query else None
        author_lower = author.lower() if author else None
        out = [r for r in rows if _row_matches(r, query_lower, author_lower)]
        return out[:limit]

    def search_comments(self, query=None, chat_id=None, author=None,
                        date_from=None, date_to=None, limit=200):
        """Искать комментарии. Возвращает список sqlite3.Row."""
        rows = self._candidates("comments", chat_id, date_from, date_to, limit)
        query_lower = query.lower() if query else None
        author_lower = author.lower() if author else None
        out = [r for r in rows if _row_matches(r, query_lower, author_lower)]
        return out[:limit]

    def search(self, query=None, chat_id=None, author=None,
               date_from=None, date_to=None, limit=100):
        """Искать и по постам, и по комментариям. Возвращает dict."""
        return {
            "posts": self.search_posts(query, chat_id, author, date_from, date_to, limit),
            "comments": self.search_comments(query, chat_id, author, date_from, date_to, limit),
        }