# -*- coding: utf-8 -*-
"""Сервисный слой для работы с MAX Bot API (Long Polling).

Используется только стандартная библиотека Python (urllib), чтобы не требовать
установки пакетов. Обёртки над методами из https://dev.max.ru/docs-api
"""
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from config import MAX_API_BASE

# Типы обновлений, которые интересуют бота
UPDATE_TYPES = [
    "bot_added",
    "bot_removed",
    "bot_admin_permissions_changed",
    "message_created",
]

# Права, которые открывают доступ к чтению истории
# (подробнее о константах в схеме API / на платформе MAX)
PERMISSION_READ_ALL_MESSAGES = "read_all_messages"


class MaxApiError(Exception):
    """Ошибка API MAX с HTTP-кодом и телом ответа."""

    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__("MAX API error: %s %s" % (status, body))


class MaxClient:
    """Клиент для MAX Bot API (Long Polling)."""

    def __init__(self, token, base_url=None):
        self.token = token
        self.base = (base_url or MAX_API_BASE).rstrip("/")
        # ВАЖНО: сертификат Минцифры нужен для запросов к platform-api2.max.ru.
        # На Windows часто проще не проверять сертификат (см. README).
        self.ctx = ssl.create_default_context()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _url(self, path, query=None):
        if query:
            return self.base + path + "?" + urllib.parse.urlencode(query)
        return self.base + path

    def _request(self, method, path, query=None, body=None):
        url = self._url(path, query)
        data = None
        headers = {"Authorization": self.token, "Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=100, context=self.ctx) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise MaxApiError(e.code, detail) from e
        except urllib.error.URLError as e:
            raise MaxApiError(0, "network error: %s" % e.reason) from e

    def _get(self, path, query=None):
        return self._request("GET", path, query=query)

    def _post(self, path, query=None, body=None):
        return self._request("POST", path, query=query, body=body)

    # ------------------------------------------------------------------
    # Обновления (Long Polling)
    # ------------------------------------------------------------------
    def get_updates(self, marker=None, limit=100, timeout=30):
        """Получить пачку обновлений. Возвращает (список обновлений, новый marker)."""
        query = {
            "limit": limit,
            "timeout": timeout,
            "types": ",".join(UPDATE_TYPES),
        }
        if marker is not None:
            query["marker"] = marker
        try:
            resp = self._get("/updates", query=query)
        except MaxApiError as e:
            # На провал сети / таймаут просто вернём пустую пачку без потери маркера
            if e.status in (0, 503, 504):
                return [], marker
            raise
        if resp is None:
            return [], marker
        updates = resp.get("updates") or []
        new_marker = resp.get("marker") or marker
        return updates, new_marker

    # ------------------------------------------------------------------
    # Информация о боте / чатах
    # ------------------------------------------------------------------
    def me(self):
        return self._get("/me")

    def get_chat(self, chat_id):
        """Информация о групповом чате или канале."""
        return self._get("/chats/%s" % chat_id)

    def check_membership(self, chat_id):
        """Проверить, является ли бот администратором чата/канала.

        Возвращает объект членства бота (есть поле is_admin и permissions).
        Для личных диалогов метод недоступен — возвращает пустой dict,
        чтобы считалось «не администратор».
        """
        try:
            return self._get("/chats/%s/members/me" % chat_id)
        except MaxApiError as e:
            # 400 "Method is not available for dialogs" — это диалог, а не чат
            if e.status == 400 and "dialog" in str(e.body).lower():
                return {}
            raise

    # ------------------------------------------------------------------
    # Сообщения / посты
    # ------------------------------------------------------------------
    def get_messages(self, chat_id, before=None, after=None, count=100):
        """Получить посты сообщения из чата/канала постранично.

        Сообщения идут в обратном порядке (последние первыми).
        before/after — unix-время в миллисекундах, маркеры пагинации.
        Возвращает список сообщений.
        """
        query = {"chat_id": chat_id, "count": count}
        if before is not None:
            query["before"] = before
        if after is not None:
            query["after"] = after
        resp = self._get("/messages", query=query)
        if resp is None:
            return []
        return resp.get("messages") or []

    def get_message(self, message_id):
        return self._get("/messages/%s" % message_id)

    def get_video_details(self, video_token):
        """Детали видео по токену: прямые URL для скачивания (mp4 разного качества)."""
        return self._get("/videos/%s" % video_token)

    def get_comments(self, message_id, before=None, after=None, count=100):
        """Комментарии к посту (канала) постранично.

        Комментарии идут в обратном порядке (последние первыми).
        before/after — unix-время в миллисекундах, маркеры пагинации.
        Возвращает список комментариев (CommentMessage).
        """
        query = {"count": count}
        if before is not None:
            query["before"] = before
        if after is not None:
            query["after"] = after
        resp = self._get("/messages/%s/comments" % message_id, query=query)
        if resp is None:
            return []
        return resp.get("messages") or []

    def send_message_to_chat(self, chat_id, text, **kwargs):
        body = {"text": text}
        body.update(kwargs)
        return self._post("/messages", query={"chat_id": chat_id}, body=body)


def is_admin(membership):
    """Проверить, что в ответе chats/{id}/members/me бот — администратор."""
    if not membership:
        return False
    return bool(membership.get("is_admin", False))


def has_permission(membership, permission):
    """Проверить наличие конкретного права у бота."""
    perms = membership.get("permissions") or []
    return permission in perms