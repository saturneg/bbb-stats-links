#!/usr/bin/env python3
"""
Генератор статистики BigBlueButton Learning Analytics Dashboard.
Читает learning_dashboard_data.json для каждой сессии и формирует
подробную HTML-страницу: название, даты, участники, активность.
"""

import json
import html
from datetime import datetime
from pathlib import Path

# --- Настройки ---
BBB_HOST = "https://arazasjuyay.beget.app"
DASHBOARD_DIR = Path("/var/bigbluebutton/learning-dashboard")
OUTPUT_FILE = Path("/var/www/html/bbb-stats/index.html")


def ts_to_str(ms) -> str:
    """Timestamp в мс -> 'YYYY-MM-DD HH:MM'."""
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, TypeError):
        return "—"


def duration_str(start_ms, end_ms) -> str:
    """Длительность в формате 'Чч Мм'."""
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


def find_data_file(session_dir: Path) -> Path | None:
    """Ищет learning_dashboard_data.json внутри подпапки-токена."""
    for sub in session_dir.iterdir():
        if sub.is_dir():
            candidate = sub / "learning_dashboard_data.json"
            if candidate.is_file():
                return candidate
    return None


def collect_user_stats(users: dict) -> list[dict]:
    """Извлекает статистику по каждому участнику."""
    result = []
    for user in users.values():
        # Время в сессии: берём самую раннюю registeredOn и самую позднюю leftOn
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
    # Сортируем: сначала модераторы, потом по имени
    result.sort(key=lambda u: (not u["is_moderator"], u["name"].lower()))
    return result


def collect_sessions() -> list[dict]:
    """Собирает все сессии со статистикой."""
    sessions = []

    if not DASHBOARD_DIR.is_dir():
        return sessions

    for session_dir in sorted(DASHBOARD_DIR.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue

        meeting_id = session_dir.name
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
        users = data.get("users", {})

        url = (
            f"{BBB_HOST}/learning-analytics-dashboard/"
            f"?meeting={meeting_id}&report={token}&lang=ru"
        )

        sessions.append({
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
            "users": collect_user_stats(users),
            "url": url,
        })

    return sessions


def render_users_table(users: list[dict]) -> str:
    """Таблица участников."""
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
    """Формирует HTML-страницу."""
    cards = ""
    for s in sessions:
        disabled_badge = (
            '<span class="badge warn">Дашборд отключён</span>'
            if s["disabled"] else ""
        )

        cards += f"""
        <div class="card">
            <h2>{html.escape(s['name'])} {disabled_badge}</h2>

            <div class="meta">
                <div><strong>Начало:</strong> {html.escape(s['date'])}</div>
                <div><strong>Окончание:</strong> {html.escape(s['ended'])}</div>
                <div><strong>Длительность:</strong> {html.escape(s['duration'])}</div>
                <div><strong>Участников:</strong> {s['users_count']} (модераторов: {s['moderators_count']})</div>
                <div><strong>Опросов:</strong> {s['polls_count']}</div>
                <div><strong>Демонстраций экрана:</strong> {s['screenshares_count']}</div>
                <div><strong>Слайдов:</strong> {s['slides_count']}</div>
                <div class="meeting-id"><strong>Meeting ID:</strong> <code>{html.escape(s['meeting_id'])}</code></div>
            </div>

            <p>
                <a class="button" href="{html.escape(s['url'])}" target="_blank">
                    Открыть интерактивный дашборд
                </a>
            </p>

            {render_users_table(s['users'])}
        </div>
        """

    if not cards:
        cards = "<p>Статистика не найдена.</p>"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
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
        .summary {{ color: #666; margin-bottom: 2rem; }}
        .card {{
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 1.25rem 1.5rem;
            margin-bottom: 2rem;
            background: #fff;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        .card h2 {{ margin-top: 0; }}
        .meta {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 0.4rem 1.5rem;
            margin-bottom: 1rem;
            font-size: 0.95em;
        }}
        .meeting-id {{ grid-column: 1 / -1; }}
        .meeting-id code {{ font-size: 0.85em; color: #555; }}
        .button {{
            display: inline-block;
            background: #0066cc;
            color: #fff;
            padding: 0.5rem 1rem;
            border-radius: 5px;
            text-decoration: none;
            font-weight: 500;
            margin-bottom: 1rem;
        }}
        .button:hover {{ background: #0055aa; }}
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
    </style>
</head>
<body>
    <h1>Статистика конференций BigBlueButton</h1>
    <p class="summary">
        Всего сессий: {len(sessions)}.
        Обновлено: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </p>
    {cards}
</body>
</html>
"""


def main():
    sessions = collect_sessions()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(render_html(sessions), encoding="utf-8")
    print(f"Готово. Найдено сессий: {len(sessions)}. Файл: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()