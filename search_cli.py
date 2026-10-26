# -*- coding: utf-8 -*-
"""Поиск по выгруженным постам и комментариям (командная строка).

Примеры:
    python search_cli.py --query "ИИ"
    python search_cli.py --query "ии" --chat 12345
    python search_cli.py --author "Ред" --chat 1001
    python search_cli.py --query "новость" --date-from 2026-01-01 --date-to 2026-01-31
    python search_cli.py --chat 1001 --list-chats
"""
import argparse
import logging

from store import PostStore
from search import Searcher

log = logging.getLogger("search_cli")


def _human_date(ts):
    import datetime
    if not ts:
        return "-"
    try:
        return datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return "-"


def _print_chat_id(idx, cid):
    s = PostStore()
    chat = s.get_chat(cid)
    s.close()
    name = chat["title"] if chat else ""
    return "[%s] %s" % (cid, name)


def main():
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="Поиск по выгруженным данным MAX")
    parser.add_argument("--query", default=None, help="текст для поиска")
    parser.add_argument("--chat", type=int, default=None, help="ID чата/канала (если нужно ограничить)")
    parser.add_argument("--author", default=None, help="имя автора")
    parser.add_argument("--date-from", default=None, help="начало периода ГГГГ-ММ-ДД")
    parser.add_argument("--date-to", default=None, help="конец периода ГГГГ-ММ-ДД")
    parser.add_argument("--limit", type=int, default=100, help="макс. результатов (по умолч. 100)")
    parser.add_argument("--list-chats", action="store_true", help="показать список чатов и выйти")
    args = parser.parse_args()

    s = PostStore()
    if args.list_chats:
        for c in s.list_chats():
            print("%s\t%s\tпостов=%d\tкоммент=%d" % (
                c["chat_id"], c["title"] or "-",
                s.count_posts(c["chat_id"]), s.count_comments(c["chat_id"]),
            ))
        s.close()
        return

    searcher = Searcher(s)
    res = searcher.search(
        query=args.query, chat_id=args.chat, author=args.author,
        date_from=args.date_from, date_to=args.date_to, limit=args.limit,
    )
    s.close()

    print("== Найдено постов: %d ==" % len(res["posts"]))
    for r in res["posts"]:
        print("\n%s  %s  %s" % (_print_chat_id(0, r["chat_id"]), _human_date(r["timestamp"]), r["sender_name"] or "-"))
        print("   %s" % ((r["text"] or "")[:300]))
    print("\n== Найдено комментариев: %d ==" % len(res["comments"]))
    for r in res["comments"]:
        print("\n%s  %s  %s  (к посту %s)" % (
            _print_chat_id(0, r["chat_id"]), _human_date(r["timestamp"]),
            r["sender_name"] or "-", r["mid"]))
        print("   %s" % ((r["text"] or "")[:300]))


if __name__ == "__main__":
    main()