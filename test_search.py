# -*- coding: utf-8 -*-
"""Тест поиска и новых фич (search, html, автообновление GUI)."""
import os
import sys
import tempfile
import datetime
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from store import PostStore
from search import Searcher
from html_report import build_html_report_path


def _seed(data_dir):
    s = PostStore(db_path=os.path.join(data_dir, "max_posts.db"), data_dir=data_dir)
    s.upsert_chat(1001, "channel", "Новости")
    s.upsert_chat(1002, "chat", "Обсуждение")
    base = int(datetime.datetime(2026, 1, 10).timestamp() * 1000)
    s.upsert_post({"chat_id": 1001, "mid": "n1", "seq": 1, "sender_id": 1,
                   "sender_name": "Ред", "timestamp": base,
                   "text": "ИИ в медицине: новые подходы",
                   "attachments_json": "[]", "url": "", "comments": 0})
    s.upsert_post({"chat_id": 1002, "mid": "d1", "seq": 1, "sender_id": 2,
                   "sender_name": "Пользователь", "timestamp": base + 3600000,
                   "text": "А как насчёт ИИ в дизайне?",
                   "attachments_json": "[]", "url": "", "comments": 0})
    s.upsert_comment({"chat_id": 1001, "mid": "n1", "comment_mid": "c1", "seq": 1,
                      "sender_id": 3, "sender_name": "Читатель",
                      "timestamp": base + 10000, "text": "интересная тема про ИИ"})
    return s


def test_search():
    d = tempfile.mkdtemp()
    s = _seed(d)
    sr = Searcher(s)

    # поиск по слову
    res = sr.search(query="ИИ")
    assert len(res["posts"]) == 2, "ожидали 2 поста с 'ИИ'"
    assert len(res["comments"]) == 1, "ожидали 1 комментарий с 'ИИ'"

    # регистронезависимость
    res = sr.search(query="ии")
    assert len(res["posts"]) == 2

    # по автору
    res = sr.search(author="Ред")
    assert len(res["posts"]) == 1
    assert res["posts"][0]["sender_name"] == "Ред"

    # по чату
    res = sr.search(query="ИИ", chat_id=1001)
    assert len(res["posts"]) == 1, "в чате 1001 должен быть 1 пост с ИИ"

    # по дате
    res = sr.search(query="ИИ", date_from="2026-01-01")
    assert len(res["posts"]) == 2
    s.close()
    print("SEARCH TEST PASSED")


def test_html_and_autorefresh():
    import tkinter as tk
    try:
        root = tk.Tk()
    except Exception as e:
        print("SKIP GUI: no display (%s)" % e)
        return
    root.withdraw()
    from gui import MaxGuiApp
    import gui as gui_module
    gui_module.messagebox.showinfo = lambda *a, **k: None
    gui_module.messagebox.showwarning = lambda *a, **k: None
    gui_module.messagebox.showerror = lambda *a, **k: None

    tmp = tempfile.mkdtemp()
    import config
    config.DATA_DIR = tmp
    import store as store_mod
    store_mod.DATA_DIR = tmp
    _seed(tmp)

    app = MaxGuiApp(root)
    app._refresh_chats()

    # HTML-отчёт
    from stats import StatsBuilder
    stat = StatsBuilder(PostStore()).build(1001)
    p = build_html_report_path(PostStore(), 1001, stat, tmp)
    content = open(p, encoding="utf-8").read()
    assert "ИИ в медицине" in content
    assert "drawBars" in content

    # поиск в GUI
    app.var_search_q.set("ИИ")
    app._do_search()
    out = app.search_text.get("1.0", "end")
    assert "ИИ в медицине" in out
    assert "А как насчёт" in out

    # автообновление не ломается
    app._auto_refresh_chats()
    root.destroy()
    print("GUI NEW FEATURES TEST PASSED")


if __name__ == "__main__":
    test_search()
    test_html_and_autorefresh()
    print("OK")