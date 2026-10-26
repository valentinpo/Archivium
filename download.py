# -*- coding: utf-8 -*-
"""Скачивание вложений постов (изображения, видео, файлы) в локальную папку.

Вложения в объекте Message:
  - image:  payload.url (прямая ссылка), payload.photo_id
  - file:   payload.url, filename, size
  - audio:  payload.url
  - video:  payload.url НЕ даёт прямых ссылок — нужен getVideoAttachmentDetails.
    В payload у видео есть url, но согласно доке для скачивания нужно
    вызывать метод /videos/{token}, который вернёт mp4-ссылки по разрешениям.

Логика: для image/file/audio качаем payload.url, для video — best mp4 из
getVideoAttachmentDetails. Если URL недоступен — пропускаем файл с логом.
"""
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("downloader")

# Расширения по умолчанию для неизвестных типов
EXT_BY_MIME_HINT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
}


def _safe_filename(name):
    """Зачистить имя файла от недопустимых символов Windows."""
    if not name:
        return "file"
    bad = '<>:"/\\|?*'
    cleaned = "".join(c if c not in bad else "_" for c in name)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "file"


def _guess_ext(url, content_type=""):
    if content_type:
        for k, v in EXT_BY_MIME_HINT.items():
            if k in content_type:
                return v
    path = urllib.parse.urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    if ext and len(ext) <= 5:
        return ext if ext.startswith(".") else "." + ext
    return ".bin"


def download_url(url, dest_dir, filename=None, timeout=60):
    """Скачать файл по URL в dest_dir. Вернуть путь или None.

    filename — имя файла; если не задано, берём из URL.
    """
    if not url:
        return None
    os.makedirs(dest_dir, exist_ok=True)
    # Определим имя файла
    if not filename:
        candidate = os.path.basename(urllib.parse.urlparse(url).path)
        filename = _safe_filename(candidate) or "download"
    else:
        filename = _safe_filename(filename)

    # уберём небезопасные пути (папки в имени)
    filename = filename.replace("/", "_").replace("\\", "_")
    dest = os.path.join(dest_dir, filename)

    req = urllib.request.Request(url, headers={"User-Agent": "Archivium/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "")
    except (urllib.error.URLError, OSError) as e:
        log.warning("Failed to download %s: %s", url, e)
        return None

    # переименуем если расширение не то
    if not os.path.splitext(dest)[1]:
        dest += _guess_ext(url, content_type)

    with open(dest, "wb") as f:
        f.write(data)
    log.info("Downloaded %s -> %s (%d bytes)", url, dest, len(data))
    return dest


def download_attachment(att, dest_dir, client=None, chat_id=None, mid=None):
    """Скачать одно вложение. att — объект attachment из сообщения.

    client — MaxClient (нужен для видео). Возвращает путь к файлу или None.
    """
    atype = att.get("type")
    payload = att.get("payload") or {}
    if atype == "image":
        return download_url(payload.get("url"), dest_dir,
                            filename="%s_%s%s" % (
                                mid, payload.get("photo_id") or "img",
                                _guess_ext(payload.get("url") or "", "image/jpeg"),
                            ))
    if atype == "file":
        name = att.get("filename") or payload.get("url") or "file"
        base = os.path.splitext(name)[0] or "file"
        ext = os.path.splitext(name)[1] or _guess_ext(payload.get("url") or "")
        return download_url(payload.get("url"), dest_dir,
                            filename="%s_%s%s" % (mid, _safe_filename(base), ext))
    if atype == "audio":
        return download_url(payload.get("url"), dest_dir,
                            filename="%s_audio%s" % (
                                mid, _guess_ext(payload.get("url") or "", "audio/mpeg")))
    if atype == "video":
        return _download_video(att, dest_dir, client, chat_id, mid)
    if atype in ("share", "sticker", "location", "contact", "inline_keyboard"):
        log.debug("Skipping attachment type %s (no downloadable file)", atype)
        return None
    log.debug("Unknown attachment type %s, skipping", atype)
    return None


def _pick_video_url(details):
    """Выбрать лучший mp4-URL из VideoAttachmentDetails."""
    urls = (details or {}).get("urls") or {}
    for pref in ("mp4_1080", "mp4_720", "mp4_480", "mp4_360"):
        if urls.get(pref):
            return urls[pref]
    for v in urls.values():
        if isinstance(v, str) and v:
            return v
    return None


def _download_video(att, dest_dir, client, chat_id, mid):
    token = (att.get("payload") or {}).get("token")
    if not client or not token:
        log.debug("Video without token or client, skip")
        return None
    try:
        details = client.get_video_details(token)
    except Exception:
        log.exception("Failed to get video details for token %s", token)
        return None
    url = _pick_video_url(details)
    if not url:
        log.warning("No playable URL for video token %s", token)
        return None
    return download_url(url, dest_dir,
                        filename="%s_video.mp4" % mid)


def get_dest_dir(data_dir, chat_id):
    """Папка для вложений чата: <data_dir>/attachments/<chat_id>/"""
    return os.path.join(data_dir, "attachments", str(chat_id))