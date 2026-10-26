# -*- coding: utf-8 -*-
"""Список выгруженных чатов/каналов и количества постов в базе.

Пример:
    python list_chats.py
"""
import logging

from store import PostStore

log = logging.getLogger("list_chats")


def main():
    logging.basicConfig(level=logging.INFO)
    s = PostStore()
    chats = s.list_chats()
    if not chats:
        print("База пуста. Добавьте бота в чат/канал и выдайте ему права администратора.")
        return
    print("%-12s %-10s %-30s %-8s %s" % ("chat_id", "тип", "название", "постов", "коммент"))
    print("-" * 80)
    total = 0
    total_com = 0
    for c in chats:
        n = s.count_posts(c["chat_id"])
        nc = s.count_comments(c["chat_id"])
        total += n
        total_com += nc
        print(
            "%-12s %-10s %-30s %-8s %s"
            % (c["chat_id"], c["chat_type"] or "?", c["title"] or "-", n, nc)
        )
    print("-" * 80)
    print("Итого постов: %d, комментариев: %d" % (total, total_com))


if __name__ == "__main__":
    main()