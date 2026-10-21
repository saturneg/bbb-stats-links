#!/usr/bin/env python3
"""
Генератор статистики BigBlueButton Learning Analytics Dashboard.
Читает learning_dashboard_data.json для каждой сессии и формирует
подробную HTML-страницу: название, даты, участники, активность.

Возможности:
  - Фильтрация мусорных сессий (короткие, без участников, по имени)
  - Ручной список исключений (skip-файл)
  - Сортировка по дате создания (а не по имени папки)
  - Корректная таймзона
  - Аккордеон для таблицы участников
  - Клиентские поиск / фильтры / сортировка без перезагрузки
  - Кнопка копирования списка участников (без модераторов)
  - CLI-режим для очистки старых сессий (--prune)
"""

import argparse
import json
import html
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# --- Настройки ---
BBB_HOST = "https://arazasjuyay.beget.app"
DASHBOARD_DIR = Path("/var/bigbluebutton/learning-dashboard")
OUTPUT_FILE = Path("/var/www/html/bbb-stats/index.html")

# Часовой пояс для отображения дат
TIMEZONE = ZoneInfo("Europe/Moscow")

# Ручной список meeting_id, которые не показывать (по одному на строку)
SKIP_FILE = Path("/usr/local/etc/bbb-stats-skip.txt")

# Пороги отсева мусора
MIN_DURATION_SEC = 60
MIN_USERS = 2
SKIP_NAME_SUBSTRINGS = (
    "test", "тест", "demo", "демо", "проверка", "check",
)


def ts_to_str(ms) -> str:
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(ms / 1000, tz=TIMEZONE).strftime("%d.%m.%Y %H:%M")
    except (ValueError, OSError, TypeError):
        return "—"


def duration_str(start_ms, end_ms) -> str:
    if not start_ms or not end_ms:
        return "—"
    try:
        seconds = int((end_ms - start_ms) / 1000)
    except (TypeError, ValueError):
        return "—"
    if seconds < 0:
        return "—"
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h} ч {m} мин"
    return f"{m} мин"


def duration_seconds(start_ms, end_ms) -> int:
    if not start_ms or not end_ms:
        return 0
    try:
        s = int((end_ms - start_ms) / 1000)
    except (TypeError, ValueError):
        return 0
    return max(s, 0)


def find_data_file(session_dir: Path) -> Path | None:
    try:
        for sub in session_dir.iterdir():
            if sub.is_dir():
                candidate = sub / "learning_dashboard_data.json"
                if candidate.is_file():
                    return candidate
    except OSError:
        return None
    return None


def load_skip_list() -> set[str]:
    if not SKIP_FILE.is_file():
        return set()
    try:
        return {
            line.strip()
            for line in SKIP_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
    except OSError:
        return set()


def collect_user_stats(users: dict) -> list[dict]:
    result = []
    for user in users.values():
        registered = None
        left = None
        for sess_data in user.get("intIds", {}).values():
            for s in sess_data.get("sessions", []):
                r = s.get("registeredOn")
                l = s.get("leftOn")
                if r and (registered is None or r < registered):
                    registered = r
                if l and (left is None or l > left):
                    left = l

        talk = user.get("talk", {})
        result.append({
            "name": user.get("name", "—"),
            "is_moderator": user.get("isModerator", False),
            "registered": ts_to_str(registered),
            "left": ts_to_str(left),
            "duration": duration_str(registered, left),
            "messages": user.get("totalOfMessages", 0),
            "talk_seconds": round(talk.get("totalTime", 0) / 1000),
            "webcams": len(user.get("webcams", [])),
            "raise_hand": len(user.get("raiseHand", [])),
            "reactions": len(user.get("reactions", [])),
            "notes": user.get("totalOfSharedNotes", 0),
            "annotations": user.get("totalOfWhiteboardAnnotations", 0),
            "answers": len(user.get("answers", {})),
        })
    result.sort(key=lambda u: (not u["is_moderator"], u["name"].lower()))
    return result


def build_attendees_list(users: list[dict]) -> str:
    """Список участников БЕЗ модераторов, по одному на строку."""
    names = [u["name"] for u in users if not u["is_moderator"]]
    return "\n".join(names)


def is_junk(session: dict) -> bool:
    if session["disabled"]:
        return True
    if session["users_count"] < MIN_USERS:
        return True
    if session["_duration_sec"] < MIN_DURATION_SEC:
        return True
    name_low = session["name"].lower()
    if any(w in name_low for w in SKIP_NAME_SUBSTRINGS):
        return True
    return False


def collect_sessions() -> list[dict]:
    sessions: list[dict] = []
    if not DASHBOARD_DIR.is_dir():
        return sessions

    skip_ids = load_skip_list()

    for session_dir in DASHBOARD_DIR.iterdir():
        if not session_dir.is_dir():
            continue

        meeting_id = session_dir.name
        if meeting_id in skip_ids:
            continue

        data_file = find_data_file(session_dir)
        if not data_file:
            continue

        token = data_file.parent.name

        try:
            data = json.loads(data_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        created = data.get("createdOn")
        ended = data.get("endedOn")

        if not created:
            try:
                created = int(session_dir.stat().st_mtime * 1000)
            except OSError:
                created = None

        users = data.get("users", {})

        url = (
            f"{BBB_HOST}/learning-analytics-dashboard/"
            f"?meeting={meeting_id}&report={token}&lang=ru"
        )

        users_list = collect_user_stats(users)

        session = {
            "meeting_id": meeting_id,
            "name": data.get("name") or meeting_id,
            "date": ts_to_str(created),
            "ended": ts_to_str(ended),
            "duration": duration_str(created, ended),
            "users_count": len(users),
            "moderators_count": sum(1 for u in users.values() if u.get("isModerator")),
            "polls_count": len(data.get("polls", {})),
            "screenshares_count": len(data.get("screenshares", [])),
            "slides_count": len(data.get("presentationSlides", [])),
            "disabled": data.get("learningDashboardDisabled", False),
            "users": users_list,
            "attendees_text": build_attendees_list(users_list),
            "attendees_count": sum(1 for u in users_list if not u["is_moderator"]),
            "url": url,
            "_created_ms": created or 0,
            "_duration_sec": duration_seconds(created, ended),
        }

        if is_junk(session):
            continue

        sessions.append(session)

    sessions.sort(key=lambda s: s["_created_ms"], reverse=True)
    return sessions


def render_users_table(users: list[dict]) -> str:
    if not users:
        return "<p><em>Участников нет.</em></p>"

    rows = ""
    for u in users:
        role = "Модератор" if u["is_moderator"] else "Участник"
        rows += f"""
        <tr>
            <td>{html.escape(u['name'])}</td>
            <td>{role}</td>
            <td>{html.escape(u['registered'])}</td>
            <td>{html.escape(u['left'])}</td>
            <td>{html.escape(u['duration'])}</td>
            <td>{u['messages']}</td>
            <td>{u['talk_seconds']} с</td>
            <td>{u['webcams']}</td>
            <td>{u['raise_hand']}</td>
            <td>{u['reactions']}</td>
            <td>{u['notes']}</td>
            <td>{u['annotations']}</td>
            <td>{u['answers']}</td>
        </tr>
        """

    return f"""
    <table class="users">
        <thead>
            <tr>
                <th>Имя</th>
                <th>Роль</th>
                <th>Вошёл</th>
                <th>Вышел</th>
                <th>Длительность</th>
                <th>Сообщений</th>
                <th>Речь</th>
                <th>Камер</th>
                <th>Рук</th>
                <th>Реакций</th>
                <th>Заметок</th>
                <th>Аннотаций</th>
                <th>Ответов</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """


def render_html(sessions: list[dict]) -> str:
    cards = ""
    for idx, s in enumerate(sessions):
        disabled_badge = (
            '<span class="badge warn">Дашборд отключён</span>'
            if s["disabled"] else ""
        )

        # Текст для копирования кладём в <textarea> (скрыт), чтобы не ломать HTML
        # экранированием переводов строк
        attendees_escaped = html.escape(s["attendees_text"])

        cards += f"""
        <div class="card"
             data-name="{html.escape(s['name'].lower())}"
             data-mid="{html.escape(s['meeting_id'].lower())}"
             data-users="{s['users_count']}"
             data-ts="{s['_created_ms']}"
             data-dur="{s['_duration_sec']}">
            <h2>{html.escape(s['name'])} {disabled_badge}</h2>
            <div class="when">{html.escape(s['date'])}</div>

            <div class="meta">
                <div><strong>Окончание:</strong> {html.escape(s['ended'])}</div>
                <div><strong>Длительность:</strong> {html.escape(s['duration'])}</div>
                <div><strong>Участников:</strong> {s['users_count']} (модераторов: {s['moderators_count']})</div>
                <div><strong>Опросов:</strong> {s['polls_count']}</div>
                <div><strong>Демонстраций экрана:</strong> {s['screenshares_count']}</div>
                <div><strong>Слайдов:</strong> {s['slides_count']}</div>
                <div class="meeting-id"><strong>Meeting ID:</strong> <code>{html.escape(s['meeting_id'])}</code></div>
            </div>

            <div class="actions">
                <a class="button" href="{html.escape(s['url'])}" target="_blank">
                    Открыть интерактивный дашборд
                </a>
                <button class="btn-hide" data-mid="{html.escape(s['meeting_id'])}" type="button">
                    Скрыть из отчёта
                </button>
            </div>

            <div class="copy-row">
                <button class="btn-copy-attendees"
                        type="button"
                        data-target="attendees-{idx}"
                        data-count="{s['attendees_count']}">
                    Скопировать список участников ({s['attendees_count']})
                </button>
                <span class="copy-hint" id="hint-{idx}"></span>
            </div>
            <textarea id="attendees-{idx}" class="attendees-data" readonly>{attendees_escaped}</textarea>

            <details>
                <summary>Участники ({s['users_count']})</summary>
                {render_users_table(s['users'])}
            </details>
        </div>
        """

    if not cards:
        cards = '<p class="empty">Статистика не найдена (все сессии отфильтрованы как мусор или отсутствуют).</p>'

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Статистика конференций BigBlueButton</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 2rem auto;
            max-width: 1400px;
            padding: 0 1rem;
            color: #222;
        }}
        h1 {{ margin-bottom: 0.5rem; }}
        .summary {{ color: #666; margin-bottom: 1rem; }}

        .toolbar {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem 1.25rem;
            align-items: center;
            padding: 0.75rem 1rem;
            background: #f4f7fb;
            border: 1px solid #d6e2f0;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            font-size: 0.9em;
        }}
        .toolbar label {{ display: inline-flex; align-items: center; gap: 0.35rem; }}
        .toolbar input[type="text"],
        .toolbar input[type="number"],
        .toolbar input[type="date"],
        .toolbar select {{
            padding: 4px 8px;
            border: 1px solid #c5d2e0;
            border-radius: 4px;
            font-size: 0.95em;
        }}
        .toolbar input[type="text"] {{ min-width: 240px; }}
        .toolbar input[type="number"] {{ width: 70px; }}
        #counter {{ margin-left: auto; color: #555; }}

        .card {{
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 1.25rem 1.5rem;
            margin-bottom: 1.5rem;
            background: #fff;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        .card h2 {{ margin: 0 0 0.25rem; }}
        .card .when {{ color: #0066cc; font-weight: 600; margin-bottom: 0.75rem; }}
        .meta {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 0.4rem 1.5rem;
            margin-bottom: 1rem;
            font-size: 0.95em;
        }}
        .meeting-id {{ grid-column: 1 / -1; }}
        .meeting-id code {{ font-size: 0.85em; color: #555; }}

        .actions {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 0.75rem;
        }}
        .button {{
            display: inline-block;
            background: #0066cc;
            color: #fff;
            padding: 0.5rem 1rem;
            border-radius: 5px;
            text-decoration: none;
            font-weight: 500;
            border: none;
            cursor: pointer;
        }}
        .button:hover {{ background: #0055aa; }}
        .btn-hide {{
            background: #fff;
            color: #b00020;
            border: 1px solid #e0b4bd;
            padding: 0.45rem 0.9rem;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9em;
        }}
        .btn-hide:hover {{ background: #fff2f4; }}

        .copy-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            align-items: center;
            margin-bottom: 0.75rem;
        }}
        .btn-copy-attendees {{
            background: #1a7f37;
            color: #fff;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 5px;
            cursor: pointer;
            font-weight: 500;
        }}
        .btn-copy-attendees:hover {{ background: #145f2a; }}
        .btn-copy-attendees.copied {{ background: #2e7d32; }}
        .copy-hint {{ color: #1a7f37; font-size: 0.9em; }}
        .attendees-data {{
            position: absolute;
            left: -9999px;
            top: -9999px;
            width: 1px;
            height: 1px;
            opacity: 0;
            pointer-events: none;
        }}

        details {{ margin-top: 1rem; }}
        details summary {{
            cursor: pointer;
            font-weight: 600;
            padding: 0.4rem 0;
            color: #0066cc;
        }}
        details[open] summary {{ margin-bottom: 0.75rem; }}

        table {{
            border-collapse: collapse;
            width: 100%;
            font-size: 0.9em;
        }}
        th, td {{
            border: 1px solid #e0e0e0;
            padding: 6px 10px;
            text-align: left;
        }}
        th {{ background: #f4f4f4; font-weight: 600; }}
        tr:nth-child(even) td {{ background: #fafafa; }}
        tr:hover td {{ background: #f0f7ff; }}

        .badge {{
            display: inline-block;
            font-size: 0.75em;
            padding: 2px 8px;
            border-radius: 10px;
            vertical-align: middle;
            margin-left: 0.5rem;
        }}
        .badge.warn {{ background: #ffd699; color: #663c00; }}
        .empty {{ color: #777; font-style: italic; }}
    </style>
</head>
<body>
    <h1>Статистика конференций BigBlueButton</h1>
    <p class="summary">
        Всего сессий: {len(sessions)}.
        Обновлено: {datetime.now(tz=TIMEZONE).strftime('%d.%m.%Y %H:%M:%S')}
    </p>

    <div class="toolbar">
        <label>Поиск:
            <input id="q" type="text" placeholder="название или meeting id">
        </label>
        <label>Мин. участников:
            <input id="minUsers" type="number" value="0" min="0">
        </label>
        <label>С:
            <input id="from" type="date">
        </label>
        <label>По:
            <input id="to" type="date">
        </label>
        <label>Сортировка:
            <select id="sort">
                <option value="date-desc">Сначала новые</option>
                <option value="date-asc">Сначала старые</option>
                <option value="users-desc">Больше участников</option>
                <option value="dur-desc">Дольше всего</option>
                <option value="name-asc">По названию</option>
            </select>
        </label>
        <span id="counter"></span>
    </div>

    <div id="cards">
    {cards}
    </div>

    <script>
    (function () {{
        const cardsEl = document.getElementById('cards');
        const cards = Array.from(cardsEl.querySelectorAll('.card'));
        const qEl = document.getElementById('q');
        const minUsersEl = document.getElementById('minUsers');
        const fromEl = document.getElementById('from');
        const toEl = document.getElementById('to');
        const sortEl = document.getElementById('sort');
        const counterEl = document.getElementById('counter');

        function parseDateInput(v) {{
            if (!v) return null;
            const d = new Date(v + 'T00:00:00');
            return isNaN(d.getTime()) ? null : d.getTime();
        }}

        function apply() {{
            const q = qEl.value.trim().toLowerCase();
            const minUsers = parseInt(minUsersEl.value, 10) || 0;
            const from = parseDateInput(fromEl.value);
            const to = parseDateInput(toEl.value);
            const toEnd = to !== null ? to + 24 * 3600 * 1000 - 1 : null;

            let visible = 0;
            cards.forEach(c => {{
                const name = c.dataset.name || '';
                const mid = c.dataset.mid || '';
                const users = parseInt(c.dataset.users, 10) || 0;
                const ts = parseInt(c.dataset.ts, 10) || 0;

                let ok = true;
                if (q && !(name.includes(q) || mid.includes(q))) ok = false;
                if (users < minUsers) ok = false;
                if (from !== null && ts < from) ok = false;
                if (toEnd !== null && ts > toEnd) ok = false;

                c.style.display = ok ? '' : 'none';
                if (ok) visible++;
            }});

            const mode = sortEl.value;
            const sorted = cards.slice().sort((a, b) => {{
                const ta = parseInt(a.dataset.ts, 10) || 0;
                const tb = parseInt(b.dataset.ts, 10) || 0;
                const ua = parseInt(a.dataset.users, 10) || 0;
                const ub = parseInt(b.dataset.users, 10) || 0;
                const da = parseInt(a.dataset.dur, 10) || 0;
                const db = parseInt(b.dataset.dur, 10) || 0;
                const na = a.dataset.name || '';
                const nb = b.dataset.name || '';
                switch (mode) {{
                    case 'date-asc': return ta - tb;
                    case 'users-desc': return ub - ua;
                    case 'dur-desc': return db - da;
                    case 'name-asc': return na.localeCompare(nb, 'ru');
                    default: return tb - ta;
                }}
            }});
            sorted.forEach(c => cardsEl.appendChild(c));

            counterEl.textContent = `Показано: ${{visible}} из ${{cards.length}}`;
        }}

        [qEl, minUsersEl, fromEl, toEl, sortEl].forEach(el =>
            el.addEventListener('input', apply)
        );
        sortEl.addEventListener('change', apply);
        apply();

        // Кнопка "Скрыть из отчёта"
        document.querySelectorAll('.btn-hide').forEach(btn => {{
            btn.addEventListener('click', async () => {{
                const mid = btn.dataset.mid;
                try {{
                    await navigator.clipboard.writeText(mid);
                    btn.textContent = 'ID скопирован ✓';
                    setTimeout(() => {{ btn.textContent = 'Скрыть из отчёта'; }}, 2000);
                }} catch (e) {{
                    prompt('Скопируйте meeting_id и добавьте в skip-файл:', mid);
                }}
            }});
        }});

        // Кнопка "Скопировать список участников"
        document.querySelectorAll('.btn-copy-attendees').forEach(btn => {{
            btn.addEventListener('click', async () => {{
                const targetId = btn.dataset.target;
                const count = btn.dataset.count;
                const ta = document.getElementById(targetId);
                const hintId = targetId.replace('attendees-', 'hint-');
                const hint = document.getElementById(hintId);

                if (!ta) return;
                const text = ta.value;

                if (!text || count === '0') {{
                    if (hint) {{
                        hint.textContent = 'Нет участников без модераторов';
                        hint.style.color = '#b00020';
                        setTimeout(() => {{ hint.textContent = ''; }}, 2500);
                    }}
                    return;
                }}

                try {{
                    await navigator.clipboard.writeText(text);
                    btn.classList.add('copied');
                    const original = btn.textContent;
                    btn.textContent = 'Скопировано ✓';
                    if (hint) hint.textContent = '';
                    setTimeout(() => {{
                        btn.classList.remove('copied');
                        btn.textContent = original;
                    }}, 2000);
                }} catch (e) {{
                    // Фолбэк: выделяем textarea и предлагаем скопировать вручную
                    ta.style.position = 'static';
                    ta.style.width = '100%';
                    ta.style.height = 'auto';
                    ta.style.opacity = '1';
                    ta.style.pointerEvents = 'auto';
                    ta.select();
                    try {{
                        document.execCommand('copy');
                        btn.textContent = 'Скопировано ✓';
                        setTimeout(() => {{ btn.textContent = original; }}, 2000);
                    }} catch (_) {{
                        if (hint) {{
                            hint.textContent = 'Скопируйте вручную из поля ниже';
                            hint.style.color = '#b00020';
                        }}
                    }}
                }}
            }});
        }});
    }})();
    </script>
</body>
</html>
"""


# --- CLI для очистки старых сессий ---

def prune_sessions(older_than_days: int, apply: bool) -> None:
    if not DASHBOARD_DIR.is_dir():
        print(f"Директория не найдена: {DASHBOARD_DIR}", file=sys.stderr)
        return

    now = datetime.now(tz=TIMEZONE).timestamp()
    threshold = now - older_than_days * 86400
    victims = []

    for session_dir in DASHBOARD_DIR.iterdir():
        if not session_dir.is_dir():
            continue
        data_file = find_data_file(session_dir)
        if not data_file:
            continue
        try:
            data = json.loads(data_file.read_text(encoding="utf-8"))
            created = data.get("createdOn")
            if not created:
                created = int(session_dir.stat().st_mtime * 1000)
            created_sec = created / 1000
        except (json.JSONDecodeError, OSError, ValueError):
            continue

        if created_sec < threshold:
            victims.append((session_dir, ts_to_str(created * 1000)))

    if not victims:
        print("Нечего удалять — сессий старше указанного срока нет.")
        return

    print(f"Найдено сессий для удаления: {len(victims)}")
    for path, date_str in victims:
        print(f"  {date_str}  {path.name}")

    if not apply:
        print("\nЭто dry-run. Для удаления добавьте --apply.")
        return

    confirm = input("\nУдалить перечисленные сессии? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Отменено.")
        return

    removed = 0
    for path, _ in victims:
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as e:
            print(f"Не удалось удалить {path}: {e}", file=sys.stderr)
    print(f"Удалено: {removed} из {len(victims)}")


def main():
    parser = argparse.ArgumentParser(description="BigBlueButton stats page generator")
    parser.add_argument("--prune", type=int, metavar="DAYS",
                        help="Удалить сессии старше N дней (dry-run без --apply)")
    parser.add_argument("--apply", action="store_true",
                        help="Применить удаление (с --prune)")
    args = parser.parse_args()

    if args.prune is not None:
        prune_sessions(args.prune, args.apply)
        return

    sessions = collect_sessions()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(render_html(sessions), encoding="utf-8")
    print(f"Готово. Найдено сессий: {len(sessions)}. Файл: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()