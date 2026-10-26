# -*- coding: utf-8 -*-
"""Тест потокобезопасности PostStore.

В GUI бот работает в фоновом потоке, а лог/автообновление приходят из главного.
Проверяем, что PostStore можно использовать из двух потоков одновременно без
ошибок "SQLite objects created in a thread can only be used in that same thread".
"""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from store import PostStore


def test_thread_safety():
    d = tempfile.mkdtemp()
    store = PostStore(db_path=os.path.join(d, "t.db"), data_dir=d)

    errors = []

    def writer_thread():
        try:
            # заведомо из другого потока
            for i in range(20):
                store.upsert_post({
                    "chat_id": 1, "mid": "m%d" % i, "seq": i,
                    "sender_id": 1, "sender_name": "Поток",
                    "timestamp": 1000 + i, "text": "тест %d" % i,
                    "attachments_json": None, "url": "", "comments": 0,
                })
        except Exception as e:
            errors.append("writer: %s" % e)

    t = threading.Thread(target=writer_thread)
    t.start()
    t.join()

    assert not errors, "Ошибки в фоновом потоке: %s" % errors
    assert store.count_posts(1) == 20, "ожидали 20 постов"
    # читаем из главного потока
    assert store.count_comments(1) == 0

    store.close()
    print("THREAD SAFETY TEST PASSED")


if __name__ == "__main__":
    test_thread_safety()
    print("OK")