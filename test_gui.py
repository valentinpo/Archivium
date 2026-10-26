# -*- coding: utf-8 -*-
"""Тесты GUI-части (без запуска окна/mainloop).

Проверяет: инициализацию, заполнение таблицы чатов, отчёт,
отображение лога через очередь, работу флага настроек.
Вся работа ведётся во временном каталоге, exports/ не затрагивается.
"""
import os
import sys
import tempfile
import datetime
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from store import PostStore


def _make_test_db(data_dir):
    s = PostStore(db_path=os.path.join(data_dir, "max_posts.db"), data_dir=data_dir)
    s.upsert_chat(1001, "channel", "Новости")
    s.upsert_chat(1002, "chat", "Обсуждение")
    base = int(datetime.datetime(2026, 1, 1).timestamp() * 1000)
    for i in range(3):
        s.upsert_post({"chat_id": 1001, "mid": "n%d" % i, "seq": i, "sender_id": 1,
                       "sender_name": "Ред", "timestamp": base + i * 3600000,
                       "text": "Новость про ИИ %d" % i,
                       "attachments_json": json.dumps([{"type": "image"}]),
                       "url": "", "comments": 0})
    s.upsert_comment({"chat_id": 1001, "mid": "n0", "comment_mid": "c1", "seq": 1,
                      "sender_id": 2, "sender_name": "Пользователь",
                      "timestamp": base + 1000, "text": "отлично"})
    s.upsert_post({"chat_id": 1002, "mid": "d0", "seq": 0, "sender_id": 3,
                   "sender_name": "Модератор", "timestamp": base + 10000,
                   "text": "тема обсуждения", "attachments_json": "[]",
                   "url": "", "comments": 0})
    s.close()


def test_gui_logic():
    import tkinter as tk
    try:
        root = tk.Tk()
    except Exception as e:
        print("SKIP: no display available (%s)" % e)
        return
    root.withdraw()

    from gui import MaxGuiApp
    import gui as gui_module
    # запрещаем модальные диалоги в тестах
    gui_module.messagebox.showinfo = lambda *a, **k: None
    gui_module.messagebox.showwarning = lambda *a, **k: None
    gui_module.messagebox.showerror = lambda *a, **k: None
    gui_module.messagebox.askyesno = lambda *a, **k: True

    tmp = tempfile.mkdtemp()
    # направляем всю работу во временную папку
    import config
    config.DATA_DIR = tmp
    import store as store_mod
    store_mod.DATA_DIR = tmp

    _make_test_db(tmp)
    app = MaxGuiApp(root)

    app._refresh_chats()
    rows = [app.tree.item(i)["values"] for i in app.tree.get_children()]
    assert len(rows) == 2, "ожидали 2 чата, получили %d" % len(rows)
    channel_row = next(r for r in rows if r[0] == 1001)
    assert channel_row[3] == 3, "у канала 1001 должно быть 3 поста"
    assert channel_row[4] == 1, "у канала 1001 должен быть 1 комментарий"

    from stats import StatsBuilder
    stat = StatsBuilder(PostStore()).build(1001)
    assert stat["total_posts"] == 3
    report = app._format_report(1001, stat)
    assert "Новости" in report
    assert "Пользователь" in report

    # очередь лога
    app._append_log("handled")
    content = app.log_text.get("1.0", "end")
    assert "handled" in content

    # сохранение настроек пишет .env (аккуратно: восстанавливаем)
    env_file = ".env"
    backup = None
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            backup = f.read()
    app.var_token.set("SECRET_TOKEN_123")
    app._save_settings()
    from dotenv_status import _load_dotenv
    assert _load_dotenv(".env").get("BOT_TOKEN") == "SECRET_TOKEN_123"
    # восстановить исходный .env или удалить тестовый
    if backup is not None:
        with open(env_file, "w", encoding="utf-8") as f:
            f.write(backup)
    else:
        cur = _load_dotenv(".env")
        # удаляем только если это наш тестовый файл (один токен)
        if set(cur.keys()) == {"BOT_TOKEN"} and cur.get("BOT_TOKEN") == "SECRET_TOKEN_123":
            try:
                os.remove(env_file)
            except OSError:
                pass

    root.destroy()
    print("GUI TESTS PASSED")


if __name__ == "__main__":
    test_gui_logic()
    print("OK")