# -*- coding: utf-8 -*-
"""Сборка итогового Excel-отчёта по чату/каналу.

Использует наш минимальный XlsxWriter (без openpyxl). Листы:
  1. Обзор        — сводные цифры
  2. Посты        — все посты
  3. Комментарии  — все комментарии
  4. Активность   — посты по дням
  5. Авторы       — топ авторов постов и комментариев
  6. Слова        — самые частые слова в постах
  7. Вложения     — распределение типов вложений
"""
import datetime
import os

from xlsx_writer import XlsxWriter


def _human_date(ts_ms):
    """unix ms -> 'YYYY-MM-DD HH:MM' (локальное время) или ''."""
    if not ts_ms:
        return ""
    try:
        dt = datetime.datetime.fromtimestamp(ts_ms / 1000)
    except (ValueError, OverflowError, OSError):
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


def _human_day(ts_ms):
    if not ts_ms:
        return ""
    try:
        dt = datetime.datetime.fromtimestamp(ts_ms / 1000)
    except (ValueError, OverflowError, OSError):
        return ""
    return dt.strftime("%Y-%m-%d")


def build_chat_excel(store, chat_id, stat, path):
    """Собрать .xlsx с отчётом. Возвращает путь к файлу."""
    w = XlsxWriter(path)

    # ---------- 1. Обзор ----------
    ov = w.add_sheet("Обзор")
    ov.rows.append(["Показатель", "Значение"])
    chat = store.get_chat(chat_id)
    chat_title = chat["title"] if chat else None
    ov.rows.append(["Чат/канал", chat_title or str(chat_id)])
    ov.rows.append(["Постов", stat["total_posts"]])
    ov.rows.append(["Комментариев", stat["total_comments"]])
    ov.rows.append(["Первый пост", _human_date(stat["first_ts"])])
    ov.rows.append(["Последний пост", _human_date(stat["last_ts"])])
    ov.rows.append(["Активных дней", len(stat["days"])])
    ov.rows.append(["Постов в среднем в день", stat["avg_per_day"]])

    # ---------- 2. Посты ----------
    posts = w.add_sheet("Посты")
    posts.rows.append(["дата", "mid", "автор", "текст", "вложения", "комментарии", "url"])
    cur_p = store.conn.execute(
        "SELECT timestamp, mid, sender_name, text, attachments_json, comments, url "
        "FROM posts WHERE chat_id=? ORDER BY timestamp ASC", (chat_id,)
    )
    for r in cur_p.fetchall():
        import json
        atts = ""
        try:
            raw = json.loads(r[4]) if r[4] else []
            atts = ", ".join(a.get("type", "?") for a in raw)
        except (TypeError, ValueError):
            pass
        posts.rows.append([
            _human_date(r[0]), r[1], r[2] or "", r[3] or "", atts, r[5] or 0, r[6] or "",
        ])

    # ---------- 3. Комментарии ----------
    com = w.add_sheet("Комментарии")
    com.rows.append(["дата", "к посту(mid)", "комментарий(mid)", "автор", "текст"])
    cur_c = store.conn.execute(
        "SELECT timestamp, mid, comment_mid, sender_name, text "
        "FROM comments WHERE chat_id=? ORDER BY timestamp ASC", (chat_id,)
    )
    for r in cur_c.fetchall():
        com.rows.append([_human_date(r[0]), r[1], r[2], r[3] or "", r[4] or ""])

    # ---------- 4. Активность по дням ----------
    act = w.add_sheet("Активность")
    act.rows.append(["дата", "постов"])
    for d, c in stat["days"]:
        act.rows.append([d, c])

    # ---------- 5. Авторы ----------
    auth = w.add_sheet("Авторы")
    auth.rows.append(["Роль", "Автор", "Постов"])
    for name, c in stat["top_post_authors"]:
        auth.rows.append(["автор постов", name, c])
    auth.rows.append(["---", None, None])
    for name, c in stat["top_comment_authors"]:
        auth.rows.append(["автор комментариев", name, c])

    # ---------- 6. Слова ----------
    wrds = w.add_sheet("Слова")
    wrds.rows.append(["слово", "упоминаний"])
    for word, c in stat["top_words"]:
        wrds.rows.append([word, c])

    # ---------- 7. Вложения ----------
    att = w.add_sheet("Вложения")
    att.rows.append(["тип", "кол-во"])
    for t, c in stat["attachments"]:
        att.rows.append([t, c])

    w.save()
    return path


def build_chat_excel_path(store, chat_id, stat, data_dir):
    """Определить имя файла отчёта и собрать его."""
    chat = store.get_chat(chat_id)
    title = (chat["title"] if chat else None) or str(chat_id)
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-") or str(chat_id)
    path = os.path.join(data_dir, "%s_%s_report.xlsx" % (chat_id, safe_title))
    return build_chat_excel(store, chat_id, stat, path)