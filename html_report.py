# -*- coding: utf-8 -*-
"""Генерация красивого HTML-отчёта по чату/каналу.

Самостоятельный .html-файл с встроенными стилями и JS-графиками
(без CDN и внешних зависимостей — работает офлайн). 

Содержит:
  - сводные показатели;
  - гистограмму активности по дням (Canvas);
  - топ авторов;
  - ключевые слова (облако/tоп);
  - последние посты и комментарии.
"""
import datetime
import html
import os


def _human_date(ts_ms):
    if not ts_ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return ""


def _esc(s):
    return html.escape(str(s if s is not None else ""))


def _bar_chart_js(div_id, labels, values, color="#4f6ef7"):
    """JS для отрисовки простой горизонтальной гистограммы на Canvas."""
    data = [(labels[i], values[i]) for i in range(min(len(labels), len(values)))]
    return {
        "div_id": div_id,
        "data": data,
        "color": color,
    }


def build_html_report(store, chat_id, stat, path):
    """Собрать HTML-отчёт. Возвращает путь к файлу."""
    try:
        chat = store.get_chat(chat_id)
    except Exception:
        chat = None
    title = chat["title"] if chat else None

    # Топ авторов (для графика) — берём посты, а если мало, добавим комментаторов
    authors = stat["top_post_authors"][:12] or []
    words = stat["top_words"][:25] or []

    # Последние посты
    recent_posts = []
    try:
        cur = store.conn.execute(
            "SELECT timestamp, mid, sender_name, text, url FROM posts "
            "WHERE chat_id=? ORDER BY timestamp DESC LIMIT 15", (chat_id,)
        )
        recent_posts = cur.fetchall()
    except Exception:
        pass

    # Последние комментарии
    recent_comments = []
    try:
        cur = store.conn.execute(
            "SELECT timestamp, mid, comment_mid, sender_name, text FROM comments "
            "WHERE chat_id=? ORDER BY timestamp DESC LIMIT 15", (chat_id,)
        )
        recent_comments = cur.fetchall()
    except Exception:
        pass

    # -------- сборка HTML --------
    days_labels = [d for d, _ in stat["days"]]
    days_vals = [c for _, c in stat["days"]]
    author_labels = [a for a, _ in authors]
    author_vals = [c for _, c in authors]

    def posts_rows():
        out = []
        for r in recent_posts:
            ts, mid, name, text, url = r
            snippet = (text or "")[:180]
            out.append(
                "<tr><td>%s</td><td>%s</td><td>%s</td><td><a href='%s'>%s</a></td></tr>"
                % (_esc(_human_date(ts)), _esc(name or ""), _esc(snippet), _esc(url or ""), _esc(mid))
            )
        return "\n".join(out) or "<tr><td colspan='4'>Нет постов</td></tr>"

    def comments_rows():
        out = []
        for r in recent_comments:
            ts, mid, cmid, name, text = r
            snippet = (text or "")[:180]
            out.append(
                "<tr><td>%s</td><td>%s</td><td><a href='#'>%s</a></td><td>%s</td></tr>"
                % (_esc(_human_date(ts)), _esc(name or ""), _esc(cmid), _esc(snippet))
            )
        return "\n".join(out) or "<tr><td colspan='4'>Нет комментариев</td></tr>"

    html_doc = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<title>Отчёт %%TITLE%%</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
         background: #f4f6fb; color: #1c2333; padding: 24px; }
  .wrap { max-width: 1000px; margin: 0 auto; }
  h1 { font-size: 24px; margin-bottom: 4px; }
  .sub { color: #6b7280; margin-bottom: 20px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit,minmax(160px,1fr)); gap: 12px; margin-bottom: 24px; }
  .card { background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  .card .num { font-size: 28px; font-weight: 700; color: #4f6ef7; }
  .card .label { font-size: 13px; color: #6b7280; margin-top: 4px; }
  section { background: #fff; border-radius: 12px; padding: 18px; margin-bottom: 16px;
            box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  section h2 { font-size: 16px; margin-bottom: 12px; border-bottom: 1px solid #f0f2f7; padding-bottom: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #f0f2f7; }
  th { color: #6b7280; font-weight: 600; }
  canvas { width: 100%; height: 260px; }
  .chip { display:inline-block; background:#eef2ff; color:#4f6ef7; border-radius:16px;
          padding: 4px 10px; margin: 3px; font-size: 13px; }
  .chip b { font-weight:700; }
  @media print { body { background:#fff; } .no-print { display:none; } }
</style>
</head>
<body>
<div class="wrap">
  <h1>Отчёт: %%TITLE%%</h1>
  <div class="sub">Archivium &middot; Канал/чат %%CHATID%% &middot; период %%PERIOD%%</div>

  <div class="cards">
    <div class="card"><div class="num">%%POSTS%%</div><div class="label">Постов всего</div></div>
    <div class="card"><div class="num">%%COMMENTS%%</div><div class="label">Комментариев</div></div>
    <div class="card"><div class="num">%%DAYS%%</div><div class="label">Активных дней</div></div>
    <div class="card"><div class="num">%%AVG%%</div><div class="label">Постов/день (сред.)</div></div>
  </div>

  <section>
    <h2>Активность по дням</h2>
    <div id="chart_days"></div>
  </section>

  <section>
    <h2>Топ авторов</h2>
    <div id="chart_authors"></div>
    <p style="font-size:12px;color:#6b7280;margin-top:8px">Число сообщений по авторам</p>
  </section>

  <section>
    <h2>Ключевые слова</h2>
    <div>%%WORDS%%</div>
  </section>

  <section>
    <h2>Последние посты</h2>
    <table><thead><tr><th>Дата</th><th>Автор</th><th>Текст</th><th>Ссылка</th></tr></thead>
    <tbody>%%POSTS_TABLE%%</tbody></table>
  </section>

  <section>
    <h2>Последние комментарии</h2>
    <table><thead><tr><th>Дата</th><th>Автор</th><th>Комм.</th><th>Текст</th></tr></thead>
    <tbody>%%COMMENTS_TABLE%%</tbody></table>
  </section>
</div>

<script>
function drawBars(id, data, color) {
  var c = document.getElementById(id); if (!c) return;
  var ctx = c.getContext('2d');
  var dpr = window.devicePixelRatio || 1;
  var W = c.clientWidth || 600, H = 260;
  c.width = W * dpr; c.height = H * dpr; ctx.scale(dpr, dpr);
  if (!data.length) { return; }
  var max = 0; data.forEach(function(d){ if(d[1]>max) max=d[1]; }); max = max || 1;
  var padL = 10, padR = 10, padT = 10, padB = 24;
  var bw = (W - padL - padR) / data.length;
  ctx.font = '11px sans-serif';
  ctx.fillStyle = '#6b7280';
  data.forEach(function(d, i){
    var h = ((H - padT - padB) * d[1]) / max;
    var x = padL + i * bw, y = H - padB - h;
    ctx.fillStyle = color;
    ctx.fillRect(x + 1, y, bw - 2, h);
    ctx.fillStyle = '#6b7280';
    // подписи
    var lab = String(d[0]);
    if (data.length > 24) lab = lab.slice(0,2);
    ctx.save(); ctx.translate(x + bw/2, H - 14); ctx.rotate(-0.6);
    ctx.fillText(lab, -20, 0); ctx.restore();
    if (data.length <= 24) { ctx.fillText(d[1], x + bw/2 - 4, y - 4); }
  });
}
window.addEventListener('load', function(){
  drawBars('chart_days', %%DAYS_JSON%%, '#4f6ef7');
  drawBars('chart_authors', %%AUTHORS_JSON%%, '#10b981');
});
</script>
</body>
</html>"""

    import json as _json
    replacements = {
        "%%TITLE%%": _esc(title or str(chat_id)),
        "%%CHATID%%": _esc(str(chat_id)),
        "%%PERIOD%%": "%s — %s" % (_human_date(stat["first_ts"]), _human_date(stat["last_ts"])),
        "%%POSTS%%": str(stat["total_posts"]),
        "%%COMMENTS%%": str(stat["total_comments"]),
        "%%DAYS%%": str(len(stat["days"])),
        "%%AVG%%": ("%.1f" % stat["avg_per_day"]) if stat["avg_per_day"] else "0",
        "%%DAYS_JSON%%": _json.dumps([[d, c] for d, c in stat["days"]], ensure_ascii=False),
        "%%AUTHORS_JSON%%": _json.dumps([[a, c] for a, c in authors], ensure_ascii=False),
        "%%WORDS%%": "".join(
            '<span class="chip">%s <b>%s</b></span>' % (_esc(w), c) for w, c in words
        ) or "—",
        "%%POSTS_TABLE%%": posts_rows(),
        "%%COMMENTS_TABLE%%": comments_rows(),
    }
    for k, v in replacements.items():
        html_doc = html_doc.replace(k, v)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return path


def build_html_report_path(store, chat_id, stat, data_dir):
    try:
        chat = store.get_chat(chat_id)
    except Exception:
        chat = None
    title = chat["title"] if chat else None
    safe_title = "".join(c for c in (title or str(chat_id)) if c.isalnum() or c in " _-") or str(chat_id)
    path = os.path.join(data_dir, "%s_%s_report.html" % (chat_id, safe_title))
    return build_html_report(store, chat_id, stat, path)