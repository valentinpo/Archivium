# -*- coding: utf-8 -*-
"""Графический интерфейс (Tkinter) для Archivium — архиватора контента MAX.

Вкладки:
  - Бот        : запуск/остановка long polling, живой лог событий
  - Чаты       : таблица выгруженных чатов/каналов, ручная выгрузка
  - Отчёты     : просмотр статистики по выбранному чату, Excel и HTML-отчёт
  - Поиск      : поиск по постам и комментариям
  - Настройки  : токен, флаги (вложения/Excel), сохранение в .env

Long polling выполняется в фоновом потоке, чтобы не блокировать UI.
Запуск:  python gui.py
"""
import logging
import queue
import threading

import tkinter as tk
from tkinter import ttk, messagebox

from bot import MaxDumperBot
from dotenv_status import get_token, _load_dotenv
from store import PostStore
from stats import StatsBuilder
from excel_export import build_chat_excel_path
from search import Searcher
from html_report import build_html_report_path
import theme

log = logging.getLogger("gui")

# Название приложения (в заголовке окна и диалоге «О программе»)
APP_NAME = "Archivium"

# период автообновления списка чатов (мс)
CHAT_REFRESH_MS = 8000


class MaxGuiApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1000x680")
        self.root.minsize(780, 540)
        # Тёмная тема
        theme.apply_theme(root)

        self.bot = None
        self.bot_thread = None
        self.ui_queue = queue.Queue()   # поток -> UI

        self._build_header()
        self._build_menu()

        # Notebook с вкладками
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)

        self.tab_bot = ttk.Frame(self.notebook)
        self.tab_chats = ttk.Frame(self.notebook)
        self.tab_reports = ttk.Frame(self.notebook)
        self.tab_search = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_bot, text="Бот")
        self.notebook.add(self.tab_chats, text="Чаты")
        self.notebook.add(self.tab_reports, text="Отчёты")
        self.notebook.add(self.tab_search, text="Поиск")
        self.notebook.add(self.tab_settings, text="Настройки")

        self._build_tab_bot()
        self._build_tab_chats()
        self._build_tab_reports()
        self._build_tab_search()
        self._build_tab_settings()

        self._build_statusbar()

        # Обработчик событий из фонового потока
        self.root.after(100, self._poll_ui_queue)
        # Автообновление списка чатов
        self.root.after(CHAT_REFRESH_MS, self._auto_refresh_chats)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================================================================
    # Меню
    # ==================================================================
    def _build_header(self):
        """Шапка приложения с названием и подзаголовком."""
        header = tk.Frame(self.root, bg=theme.ACCENT_DARK)
        header.pack(fill="x")
        title = tk.Label(header, text="Archivium", bg=theme.ACCENT_DARK, fg="#FFFFFF",
                         font=("Segoe UI", 16, "bold"), padx=16, pady=6)
        title.pack(side="left")
        subtitle = tk.Label(header, text="архив и аналитика чатов и каналов MAX",
                            bg=theme.ACCENT_DARK, fg=theme.ACCENT_LIGHT,
                            font=("Segoe UI", 9))
        subtitle.pack(side="left", padx=(4, 0), pady=(0, 0))

    def _build_menu(self):
        menubar = tk.Menu(self.root,
                          bg=theme.BG_LIGHT, fg=theme.FG,
                          activebackground=theme.ACCENT, activeforeground="#FFFFFF")
        filemenu = tk.Menu(menubar, tearoff=0,
                           bg=theme.BG_LIGHT, fg=theme.FG,
                           activebackground=theme.ACCENT, activeforeground="#FFFFFF")
        filemenu.add_command(label="Выход", command=self._on_close)
        menubar.add_cascade(label="Файл", menu=filemenu)
        helpmenu = tk.Menu(menubar, tearoff=0,
                           bg=theme.BG_LIGHT, fg=theme.FG,
                           activebackground=theme.ACCENT, activeforeground="#FFFFFF")
        helpmenu.add_command(label="О программе", command=self._show_about)
        menubar.add_cascade(label="Справка", menu=helpmenu)
        self.root.config(menu=menubar)

    def _show_about(self):
        messagebox.showinfo(
            "О программе",
            "%s — архив контента чатов и каналов MAX\n\n"
            "Выгрузка постов и комментариев, статистика и отчёты.\n"
            "Бот должен быть администратором чата/канала." % APP_NAME,
        )

    # ==================================================================
    # Вкладка «Бот»
    # ==================================================================
    def _build_tab_bot(self):
        f = self.tab_bot
        top = ttk.Frame(f)
        top.pack(fill="x", padx=8, pady=8)
        self.btn_start = ttk.Button(top, text="▶ Запустить бота", command=self._start_bot,
                                style="Accent.TButton")
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(top, text="■ Остановить", command=self._stop_bot, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.lbl_status = ttk.Label(top, text="● Бот остановлен", foreground=theme.FG_DIM,
                                    font=("Segoe UI", 10, "bold"))
        self.lbl_status.pack(side="left", padx=12)

        # ---------- Журнал событий ----------
        logframe = ttk.LabelFrame(f, text="Журнал событий")
        logframe.pack(fill="both", expand=True, padx=8, pady=8)
        logbar = ttk.Frame(logframe)
        logbar.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Button(logbar, text="📋 Копировать всё",
                   command=self._copy_log_all).pack(side="left")
        ttk.Button(logbar, text="Очистить журнал",
                   command=self._clear_log).pack(side="left", padx=6)
        ttk.Label(logbar, text="Можно выделить текст и скопировать (Ctrl+C или правая кнопка)",
                  foreground="#888").pack(side="left", padx=12)

        self.log_text = tk.Text(logframe, height=18, wrap="word", undo=True)
        theme.style_text_widget(self.log_text)
        self.log_text.configure(state="normal")
        sb = ttk.Scrollbar(logframe, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        # защита от ручного редактирования журнала (но разрешаем выделение/копирование)
        self.log_text.bind("<Key>", self._log_block_keys)
        self.log_text.bind("<Control-a>", self._log_select_all)
        # контекстное меню
        self.log_cm = tk.Menu(self.root, tearoff=0)
        self.log_cm.add_command(label="Копировать выделенное", command=self._copy_log_selection)
        self.log_cm.add_command(label="Копировать всё", command=self._copy_log_all)
        self.log_cm.add_separator()
        self.log_cm.add_command(label="Очистить журнал", command=self._clear_log)
        self.log_text.bind("<Button-3>", self._show_log_menu)
        self.log_text.bind("<Button-2>", self._show_log_menu)

    # ==================================================================
    # Вкладка «Чаты»
    # ==================================================================
    def _build_tab_chats(self):
        f = self.tab_chats
        top = ttk.Frame(f)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Button(top, text="⟳ Обновить список", command=self._refresh_chats).pack(side="left")
        self.btn_dump_manual = ttk.Button(top, text="Выгрузить выбранный чат",
                                          command=self._dump_manual, state="disabled")
        self.btn_dump_manual.pack(side="left", padx=6)
        self.btn_dump_manual_noatt = ttk.Button(top, text="Выгрузка без вложений",
                                                command=self._dump_manual_noatt, state="disabled")
        self.btn_dump_manual_noatt.pack(side="left", padx=6)

        # Таблица чатов
        table_frame = ttk.Frame(f)
        table_frame.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("id", "тип", "название", "постов", "коммент")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        headers = {"id": "Chat ID", "тип": "Тип", "название": "Название",
                   "постов": "Постов", "коммент": "Коммент."}
        widths = {"id": 90, "тип": 70, "название": 300, "постов": 60, "коммент": 70}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="w" if c in ("id", "тип", "название") else "center")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_manual_buttons())

        # Итоговая строка
        self.lbl_chats_total = ttk.Label(f, text="")
        self.lbl_chats_total.pack(anchor="w", padx=10, pady=(0, 6))

    def _update_manual_buttons(self):
        sel = self.tree.selection()
        state = "normal" if sel else "disabled"
        self.btn_dump_manual.configure(state=state)
        self.btn_dump_manual_noatt.configure(state=state)

    def _selected_chat_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        item = self.tree.item(sel[0])
        try:
            return int(item["values"][0])
        except (ValueError, IndexError, TypeError):
            return None

    # ==================================================================
    # Вкладка «Отчёты»
    # ==================================================================
    def _build_tab_reports(self):
        f = self.tab_reports
        top = ttk.Frame(f)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Чат:").pack(side="left")
        self.cmb_report_chat = ttk.Combobox(top, width=14, state="readonly")
        self.cmb_report_chat.pack(side="left", padx=6)
        ttk.Button(top, text="Показать отчёт", command=self._show_report).pack(side="left", padx=6)
        self.btn_export_xlsx = ttk.Button(top, text="Собрать Excel-отчёт",
                                          command=self._export_xlsx, state="disabled")
        self.btn_export_xlsx.pack(side="left", padx=6)
        self.btn_export_html = ttk.Button(top, text="HTML-отчёт",
                                          command=self._export_html, state="disabled")
        self.btn_export_html.pack(side="left", padx=6)

        # Просмотр
        view = ttk.LabelFrame(f, text="Статистика")
        view.pack(fill="both", expand=True, padx=8, pady=6)
        self.report_text = tk.Text(view, height=20, state="disabled", wrap="word")
        theme.style_text_widget(self.report_text)
        sb = ttk.Scrollbar(view, command=self.report_text.yview)
        self.report_text.configure(yscrollcommand=sb.set)
        self.report_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ==================================================================
    # Вкладка «Поиск»
    # ==================================================================
    def _build_tab_search(self):
        f = self.tab_search
        top = ttk.Frame(f)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Текст:").pack(side="left")
        self.var_search_q = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.var_search_q, width=24)
        ent.pack(side="left", padx=4)
        ent.bind("<Return>", lambda e: self._do_search())

        self.var_search_author = tk.StringVar()
        ttk.Label(top, text="Автор:").pack(side="left", padx=(10, 0))
        ttk.Entry(top, textvariable=self.var_search_author, width=14).pack(side="left", padx=4)

        ttk.Button(top, text="Найти", command=self._do_search).pack(side="left", padx=6)
        ttk.Button(top, text="Сброс", command=self._clear_search).pack(side="left")

        # фильтр по чату
        f2 = ttk.Frame(f)
        f2.pack(fill="x", padx=8)
        ttk.Label(f2, text="Чат:").pack(side="left")
        self.cmb_search_chat = ttk.Combobox(f2, width=18)
        self.cmb_search_chat.pack(side="left", padx=4)
        ttk.Label(f2, text="Период (ГГГГ-ММ-ДД):").pack(side="left", padx=(12, 0))
        self.var_date_from = tk.StringVar()
        ttk.Entry(f2, textvariable=self.var_date_from, width=11).pack(side="left", padx=4)
        ttk.Label(f2, text="—").pack(side="left")
        self.var_date_to = tk.StringVar()
        ttk.Entry(f2, textvariable=self.var_date_to, width=11).pack(side="left", padx=4)

        # результаты
        res = ttk.Frame(f)
        res.pack(fill="both", expand=True, padx=8, pady=6)
        self.search_text = tk.Text(res, height=18, state="disabled", wrap="word")
        theme.style_text_widget(self.search_text)
        sb = ttk.Scrollbar(res, command=self.search_text.yview)
        self.search_text.configure(yscrollcommand=sb.set)
        self.search_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _do_search(self):
        query = self.var_search_q.get().strip() or None
        author = self.var_search_author.get().strip() or None
        chat_id = self._search_chat_id()
        date_from = self.var_date_from.get().strip() or None
        date_to = self.var_date_to.get().strip() or None
        if not (query or author):
            self._set_search_text("Укажите текст для поиска или имя автора.")
            return
        store = PostStore()
        try:
            searcher = Searcher(store)
            res = searcher.search(query=query, chat_id=chat_id, author=author,
                                  date_from=date_from, date_to=date_to, limit=200)
        except ValueError as e:
            self._set_search_text("Ошибка ввода: %s" % e)
            store.close()
            return
        except Exception as e:
            self._set_search_text("Ошибка поиска: %s" % e)
            store.close()
            return
        store.close()

        lines = []
        lines.append("== Посты: %d ==" % len(res["posts"]))
        for r in res["posts"]:
            lines.append("[%d] %s | %s" % (
                r["chat_id"], self._human_date(r["timestamp"]), r["sender_name"] or "-"))
            lines.append("   " + ((r["text"] or "")[:300]))
            lines.append("")
        lines.append("== Комментарии: %d ==" % len(res["comments"]))
        for r in res["comments"]:
            lines.append("[%d] %s | %s (к посту %s)" % (
                r["chat_id"], self._human_date(r["timestamp"]),
                r["sender_name"] or "-", r["mid"]))
            lines.append("   " + ((r["text"] or "")[:300]))
            lines.append("")
        if not res["posts"] and not res["comments"]:
            lines.append("Ничего не найдено.")
        self._set_search_text("\n".join(lines))

    def _search_chat_id(self):
        sel = self.cmb_search_chat.get()
        if not sel:
            return None
        try:
            return int(sel.split(" — ")[0])
        except (ValueError, IndexError):
            return None

    def _update_search_combobox(self):
        store = PostStore()
        chats = store.list_chats()
        store.close()
        items = ["%s — %s" % (c["chat_id"], c["title"] or "?") for c in chats]
        self.cmb_search_chat["values"] = items

    def _clear_search(self):
        self.var_search_q.set("")
        self.var_search_author.set("")
        self.var_date_from.set("")
        self.var_date_to.set("")
        self.cmb_search_chat.set("")
        self._set_search_text("")

    def _set_search_text(self, text):
        self.search_text.configure(state="normal")
        self.search_text.delete("1.0", "end")
        self.search_text.insert("1.0", text)
        self.search_text.configure(state="disabled")

    @staticmethod
    def _human_date(ts):
        import datetime
        if not ts:
            return "-"
        try:
            return datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OverflowError, OSError):
            return "-"

    # ==================================================================
    # Вкладка «Настройки»
    # ==================================================================
    def _build_tab_settings(self):
        f = self.tab_settings
        box = ttk.LabelFrame(f, text="Бот")
        box.pack(fill="x", padx=8, pady=8)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Токен BOT_TOKEN:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.var_token = tk.StringVar()
        self.ent_token = ttk.Entry(box, textvariable=self.var_token, show="*")
        self.ent_token.grid(row=0, column=1, sticky="we", padx=6)
        btn_show = ttk.Button(box, text="Показать", command=self._toggle_token_vis)
        btn_show.grid(row=0, column=2, padx=6)
        ttk.Label(box, text="Скопируйте токен со платформы MAX и вставьте сюда (Ctrl+V или правая кнопка → Вставить).",
                  foreground="#888").grid(row=1, column=1, sticky="w", padx=6, pady=(0, 6))
        # контекстное меню (правая кнопка) для вставки/копирования
        self._bind_entry_context_menu(self.ent_token)

        opts = ttk.LabelFrame(f, text="Параметры выгрузки")
        opts.pack(fill="x", padx=8, pady=4)
        self.var_attachments = tk.BooleanVar(value=True)
        self.var_excel = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Скачивать вложения постов", variable=self.var_attachments).pack(anchor="w", padx=8, pady=2)
        ttk.Checkbutton(opts, text="Формировать Excel-отчёт", variable=self.var_excel).pack(anchor="w", padx=8, pady=2)

        self.lbl_downloads = ttk.Label(f, text="Папка выгрузок: exports/")
        self.lbl_downloads.pack(anchor="w", padx=10, pady=2)

        btns = ttk.Frame(f)
        btns.pack(fill="x", padx=8, pady=8)
        ttk.Button(btns, text="Сохранить настройки", command=self._save_settings).pack(side="left")
        ttk.Button(btns, text="Очистить БД (посты/комментарии)",
                   command=self._reset_db).pack(side="left", padx=6)
        self._load_settings()

    # ==================================================================
    # Статусбар
    # ==================================================================
    def _build_statusbar(self):
        self.statusbar = ttk.Label(self.root, text="Готово", style="Status.TLabel",
                                   anchor="w")
        self.statusbar.pack(fill="x", side="bottom")

    # ==================================================================
    # Логика бота
    # ==================================================================
    def _start_bot(self):
        token = self.var_token.get().strip()
        if not token:
            messagebox.showwarning("Нет токена", "Введите токен бота в настройках.")
            self.notebook.select(self.tab_settings)
            return
        if self.bot is not None and self.bot_thread and self.bot_thread.is_alive():
            messagebox.showinfo("Уже запущен", "Бот уже работает.")
            return

        self.bot = MaxDumperBot(
            token,
            download_attachments=self.var_attachments.get(),
            on_log=self.ui_queue.put,
        )
        if not self.var_excel.get():
            self.bot._build_excel_report = lambda chat_id: None

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.lbl_status.configure(text="● Бот работает…", foreground=theme.GREEN)
        self.statusbar.configure(text="Long polling активен")

        self.bot_thread = threading.Thread(target=self.bot.run, daemon=True)
        self.bot_thread.start()
        self._append_log("Bot запущен.")

    def _stop_bot(self):
        if self.bot:
            self.bot.stop()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.lbl_status.configure(text="● Бот остановлен", foreground=theme.FG_DIM)
        self.statusbar.configure(text="Остановлен")
        self._append_log("Bot остановлен.")

    # ==================================================================
    # Чаты
    # ==================================================================
    def _refresh_chats(self, preserve_selection=False):
        store = PostStore()
        chats = store.list_all_chats()
        store.close()
        # сохраним текущее выделение (для автообновления)
        sel = self.tree.selection()
        sel_ids = set()
        if preserve_selection and sel:
            for i in sel:
                v = self.tree.item(i)["values"]
                try:
                    sel_ids.add(int(v[0]))
                except (ValueError, IndexError, TypeError):
                    pass
        for item in self.tree.get_children():
            self.tree.delete(item)
        total_p = total_c = 0
        s = PostStore()
        to_select = []
        for c in chats:
            np = s.count_posts(c["chat_id"])
            nc = s.count_comments(c["chat_id"])
            total_p += np
            total_c += nc
            iid = self.tree.insert("", "end", values=(
                c["chat_id"], c["chat_type"] or "?",
                c["title"] or "-", np, nc,
            ))
            if c["chat_id"] in sel_ids:
                to_select.append(iid)
        s.close()
        if to_select:
            self.tree.selection_set(to_select)
        self.lbl_chats_total.configure(
            text="Чатов/каналов: %d  |  постов: %d  |  комментариев: %d"
                 % (len(chats), total_p, total_c)
        )
        self._update_report_combobox()

    def _auto_refresh_chats(self):
        """Автоматически обновлять список чатов с интервалом."""
        try:
            self._refresh_chats(preserve_selection=True)
        except Exception:
            pass
        self.root.after(CHAT_REFRESH_MS, self._auto_refresh_chats)

    def _dump_manual(self):
        chat_id = self._selected_chat_id()
        if chat_id is None:
            return
        self._run_manual_dump(chat_id, download=True)

    def _dump_manual_noatt(self):
        chat_id = self._selected_chat_id()
        if chat_id is None:
            return
        self._run_manual_dump(chat_id, download=False)

    def _run_manual_dump(self, chat_id, download):
        token = self.var_token.get().strip()
        if not token:
            messagebox.showwarning("Нет токена", "Введите токен бота в настройках.")
            return
        self.statusbar.configure(text="Выгрузка чата %s…" % chat_id)
        self._append_log("Начинаю ручную выгрузку чата %s (вложения: %s)"
                         % (chat_id, "да" if download else "нет"))

        def work():
            try:
                bot = MaxDumperBot(token, download_attachments=download,
                                   on_log=self.ui_queue.put)
                if not self.var_excel.get():
                    bot._build_excel_report = lambda chat_id: None
                membership = bot.client.check_membership(chat_id)
                if not membership or not membership.get("is_admin"):
                    self.ui_queue.put(("MSG", "Ошибка",
                                       "Бот не является администратором чата %s.\n"
                                       "Выдайте права администратора." % chat_id))
                    self.ui_queue.put(("UI", ("status", "Готово")))
                    return
                bot._dump_history(chat_id)
                self.ui_queue.put(("MSG", "Готово",
                                   "Выгрузка чата %s завершена." % chat_id))
            except Exception as e:
                self.ui_queue.put(("MSG", "Ошибка", "Сбой выгрузки: %s" % e))
            finally:
                self.ui_queue.put(("UI", ("status", "Готово")))
                self.ui_queue.put(("UI", ("refresh_chats", None)))

        threading.Thread(target=work, daemon=True).start()

    # ==================================================================
    # Отчёты
    # ==================================================================
    def _update_report_combobox(self):
        store = PostStore()
        chats = store.list_chats()
        store.close()
        items = ["%s — %s" % (c["chat_id"], c["title"] or "?") for c in chats]
        self.cmb_report_chat["values"] = items
        if items:
            self.cmb_report_chat.current(0)
        self.btn_export_xlsx.configure(state="normal" if items else "disabled")
        self.btn_export_html.configure(state="normal" if items else "disabled")
        self._update_search_combobox()

    def _report_chat_id(self):
        sel = self.cmb_report_chat.get()
        if not sel:
            return None
        try:
            return int(sel.split(" — ")[0])
        except (ValueError, IndexError):
            return None

    def _show_report(self):
        chat_id = self._report_chat_id()
        if chat_id is None:
            return
        store = PostStore()
        try:
            sb = StatsBuilder(store)
            stat = sb.build(chat_id)
            report = self._format_report(chat_id, stat)
            self._set_report_text(report)
        except Exception as e:
            messagebox.showerror("Ошибка", "Не удалось построить отчёт: %s" % e)
        finally:
            store.close()

    def _format_report(self, chat_id, stat):
        lines = []
        chat = PostStore().get_chat(chat_id)
        title = chat["title"] if chat else None
        from excel_export import _human_date
        lines.append("=== Отчёт по чату %s ===" % (title or chat_id))
        lines.append("")
        lines.append("Постов: %d" % stat["total_posts"])
        lines.append("Комментариев: %d" % stat["total_comments"])
        lines.append("Период: %s — %s" % (_human_date(stat["first_ts"]), _human_date(stat["last_ts"])))
        lines.append("Активных дней: %d (в среднем %.2f постов/день)"
                     % (len(stat["days"]), stat["avg_per_day"]))
        lines.append("")
        if stat["top_post_authors"]:
            lines.append("— Топ авторов постов —")
            for i, (name, cnt) in enumerate(stat["top_post_authors"][:10], 1):
                lines.append("  %d. %s — %d" % (i, name, cnt))
            lines.append("")
        if stat["top_comment_authors"]:
            lines.append("— Топ авторов комментариев —")
            for i, (name, cnt) in enumerate(stat["top_comment_authors"][:10], 1):
                lines.append("  %d. %s — %d" % (i, name, cnt))
            lines.append("")
        if stat["top_words"]:
            lines.append("— Ключевые слова —")
            for i, (word, cnt) in enumerate(stat["top_words"][:20], 1):
                lines.append("  %d. %s — %d" % (i, word, cnt))
            lines.append("")
        if stat["attachments"]:
            lines.append("— Типы вложений —")
            for t, cnt in stat["attachments"]:
                lines.append("  %s × %d" % (t, cnt))
        return "\n".join(lines)

    def _set_report_text(self, text):
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", text)
        self.report_text.configure(state="disabled")

    def _export_xlsx(self):
        chat_id = self._report_chat_id()
        if chat_id is None:
            return
        store = PostStore()
        try:
            sb = StatsBuilder(store)
            stat = sb.build(chat_id)
            path = build_chat_excel_path(store, chat_id, stat, store.data_dir)
            messagebox.showinfo("Excel-отчёт", "Сохранено:\n%s" % path)
        except Exception as e:
            messagebox.showerror("Ошибка", "Не удалось собрать Excel: %s" % e)
        finally:
            store.close()

    def _export_html(self):
        chat_id = self._report_chat_id()
        if chat_id is None:
            return
        store = PostStore()
        try:
            sb = StatsBuilder(store)
            stat = sb.build(chat_id)
            path = build_html_report_path(store, chat_id, stat, store.data_dir)
            messagebox.showinfo("HTML-отчёт", "Сохранено:\n%s" % path)
        except Exception as e:
            messagebox.showerror("Ошибка", "Не удалось собрать HTML: %s" % e)
        finally:
            store.close()

    # ==================================================================
    # Настройки
    # ==================================================================
    def _load_settings(self):
        env = _load_dotenv()
        self.var_token.set(env.get("BOT_TOKEN", ""))
        # читаем флаги из config если есть
        try:
            from config import DATA_DIR
            self.lbl_downloads.configure(text="Папка выгрузок: %s/" % DATA_DIR)
        except Exception:
            pass

    def _toggle_token_vis(self):
        if self.ent_token.cget("show") == "*":
            self.ent_token.configure(show="")
        else:
            self.ent_token.configure(show="*")

    def _bind_entry_context_menu(self, entry):
        """Добавить правой кнопке мыши меню: Копировать / Вставить / Выделить всё.

        Стандартная вставка в Tkinter — Ctrl+V, но на Windows пользователи привыкли
        к правому клику → «Вставить». Это меню решает проблему «не могу вставить токен».
        """
        menu = tk.Menu(self.root, tearoff=0)

        def do_copy():
            try:
                entry.event_generate("<<Copy>>")
            except Exception:
                text = entry.selection_get()
                self.root.clipboard_clear()
                self.root.clipboard_append(text)

        def do_paste():
            try:
                entry.event_generate("<<Paste>>")
            except Exception:
                try:
                    text = self.root.clipboard_get()
                    entry.delete(0, "end")
                    entry.insert(0, text)
                except Exception:
                    pass

        def do_select_all():
            entry.selection_range(0, "end")
            entry.icursor("end")

        menu.add_command(label="Копировать", command=do_copy)
        menu.add_command(label="Вставить", command=do_paste)
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=do_select_all)

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        entry.bind("<Button-3>", show_menu)
        entry.bind("<Button-2>", show_menu)  # для некоторых систем

    def _save_settings(self):
        token = self.var_token.get().strip()
        env = _load_dotenv()
        env["BOT_TOKEN"] = token
        lines = ["%s=%s" % (k, v) for k, v in env.items()]
        with open(".env", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            if lines:
                f.write("\n")
        self._append_log("Настройки сохранены в .env")
        messagebox.showinfo("Сохранено", "Настройки сохранены в .env")

    def _reset_db(self):
        if not messagebox.askyesno("Подтверждение",
                                   "Удалить все выгруженные посты и комментарии?\n"
                                   "(база max_posts.db)"):
            return
        import os
        store = PostStore()
        store.close()
        db = os.path.join("exports", "max_posts.db")
        if os.path.exists(db):
            os.remove(db)
        self._append_log("База данных очищена.")
        self._refresh_chats()

    # ==================================================================
    # Лог / очередь
    # ==================================================================
    def _append_log(self, msg):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")

    # ---------------- журнал: копирование и очистка ----------------
    def _copy_log_all(self):
        """Скопировать весь журнал в буфер обмена."""
        content = self.log_text.get("1.0", "end")
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.statusbar.configure(text="Журнал скопирован в буфер обмена")

    def _copy_log_selection(self):
        """Скопировать выделенный фрагмент журнала."""
        try:
            sel = self.log_text.get("sel.first", "sel.last")
        except tk.TclError:
            sel = self.log_text.get("1.0", "end")  # если ничего не выделено — всё
        if sel.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(sel)
            self.statusbar.configure(text="Выделенный фрагмент скопирован")

    def _clear_log(self):
        self.log_text.delete("1.0", "end")
        self.statusbar.configure(text="Журнал очищен")

    def _log_select_all(self, event=None):
        self.log_text.tag_add("sel", "1.0", "end")
        self.log_text.mark_set("insert", "end")
        return "break"

    def _log_block_keys(self, event):
        # разрешаем сочетания с Ctrl (копирование/выделение), блокируем ввод текста
        ctrl = (event.state & 0x4) != 0
        if ctrl and event.keysym.lower() in ("c", "a", "v", "x"):
            if event.keysym.lower() == "c":
                self._copy_log_selection()
            return "break" if event.keysym.lower() in ("v", "x") else None
        # навигационные клавиши разрешаем
        if event.keysym in ("Return", "BackSpace", "Delete",
                            "Left", "Right", "Up", "Down", "Home", "End",
                            "Prior", "Next"):
            return "break"
        return "break"

    def _show_log_menu(self, event):
        try:
            self.log_cm.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_cm.grab_release()

    def _poll_ui_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "MSG":
                    self._append_log("[сообщение] " + str(item[1]))
                    messagebox.showinfo(item[1], item[2])
                elif isinstance(item, tuple) and item and item[0] == "UI":
                    self._handle_ui_cmd(item[1])
                else:
                    self._append_log(str(item))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui_queue)

    def _handle_ui_cmd(self, cmd):
        if not cmd:
            return
        kind = cmd[0]
        if kind == "status":
            self.statusbar.configure(text=cmd[1] if len(cmd) > 1 else "")
        elif kind == "refresh_chats":
            self._refresh_chats()

    def _on_close(self):
        if self.bot:
            self.bot.stop()
        self.root.destroy()


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    root = tk.Tk()
    app = MaxGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()