# -*- coding: utf-8 -*-
"""Загрузка токена из переменной окружения или файла .env (мини-парсер).

Не тянем python-dotenv, чтобы проект работал на голой стандартной библиотеке.
"""
import os


def _load_dotenv(path=".env"):
    """Примитивный парсер .env (без кавычек/продолжений). Достаточно для токена."""
    if not os.path.exists(path):
        return {}
    result = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def get_token():
    """Вернуть токен бота: приоритет — переменная окружения, затем .env."""
    env_token = os.environ.get("BOT_TOKEN", "").strip()
    if env_token:
        return env_token
    return _load_dotenv().get("BOT_TOKEN", "").strip()