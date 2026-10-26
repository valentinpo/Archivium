# -*- coding: utf-8 -*-
"""Проверка генерации HTML-отчёта."""
import os
import sys
import tempfile
import datetime
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from store import PostStore
from stats import StatsBuilder
from html_report import build_html_report_path


def main():
    d = tempfile.mkdtemp()
    s = PostStore(db_path=os.path.join(d, "t.db"), data_dir=d)
    s.upsert_chat(555, "channel", "Тест HTML канал")
    base = int(datetime.datetime(2026, 2, 1).timestamp() * 1000)
    for i in range(4):
        s.upsert_post({"chat_id": 555, "mid": "h%d" % i, "seq": i, "sender_id": 1,
                       "sender_name": "Автор", "timestamp": base + i * 172800000,
                       "text": "Статья про UI и дизайн %d" % i,
                       "attachments_json": json.dumps([{"type": "image"}]),
                       "url": "https://max.ru/h%d" % i, "comments": 0})
    p = build_html_report_path(s, 555, StatsBuilder(s).build(555), d)
    content = open(p, encoding="utf-8").read()
    assert "Тест HTML канал" in content, "title"
    assert "Статья про UI" in content, "posts table"
    assert "drawBars" in content, "chart js"
    assert "дизайн" in content, "words"
    assert "<!DOCTYPE html>" in content
    print("HTML REPORT TEST PASSED (size=%d)" % os.path.getsize(p))
    s.close()


if __name__ == "__main__":
    main()