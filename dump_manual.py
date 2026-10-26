# -*- coding: utf-8 -*-
"""Ручной запуск выгрузки истории одного чата/канала.

Пример:
    python dump_manual.py --chat 123456
    python dump_manual.py --chat 123456 --no-excel --no-attachments

Ищет токен в переменной окружения BOT_TOKEN или в файле .env.
"""
import argparse
import logging

from bot import MaxDumperBot
from dotenv_status import get_token

log = logging.getLogger("dump_manual")


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="Выгрузка истории постов чата/канала MAX")
    parser.add_argument("--chat", required=True, type=int, help="chat_id чата или канала")
    parser.add_argument("--token", default=None, help="токен бота (или BOT_TOKEN/.env)")
    parser.add_argument("--no-attachments", action="store_true",
                        help="Не скачивать вложения (быстрее)")
    parser.add_argument("--no-excel", action="store_true",
                        help="Не формировать Excel-отчёт")
    args = parser.parse_args()

    token = args.token or get_token()
    if not token:
        log.error("Токен не задан. Укажите --token или BOT_TOKEN в .env")
        return
    if args.chat <= 0:
        log.error("Некорректный chat_id: %s", args.chat)
        return

    bot = MaxDumperBot(token, download_attachments=not args.no_attachments)
    if args.no_excel:
        bot._build_excel_report = lambda chat_id: None
    try:
        membership = bot.client.check_membership(args.chat)
    except Exception as e:
        log.error("Не удалось проверить права бота в чате %s: %s", args.chat, e)
        log.error("Проверьте, что бот добавлен в чат и является администратором.")
        return

    if not membership or not membership.get("is_admin"):
        log.error(
            "Бот НЕ является администратором чата %s. "
            "Выгрузка истории требует прав администратора.",
            args.chat,
        )
        return

    log.info("Права подтверждены. Начинаю выгрузку чата %s...", args.chat)
    bot._dump_history(args.chat)
    log.info("Готово. Файлы лежат в папке exports/.")


if __name__ == "__main__":
    main()