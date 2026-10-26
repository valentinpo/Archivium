# -*- coding: utf-8 -*-
"""Нормализация ответов MAX API в плоские записи для хранения.

Сырой объект Message из GET /messages выглядит так (упрощённо):
{
  "sender":  {...user...},
  "recipient": {...chat...},
  "timestamp": 1737500130100,
  "body": {"mid": "...", "seq": 42, "text": "...", "attachments": [...]},
  "url": "https://...",
  "stat": {...}   # только у каналов
}
"""
import json


def _recipient_type(recipient):
    """Определить тип получателя: chat / channel / user / dialog."""
    if not recipient:
        return "unknown"
    if recipient.get("is_channel"):
        return "channel"
    if recipient.get("type"):
        return recipient.get("type")
    if recipient.get("chat_id") is not None or recipient.get("id") is not None:
        return "chat"
    return "unknown"


def _sender_info(sender):
    if not sender:
        return None, None
    return sender.get("user_id"), sender.get("name")


def normalize_message(raw, chat_id=None, known_chat_id=None):
    """Преобразовать сырое сообщение API в dict для PostStore.

    chat_id — фактический id, из которого читаем (если передан).
    known_chat_id — id из recipient, если он известен (актуально для каналов).
    """
    body = raw.get("body") or {}
    recipient = raw.get("recipient") or {}
    sender_id, sender_name = _sender_info(raw.get("sender"))

    # Отдаём приоритет переданному chat_id, иначе берём из recipient
    result_chat = chat_id
    if result_chat is None:
        candidate = recipient.get("chat_id") if "chat_id" in recipient else recipient.get("id")
        if candidate is not None:
            result_chat = candidate
    if result_chat is None:
        result_chat = known_chat_id

    attachments = body.get("attachments") or []

    return {
        "chat_id": result_chat,
        "mid": body.get("mid"),
        "seq": body.get("seq"),
        "sender_id": sender_id,
        "sender_name": sender_name,
        "timestamp": raw.get("timestamp"),
        "text": body.get("text"),
        "attachments_json": json.dumps(attachments, ensure_ascii=False) if attachments else None,
        "url": raw.get("url"),
        "comments": (raw.get("stat") or {}).get("comments") or 0,
    }


def normalize_comments_count(raw):
    """Число комментариев у поста канала (из stat)."""
    stat = raw.get("stat") or {}
    return stat.get("comments") or 0


def normalize_comment(raw, chat_id, mid):
    """Преобразовать сырой комментарий (CommentMessage) в dict для PostStore.

    comment_mid — id самого комментария (из body.mid).
    mid — id поста, к которому относится комментарий.
    """
    body = raw.get("body") or {}
    sender = raw.get("sender") or {}
    sender_id = sender.get("user_id")
    sender_name = sender.get("name")
    return {
        "chat_id": chat_id,
        "mid": mid,
        "comment_mid": body.get("mid"),
        "seq": body.get("seq"),
        "sender_id": sender_id,
        "sender_name": sender_name,
        "timestamp": raw.get("timestamp"),
        "text": body.get("text"),
    }


def summarize_attachments(attachments_json):
    """Краткое описание типов вложений для отображения (необязательно)."""
    if not attachments_json:
        return ""
    try:
        items = json.loads(attachments_json)
    except (TypeError, ValueError):
        return ""
    types = [a.get("type", "?") for a in items]
    return ", ".join(types)