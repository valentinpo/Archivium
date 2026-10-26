# -*- coding: utf-8 -*-
"""Смоук-тест: многоканальная выгрузка, дедупликация, сбор комментариев.

Мокаем HTTP-клиент, поэтому сеть и токен не нужны.
"""
import os
import sys
import tempfile

# чтобы импортировать модули проекта из папки
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot import MaxDumperBot
from store import PostStore


class FakeClient:
    """Подмена MaxClient: возвращает фиксированные данные."""

    def __init__(self):
        self.checked = {}     # chat_id -> membership
        self.pages = {}       # chat_id -> список страниц (каждая список raw-сообщений)

    def check_membership(self, chat_id):
        return self.checked.get(chat_id, {"is_admin": False})

    def get_messages(self, chat_id, before=None, count=100):
        # возвращаем разные страницы в зависимости от `before` (для простоты — всё сразу)
        return self.pages.get(chat_id, [])


def raw_post(mid, ts, text, chat_id=0, sender="Автор"):
    return {
        "sender": {"user_id": 1, "name": sender},
        "recipient": {"chat_id": chat_id, "is_channel": True},
        "timestamp": ts,
        "body": {"mid": mid, "seq": 1, "text": text, "attachments": []},
        "url": "https://max.ru/%s" % mid,
        "stat": {"comments": 0},
    }


def raw_comment(mid, ts, text, sender="Комментатор"):
    return {
        "sender": {"user_id": 2, "name": sender},
        "recipient": {"chat_id": 0, "is_channel": True},
        "timestamp": ts,
        "body": {"mid": mid, "seq": 1, "text": text},
    }


def test_multichannel_and_comments():
    tmp = tempfile.mkdtemp()

    fake = FakeClient()
    # два чата, в обоих бот админ
    fake.checked[111] = {"is_admin": True}
    fake.checked[222] = {"is_admin": True}
    fake.pages[111] = [raw_post("p1", 1000, "Пост A", 111), raw_post("p2", 2000, "Пост B", 111)]
    fake.pages[222] = [raw_post("p3", 3000, "Пост C", 222)]

    class TestBot(MaxDumperBot):
        def __init__(self):
            # не создаём реальный client/store, подменяем
            object.__setattr__(self, "client", fake)
            object.__setattr__(self, "store", PostStore(db_path=os.path.join(tmp, "t.db"), data_dir=tmp))
            object.__setattr__(self, "download_attachments", False)
            self._done_cache = {}

        def client_check(self, chat_id):
            return fake.check_membership(chat_id)

        def _build_excel_report(self, chat_id):
            pass  # отключаем Excel в тесте

    # Мокаем метод сбора комментариев, чтобы проверить вызовы
    bot = TestBot()
    bot._dump_comments = lambda chat_id, mid: 0

    # выгружаем оба чата
    bot._dump_history(111)
    bot._dump_history(222)

    store = bot.store
    assert store.count_posts(111) == 2, "Ожидали 2 поста в чате 111"
    assert store.count_posts(222) == 1, "Ожидали 1 пост в чате 222"
    assert store.count_posts() == 3, "Всего 3 поста в базе"

    # повторная выгрузка не дублирует
    bot._dump_history(111)
    assert store.count_posts(111) == 2, "Повторная выгрузка не должна дублировать"

    # комментарии
    fake.pages[111] = [raw_post("pNEW", 5000, "Пост с коммент", 111)]

    class CommentBot(MaxDumperBot):
        def __init__(self):
            object.__setattr__(self, "client", None)
            object.__setattr__(self, "store", PostStore(db_path=os.path.join(tmp, "c.db"), data_dir=tmp))
            object.__setattr__(self, "download_attachments", False)
            self._done_cache = {}

    cb = CommentBot()
    # подменяем клиент с поддержкой get_comments
    class CommentClient(fake.__class__):
        def __init__(self, *a):
            super().__init__()
        def get_comments(self, mid, before=None, count=100):
            return [raw_comment("c1", 5100, "комментарий 1"), raw_comment("c2", 5200, "комментарий 2")]

    cc = CommentClient()
    cb.client = cc
    # добавим пост в базу и соберём комментарии вручную
    from normalize import normalize_message, normalize_comment
    post = normalize_message(raw_post("pNEW", 5000, "Пост с коммент", 111), chat_id=111)
    cb.store.upsert_post(post)
    added = cb._dump_comments(111, "pNEW")
    assert added == 2, "Ожидали 2 новых комментария, получили %d" % added
    # повторно — дедупликация
    added2 = cb._dump_comments(111, "pNEW")
    assert added2 == 0, "Повторный сбор не должен добавлять"
    assert cb.store.count_comments(111) == 2

    # --- message_created извлекает chat_id из message.recipient ---
    # событие без верхнего chat_id, как в реальном API
    update = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 4, "name": "Автор"},
            "recipient": {"chat_id": 555, "chat_type": "chat"},
            "timestamp": 9000,
            "body": {"mid": "live1", "seq": 10, "text": "событие в чате", "attachments": []},
        },
    }
    captured = {}
    # переопределим _on_new_message чтобы поймать chat_id
    class CapBot(MaxDumperBot):
        def __init__(self):
            object.__setattr__(self, "client", fake)
            object.__setattr__(self, "store", PostStore(db_path=os.path.join(tmp, "cap.db"), data_dir=tmp))
            object.__setattr__(self, "download_attachments", False)
            self._done_cache = {}
        def _on_new_message(self, chat_id, upd):
            captured["chat_id"] = chat_id
    cap = CapBot()
    cap.handle_update(update)
    assert captured.get("chat_id") == 555, "message_created должен дать chat_id=555, получили %r" % captured.get("chat_id")

    # --- Excel-отчёт и статистика ---
    from stats import StatsBuilder
    from excel_export import build_chat_excel_path
    store2 = PostStore(db_path=os.path.join(tmp, "stats.db"), data_dir=tmp)
    store2.upsert_chat(333, "channel", "Отчётный канал")
    store2.upsert_post({'chat_id':333,'mid':'a','seq':1,'sender_id':1,'sender_name':'Автор',
                        'timestamp':1000000,'text':'первый пост про аналитику','attachments_json':'[{"type":"image"}]','url':'','comments':0})
    store2.upsert_post({'chat_id':333,'mid':'b','seq':2,'sender_id':1,'sender_name':'Автор',
                        'timestamp':2000000,'text':'второй пост про маркетинг','attachments_json':'[{"type":"video"}]','url':'','comments':1})
    store2.upsert_comment({'chat_id':333,'mid':'b','comment_mid':'cm1','seq':1,'sender_id':2,
                           'sender_name':'Читатель','timestamp':2100000,'text':'отличный пост'})
    stat = StatsBuilder(store2).build(333)
    assert stat['total_posts'] == 2, "статистика: 2 поста"
    assert stat['total_comments'] == 1, "статистика: 1 комментарий"
    assert 'аналитику' in [w for w, _ in stat['top_words']], "слова собираются"
    xlsx = build_chat_excel_path(store2, 333, stat, tmp)
    import zipfile
    with zipfile.ZipFile(xlsx) as z:
        assert 'xl/workbook.xml' in z.namelist(), "xlsx содержит workbook"
        assert sum(1 for n in z.namelist() if 'worksheets' in n) >= 5, "несколько листов"
    store2.close()

    store.close()

    print("ALL TESTS PASSED")


if __name__ == "__main__":
    test_multichannel_and_comments()
    print("OK")