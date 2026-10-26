# -*- coding: utf-8 -*-
"""Тема оформления (цветовая схема) для GUI Archivium.

Централизованное место всех цветов и стилей. Применяется через ttk.Style
при запуске приложения.

Палитра — тёмная сине-графитовая с акцентным фиолетово-голубым (современно,
удобно читается, не утомляет).
"""
import tkinter as tk
from tkinter import ttk

# ---------------- Палитра ----------------
BG = "#111827"            # основной фон (тёмно-графит)
BG_LIGHT = "#1F2937"      # фон панелей/карточек
BG_HOVER = "#2D3748"      # ховер строк таблицы
FG = "#E5E7EB"            # основной текст (светлый)
FG_MUTED = "#9CA3AF"      # приглушённый текст
FG_DIM = "#6B7280"        # подсказки
ACCENT = "#6366F1"        # акцент (индиго)
ACCENT_LIGHT = "#818CF8"  # акцент светлее
ACCENT_DARK = "#4F46E5"   # акцент для нажатий
GREEN = "#10B981"         # успех / бот работает
RED = "#EF4444"           # ошибка / стоп
YELLOW = "#F59E0B"        # предупреждение
BORDER = "#374151"        # границы
SELECT = "#4F46E5"        # выделенное в таблицах

# Цвета вкладок / редакторов текста
TEXT_BG = "#1F2937"
TEXT_FG = "#E5E7EB"

# ---------------- Применение темы ----------------
def apply_theme(root):
    """Применить тёмную тему ко всему приложению."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")  # clam — расширяемая тема, надёжна на Windows
    except tk.TclError:
        pass

    # Базовый (родительский) стиль
    root.configure(bg=BG)

    # --- Общие виджеты ---
    style.configure(".", background=BG, foreground=FG,
                    fieldbackground=TEXT_BG, font=("Segoe UI", 10))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("TLabelframe", background=BG, foreground=FG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=FG_MUTED,
                    font=("Segoe UI", 10, "bold"))
    style.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=(4, 4, 4, 0))
    style.configure("TNotebook.Tab", background=BG_LIGHT, foreground=FG,
                    padding=(14, 8), font=("Segoe UI", 10))
    style.map("TNotebook.Tab",
              background=[("selected", ACCENT_DARK), ("active", BG_HOVER)],
              foreground=[("selected", "#FFFFFF")])

    # --- Кнопки ---
    style.configure("TButton",
                    background=BG_LIGHT, foreground=FG,
                    bordercolor=BORDER, lightcolor=BG_LIGHT, darkcolor=BG_LIGHT,
                    padding=(12, 6), font=("Segoe UI", 10))
    style.map("TButton",
              background=[("pressed", ACCENT_DARK), ("active", ACCENT)],
              foreground=[("pressed", "#FFFFFF"), ("active", "#FFFFFF")])
    # Акцентная кнопка (основное действие)
    style.configure("Accent.TButton",
                    background=ACCENT, foreground="#FFFFFF",
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
                    padding=(14, 7), font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton",
              background=[("pressed", ACCENT_DARK), ("active", ACCENT_LIGHT)],
              foreground=[("pressed", "#FFFFFF"), ("active", "#FFFFFF")])

    # --- Поля ввода ---
    style.configure("TEntry", fieldbackground=TEXT_BG, foreground=TEXT_FG,
                    insertcolor=FG, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, padding=4)
    style.map("TEntry",
              fieldbackground=[("focus", "#273449")],
              bordercolor=[("focus", ACCENT)])

    # --- Комбобоксы ---
    style.configure("TCombobox", fieldbackground=TEXT_BG, foreground=TEXT_FG,
                    background=BG_LIGHT, arrowcolor=FG, bordercolor=BORDER,
                    padding=4)
    style.map("TCombobox",
              fieldbackground=[("readonly", TEXT_BG), ("focus", "#273449")],
              bordercolor=[("focus", ACCENT)],
              selectbackground=[("readonly", TEXT_BG)],
              selectforeground=[("readonly", TEXT_FG)])

    # --- Чекбоксы ---
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.map("TCheckbutton",
              background=[("active", BG)],
              indicatorcolor=[("selected", ACCENT)])

    # --- Таблицы (Treeview) ---
    style.configure("Treeview", background=TEXT_BG, fieldbackground=TEXT_BG,
                    foreground=TEXT_FG, bordercolor=BORDER, rowheight=26)
    style.map("Treeview",
              background=[("selected", SELECT)],
              foreground=[("selected", "#FFFFFF")])
    style.configure("Treeview.Heading", background=BG_LIGHT, foreground=FG_MUTED,
                    font=("Segoe UI", 10, "bold"), padding=6)
    style.map("Treeview.Heading",
              background=[("active", BG_HOVER)])
    style.configure("Treeview", font=("Segoe UI", 10))

    # --- Текстовые поля (лог/отчёты) с прокруткой ---
    for widget in (root.winfo_children(),):
        pass  # текстовые виджеты настраиваются при создании

    # --- Статусбар ---
    style.configure("Status.TLabel",
                    background=BG_LIGHT, foreground=FG_MUTED, padding=(8, 4))

    # --- Scrollbar ---
    style.configure("Vertical.TScrollbar", background=BG_LIGHT,
                    troughcolor=BG, bordercolor=BG, arrowcolor=FG, width=12)
    style.map("Vertical.TScrollbar",
              background=[("active", ACCENT)])


def style_text_widget(widget):
    """Применить стиль к tk.Text-виджету (лого, отчёты)."""
    widget.configure(bg=TEXT_BG, fg=TEXT_FG, insertbackground=FG,
                     relief="flat", borderwidth=0, padx=8, pady=8,
                     font=("Consolas", 10))