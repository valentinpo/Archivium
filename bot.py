# -*- coding: utf-8 -*-
"""Основная логика бота: обработка событий и выгрузка постов из чатов/каналов.

Сценарий:
  1. Бота добавляют в чат/канал -> событие bot_added.
  2. Боту выдают права администратора -> событие bot_admin_permissions_changed
     (поле is_admin=True). Это открывает доступ к истории через GET /messages.
  3. Бот выгружает все посты постранично и складывает в SQLite.
"""
import logging
import json
import time

from max_api import MaxClient
from normalize import normalize_message, normalize_comment, summarize_attachments
from store import PostStore
from download import download_attachment, get_dest_dir

log = logging.getLogger("maxbot")

# Право, необходимое для чтения истории постов
REQUIRED_PERMISSION = "read_all_messages"

# На сколько страниц максимум запрашиваем историю (защита от бесконечного цикла)
MAX_PAGES = 5000


class MaxDumperBot:
    def __init__(self, token, base_url=None, download_attachments=True,
                 on_event=None, on_log=None):
        self.client = MaxClient(token, base_url=base_url)
        self.store = PostStore()
        # скачивать ли вложения постов (можно выключить для скорости)
        self.download_attachments = download_attachments
        # кэш уже выгруженных mid по чатам, чтобы не ходить в БД на каждый пост
        self._done_cache = {}
        # хуки для GUI
        self.on_event = on_event          # вызвается при каждом update
        self.on_log = on_log              # вызывается на каждое лог-сообщение
        self._stop = False                # флаг остановки (для GUI/сервиса)
        if on_log:
            self._setup_gui_logging()

    # ------------------------------------------------------------------
    # Главный цикл (Long Polling)
    # ------------------------------------------------------------------
    def stop(self):
        """Запросить остановку цикла (для GUI/сервиса)."""
        self._stop = True

    def _setup_gui_logging(self):
        """Перенаправить лог проекта в хук on_log (для GUI)."""
        handler = _GuiLogHandler(self.on_log)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger = logging.getLogger("maxbot")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    def run(self, poll_timeout=30):
        log.info("Bot started. Waiting for events (Long Polling)...")
        marker = None
        idle_errors = 0
        self._stop = False
        # Проверяем уже известные чаты: если бот где-то админ, выгружаем историю
        # даже если событие bot_added/admin пришло, пока бот не был запущен.
        try:
            self._sync_known_chats()
        except Exception:
            log.exception("Initial chat sync failed")
        while not self._stop:
            try:
                updates, marker = self.client.get_updates(
                    marker=marker, limit=100, timeout=poll_timeout
                )
                idle_errors = 0
                for upd in updates:
                    if self._stop:
                        break
                    try:
                        if self.on_event:
                            self.on_event(upd)
                        self.handle_update(upd)
                    except Exception:
                        log.exception("Error handling update %s", upd)
            except KeyboardInterrupt:
                log.info("Stopped by user.")
                break
            except Exception:
                idle_errors += 1
                log.exception("Polling error (attempt %d), retrying...", idle_errors)
                time.sleep(min(5 * idle_errors, 30))
        log.info("Bot stopped.")

    # ------------------------------------------------------------------
    # Обработка событий
    # ------------------------------------------------------------------
    def handle_update(self, upd):
        utype = upd.get("update_type")
        chat_id = upd.get("chat_id")

        # Для message_created chat_id лежит в message.recipient.chat_id
        if chat_id is None and utype == "message_created":
            message = upd.get("message") or {}
            recipient = message.get("recipient") or {}
            cid = recipient.get("chat_id")
            if cid is not None:
                chat_id = cid

        log.info("Update: %s chat=%s", utype, chat_id)

        if utype == "bot_added":
            self._on_bot_added(chat_id, upd.get("is_channel", False), upd)
        elif utype == "bot_admin_permissions_changed":
            self._on_admin_changed(chat_id, upd)
        elif utype == "bot_removed":
            log.info("Bot removed from chat %s", chat_id)
        elif utype == "message_created":
            self._on_new_message(chat_id, upd)
        else:
            log.debug("Ignored update type: %s", utype)

    # ------------------------------------------------------------------
    # bot_added
    # ------------------------------------------------------------------
    def _on_bot_added(self, chat_id, is_channel, upd):
        if chat_id is None:
            log.warning("bot_added without chat_id, skipping")
            return
        log.info("Bot added to %s %s", "channel" if is_channel else "chat", chat_id)
        # Запомним чат, но выгрузку запустим только когда появится право админа.
        self.store.upsert_chat(chat_id, chat_type="channel" if is_channel else "chat")
        self._maybe_dump(chat_id, reason="bot_added")

    # ------------------------------------------------------------------
    # bot_admin_permissions_changed
    # ------------------------------------------------------------------
    def _on_admin_changed(self, chat_id, upd):
        if chat_id is None:
            return
        is_admin = upd.get("is_admin", False)
        log.info("Admin permissions for bot in %s changed (is_admin=%s)", chat_id, is_admin)
        self.store.upsert_chat(
            chat_id,
            chat_type="channel" if upd.get("is_channel") else "chat",
        )
        if is_admin:
            self._maybe_dump(chat_id, reason="admin_granted")

    # ------------------------------------------------------------------
    # message_created (новые посты после выгрузки)
    # ------------------------------------------------------------------
    def _on_new_message(self, chat_id, upd):
        if chat_id is None:
            return
        raw = upd.get("message")
        if not raw:
            return
        try:
            post = normalize_message(raw, chat_id=chat_id)
        except Exception:
            log.exception("Cannot normalize new message")
            return
        if post.get("mid") is None:
            return
        # Гарантируем, что чат появится в списке вкладки «Чаты»
        try:
            self.store.upsert_chat(chat_id)   # chat_type/title подтянутся позже
            self._try_fill_chat_info(chat_id)
        except Exception:
            log.exception("Failed to register chat %s", chat_id)
        self.store.upsert_post(post)
        log.info("Stored new post mid=%s in chat %s", post["mid"], chat_id)
        # Скачиваем вложения нового поста
        try:
            self._download_post_attachments(post)
        except Exception:
            log.exception("Failed to download attachments for new post %s", post["mid"])
        # Подбираем комментарии к новому посту (актуально для каналов)
        try:
            self._dump_comments(chat_id, post["mid"])
        except Exception:
            log.exception("Failed to collect comments for new post %s", post["mid"])

    def _try_fill_chat_info(self, chat_id):
        """Попытаться получить название/тип чата через API (нужны права админа).

        Не критично, если не получится — чат всё равно появится в списке
        с пустым названием, а тип/название подтянутся при полной выгрузке.
        """
        try:
            info = self.client.get_chat(chat_id)
        except Exception:
            return
        if not info:
            return
        title = info.get("name") or info.get("title")
        chat_type = None
        if info.get("is_channel"):
            chat_type = "channel"
        self.store.upsert_chat(chat_id, chat_type=chat_type,
                               title=title or None)
        if title:
            log.info("Chat %s title resolved: %s", chat_id, title)

    # ------------------------------------------------------------------
    # Запуск выгрузки
    # ------------------------------------------------------------------
    def _maybe_dump(self, chat_id, reason):
        """Проверяем права; если бот админ — выгружаем историю."""
        try:
            membership = self.client.check_membership(chat_id)
        except Exception:
            log.exception("Cannot check membership for chat %s", chat_id)
            return

        if not self._is_admin_membership(membership):
            log.info(
                "Bot is not admin in %s yet (reason=%s). "
                "Grant admin rights to enable history export.",
                chat_id, reason,
            )
            return

        log.info("Bot is admin in %s — starting export (reason=%s)", chat_id, reason)
        self._dump_history(chat_id)

    @staticmethod
    def _is_admin_membership(membership):
        if not membership:
            return False
        return bool(membership.get("is_admin", False))

    def _sync_known_chats(self):
        """При старте проверить все известные чаты и выгрузить их историю.

        Нужно, чтобы история скачалась даже если событие admin_permissions
        пришло, пока бот не был запущен (или было потеряно).
        """
        try:
            chats = self.store.list_all_chats()
        except Exception:
            chats = []
        if not chats:
            log.info("No known chats at startup, nothing to sync.")
            return
        for row in chats:
            chat_id = row["chat_id"]
            if chat_id is None:
                continue
            log.info("Checking permissions in known chat %s...", chat_id)
            self._maybe_upsert_chat_meta(chat_id)
            self._maybe_dump(chat_id, reason="startup_sync")

    def _maybe_upsert_chat_meta(self, chat_id):
        """Попробовать получить название/тип чата и сохранить их."""
        try:
            info = self.client.get_chat(chat_id)
        except Exception:
            return
        if not info:
            return
        title = info.get("name") or info.get("title")
        chat_type = "channel" if info.get("is_channel") else None
        self.store.upsert_chat(chat_id, chat_type=chat_type, title=title or None)

    # ------------------------------------------------------------------
    # Выгрузка всей истории
    # ------------------------------------------------------------------
    def _dump_history(self, chat_id):
        # Определим границы: до последнего поста (компактный запрос с after)
        # Выгружаем постранично, двигаясь назад во времени от нового к старому.
        before = None
        page_stats = {"pages": 0, "new": 0, "new_comments": 0}
        oldest_ts = None

        for page in range(MAX_PAGES):
            try:
                messages = self.client.get_messages(
                    chat_id, before=before, count=100
                )
            except Exception:
                log.exception("Failed to fetch messages page for chat %s", chat_id)
                return

            if not messages:
                break

            page_stats["pages"] += 1
            for raw in messages:
                post = normalize_message(raw, chat_id=chat_id)
                mid = post.get("mid")
                if mid is None:
                    continue
                if not self._is_new_post(chat_id, mid):
                    continue
                self.store.upsert_post(post)
                page_stats["new"] += 1
                ts = post.get("timestamp")
                if ts is not None:
                    oldest_ts = ts if oldest_ts is None else min(oldest_ts, ts)
                # Скачиваем вложения поста (изображения, видео, файлы)
                try:
                    self._download_post_attachments(post)
                except Exception:
                    log.exception("Failed to download attachments for post %s", mid)
                # Собираем комментарии к посту (для каналов)
                try:
                    added = self._dump_comments(chat_id, mid)
                    page_stats["new_comments"] += added
                except Exception:
                    log.exception("Failed to collect comments for post %s", mid)

            # Последний (самый старый) пост на странице определяет следующий шаг.
            last_ts = messages[-1].get("timestamp")
            if last_ts is None:
                break

            # Страховка от зацикливания: если маркер не продвинулся — стоп.
            if before is not None and last_ts >= before:
                log.warning(
                    "Marker did not advance (before=%s last_ts=%s), stopping.",
                    before, last_ts,
                )
                break
            before = last_ts
            if page_stats["pages"] >= MAX_PAGES:
                log.warning("Reached MAX_PAGES for chat %s", chat_id)
                break

        log.info(
            "Export finished for chat %s: %d page(s), %d new post(s), %d comment(s)",
            chat_id, page_stats["pages"], page_stats["new"], page_stats["new_comments"],
        )

        # Экспорт в файл
        try:
            json_path = self.store.export_chat(chat_id, fmt="json")
            csv_path = self.store.export_chat(chat_id, fmt="csv")
            cjson_path = self.store.export_comments(chat_id, fmt="json")
            ccsv_path = self.store.export_comments(chat_id, fmt="csv")
            log.info(
                "Exported chat %s ->\n  %s\n  %s\n  %s\n  %s",
                chat_id, json_path, csv_path, cjson_path, ccsv_path,
            )
            # Статистика + Excel-отчёт
            self._build_excel_report(chat_id)
        except Exception:
            log.exception("Failed to export chat %s to files", chat_id)

    def _download_post_attachments(self, post):
        """Скачать все вложения поста в папку attachments/<chat_id>/."""
        if not self.download_attachments:
            return
        if not post.get("attachments_json"):
            return
        try:
            atts = json.loads(post["attachments_json"])
        except (TypeError, ValueError):
            return
        if not atts:
            return
        dest = get_dest_dir(self.store.data_dir, post["chat_id"])
        for att in atts:
            try:
                download_attachment(
                    att, dest, client=self.client,
                    chat_id=post["chat_id"], mid=post["mid"],
                )
            except Exception:
                log.exception("Failed to download attachment of post %s", post["mid"])

    def _build_excel_report(self, chat_id):
        """Собрать статистику и построить Excel-отчёт по чату."""
        from stats import StatsBuilder
        from excel_export import build_chat_excel_path

        try:
            sb = StatsBuilder(self.store)
            stat = sb.build(chat_id)
            xlsx_path = build_chat_excel_path(self.store, chat_id, stat, self.store.data_dir)
            log.info("Excel report for chat %s -> %s", chat_id, xlsx_path)
        except Exception:
            log.exception("Failed to build Excel report for chat %s", chat_id)

    def _dump_comments(self, chat_id, mid):
        """Выгрузить все комментарии к посту (канала). Возвращает число новых.

        Для групповых чатов метод может вернуть ошибку 403/404 или пусто —
        обрабатываем безопасно (пустой результат). Право на комментарии
        тоже требует админки, как и на историю постов.
        """
        before = None
        added = 0
        max_comment_pages = 500
        for _page in range(max_comment_pages):
            try:
                comments = self.client.get_comments(mid, before=before, count=100)
            except Exception as e:
                # Для обычных чатов комментариев нет -> тихо пропускаем.
                log.debug("Comments unavailable for post %s: %s", mid, e)
                break
            if not comments:
                break
            for c in comments:
                comment = normalize_comment(c, chat_id, mid)
                cmid = comment.get("comment_mid")
                if cmid is None:
                    continue
                if self.store.comment_exists(chat_id, mid, cmid):
                    continue
                self.store.upsert_comment(comment)
                added += 1
            last_ts = comments[-1].get("timestamp")
            if last_ts is None:
                break
            if before is not None and last_ts >= before:
                break
            before = last_ts
        return added

    def _is_new_post(self, chat_id, mid):
        if chat_id not in self._done_cache:
            self._done_cache[chat_id] = set()
        if mid in self._done_cache[chat_id]:
            return False
        self._done_cache[chat_id].add(mid)
        return True


class _GuiLogHandler(logging.Handler):
    """Переправляет записи лога в callback (для показа в GUI)."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            msg = self.format(record)
            self.callback(msg)
        except Exception:
            pass


def main():
    import argparse
    import os

    from dotenv_status import get_token

    parser = argparse.ArgumentParser(description="MAX post dumper bot (long polling)")
    parser.add_argument(
        "--no-attachments", action="store_true",
        help="Не скачивать вложения постов (только текст/метаданные)",
    )
    parser.add_argument(
        "--no-excel", action="store_true",
        help="Не формировать Excel-отчёт",
    )
    parser.add_argument(
        "--download-attachments", action="store_true",
        help="Скачивать вложения только при 'message_created' (доп. флаг)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    token = get_token()
    if not token:
        log.error(
            "BOT_TOKEN is not set. Создайте файл .env рядом со скриптом "
            "с содержимым: BOT_TOKEN=ваш_токен"
        )
        return

    bot = MaxDumperBot(token, download_attachments=not args.no_attachments)
    if args.no_excel:
        # отключаем Excel-отчёт: подменяем метод на no-op
        bot._build_excel_report = lambda chat_id: None
    try:
        me = bot.client.me()
        log.info("Authorized as bot: %s", me.get("name") or me.get("user_id"))
    except Exception:
        log.exception("Authorization failed — check BOT_TOKEN")
        return

    bot.run()


if __name__ == "__main__":
    main()