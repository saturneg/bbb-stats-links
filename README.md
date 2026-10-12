# 📘 BigBlueButton Stats Page

Скрипт для генерации HTML-страницы со сводной статистикой всех конференций BigBlueButton на сервере.

---

## 📖 О проекте

**BigBlueButton Stats Page** решает проблему отсутствия удобного доступа к статистике конференций в Moodle. В стандартном модуле BigBlueButton кнопка «Статистика» часто отсутствует, а данные Learning Analytics Dashboard удаляются через 2 минуты после завершения встречи.

Скрипт обходит это ограничение: читает файлы `learning_dashboard_data.json` напрямую с диска сервера и формирует удобную HTML-страницу с полной информацией о каждой сессии.

### Что показывает

- **Название комнаты**, дата и время начала/окончания
- **Длительность** встречи
- **Количество участников** и модераторов
- **Опросы**, демонстрации экрана, слайды
- **Подробную таблицу участников** (скрыта под аккордеоном):
  - Имя, роль
  - Время входа/выхода, длительность пребывания
  - Сообщения в чате
  - Время речи
  - Включения камеры, поднятия руки, реакции
  - Заметки, аннотации на доске, ответы на опросы
- **Прямую ссылку** на интерактивный Learning Analytics Dashboard

---

## ✅ Требования

| Компонент | Версия / Примечание |
|---|---|
| BigBlueButton | 2.6+ (эндпоинт `/learning-analytics-dashboard/`) |
| Python | 3.9+ (используется `str \| None`) |
| nginx | Устанавливается вместе с BBB |
| Права | `root` или `sudo` |

---

## 🚀 Установка

### 1. Скопировать скрипт на сервер

Поместите файл `bbb-stats-links.py` в `/usr/local/bin/`:

```bash
sudo cp bbb-stats-links.py /usr/local/bin/bbb-stats-links.py
```

### 2. Настроить параметры

Откройте скрипт:

```bash
sudo nano /usr/local/bin/bbb-stats-links.py
```

Отредактируйте две константы в начале файла:

```python
BBB_HOST = "https://ваш-домен.ru"           # адрес BBB-сервера
OUTPUT_FILE = Path("/var/www/html/bbb-stats/index.html")
```

### 3. Сделать исполняемым и запустить

```bash
sudo chmod +x /usr/local/bin/bbb-stats-links.py
sudo python3 /usr/local/bin/bbb-stats-links.py
```

Ожидаемый вывод:

```
Готово. Найдено сессий: N. Файл: /var/www/html/bbb-stats/index.html
```

### 4. Настроить nginx

Откройте конфиг BBB:

```bash
sudo nano /etc/nginx/sites-available/bigbluebutton
```

Найдите `server`-блок, который слушает **порт 82** (`listen 127.0.0.1:82 proxy_protocol;`) — это HTTPS-канал, если SSL терминируется на haproxy. Добавьте туда:

```nginx
location /bbb-stats/ {
    alias /var/www/html/bbb-stats/;
    index index.html;
    try_files $uri $uri/ =404;
}
```

> ⚠️ **Не добавляйте** `location` в HTTP-блок (`listen 80`), где стоит `return 301` — там он не сработает, так как все запросы уходят на редирект.

Проверьте и перезагрузите:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 5. Откройте страницу

```
https://ваш-домен.ru/bbb-stats/
```

---

## ⏰ Автообновление через cron

Чтобы страница обновлялась сама:

```bash
sudo crontab -e
```

Добавьте в конец:

```
*/5 * * * * /usr/bin/python3 /usr/local/bin/bbb-stats-links.py > /dev/null 2>&1
```

Страница будет пересобираться каждые 5 минут.

---

## 📊 Структура данных

Скрипт читает файл:

```
/var/bigbluebutton/learning-dashboard/<meeting_id>/<report_token>/learning_dashboard_data.json
```

Где:
- `<meeting_id>` — уникальный идентификатор встречи (например, `7e2ecab2f7b9004de404a4965cf6b2fc3f5ca1a0-1791799354722`)
- `<report_token>` — токен доступа (например, `ghgfd7kqjpog`), имя подпапки внутри директории сессии

### Используемые поля JSON

| Поле | Содержимое |
|---|---|
| `name` | Название комнаты |
| `createdOn` | Timestamp начала (мс) |
| `endedOn` | Timestamp окончания (мс) |
| `learningDashboardDisabled` | Флаг отключения дашборда |
| `users` | Словарь участников |
| `users[].name` | Имя участника |
| `users[].isModerator` | Является ли модератором |
| `users[].intIds[].sessions[]` | Сессии входа/выхода (`registeredOn`, `leftOn`) |
| `users[].totalOfMessages` | Сообщений в чате |
| `users[].talk.totalTime` | Время речи (мс) |
| `users[].webcams` | Включения камеры |
| `users[].raiseHand` | Поднятия руки |
| `users[].reactions` | Реакции |
| `users[].totalOfSharedNotes` | Заметки |
| `users[].totalOfWhiteboardAnnotations` | Аннотации на доске |
| `users[].answers` | Ответы на опросы |
| `polls` | Опросы |
| `screenshares` | Демонстрации экрана |
| `presentationSlides` | Показанные слайды |

---

## ⚠️ Важные нюансы

### 1. Данные статистики удаляются

По умолчанию BBB очищает Learning Dashboard через **2 минуты** после завершения встречи. Чтобы статистика сохранялась постоянно, на сервере должно быть:

```bash
grep learningDashboardCleanup /usr/share/bbb-web/WEB-INF/classes/bigbluebutton.properties
```

Значение должно быть:

```properties
learningDashboardCleanupDelayInMinutes=0
```

Если другое — измените и перезапустите:

```bash
sudo systemctl restart bbb-web
```

> Изменение применяется только к **новым** встречам.

### 2. Сохранение событий встречи

Параметр `defaultKeepEvents=true` в `/usr/share/bbb-web/WEB-INF/classes/bigbluebutton.properties` отвечает за сохранение событий встречи. Без него данные дашборда могут быть неполными.

```bash
sudo systemctl restart bbb-web
```

### 3. Токен `report` обязателен

Ссылка вида:

```
https://bbb.example.com/learning-analytics-dashboard/?meeting=<id>&report=<token>&lang=ru
```

работает только с корректным `report`. Без токена дашборд отдаёт ошибку (проверено в режиме инкогнито).

### 4. Не путайте эндпоинты

| Путь | Статус |
|---|---|
| `/learning-dashboard/` | ❌ Устаревший (BBB < 2.6), отдаёт 404 |
| `/learning-analytics-dashboard/` | ✅ Актуальный (BBB 2.6+) |

### 5. Конфигурация за haproxy

Если SSL терминируется на haproxy, nginx слушает только локальный порт. `location` нужно добавлять в `server`-блок с `listen 127.0.0.1:82 proxy_protocol;`, а не в блок с `listen 443 ssl`.

### 6. Определение даты

Дата берётся из поля `createdOn` (timestamp в мс). Если поле отсутствует — используется время модификации папки (менее точно).

---

## 🔒 Безопасность

Страница `/bbb-stats/` содержит **токены доступа** к дашбордам. Любой, кто знает URL, сможет посмотреть статистику всех конференций. Рекомендуется закрыть её basic-аутентификацией.

```bash
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd admin
```

В nginx добавьте в `location /bbb-stats/`:

```nginx
auth_basic "Статистика BBB";
auth_basic_user_file /etc/nginx/.htpasswd;
```

Перезагрузите:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 🧪 Диагностика

### Страница отдаёт 404

1. Проверьте, что файл существует:
   ```bash
   ls -la /var/www/html/bbb-stats/
   ```

2. Проверьте, что `location` в правильном `server`-блоке:
   ```bash
   sudo nginx -T 2>/dev/null | grep -B20 "bbb-stats" | grep -E "listen|server_name"
   ```
   Перед `bbb-stats` должно быть `listen 127.0.0.1:82` (или `listen 443 ssl`), а не `listen 80`.

3. Проверьте логи:
   ```bash
   sudo tail -20 /var/log/nginx/error.log
   ```

### Скрипт находит 0 сессий

1. Проверьте директорию:
   ```bash
   ls -la /var/bigbluebutton/learning-dashboard/
   ```

2. Найдите JSON-файлы:
   ```bash
   find /var/bigbluebutton/learning-dashboard/ -name "learning_dashboard_data.json"
   ```

3. Проверьте `learningDashboardCleanupDelayInMinutes=0`.

### Ссылка работает в обычном окне, но не в инкогнито

Токен `report` не проходит, доступ обеспечивается сессией BBB. Убедитесь, что в URL есть `&report=<token>` и он совпадает с именем подпапки на диске.

### Страница не обновляется

Проверьте cron:
```bash
sudo crontab -l
```

Запустите вручную:
```bash
sudo python3 /usr/local/bin/bbb-stats-links.py
```

---

## 📌 Ограничения

- Только **завершённые** встречи — данные текущих сессий появятся после окончания.
- Только встречи **с записанной статистикой** — если Learning Dashboard не создан, сессии не будет в списке.
- **Нет фильтрации по курсам** — скрипт показывает все сессии на сервере, без привязки к Moodle.
- **Зависимость от формата JSON** — при изменении структуры `learning_dashboard_data.json` в новых версиях BBB скрипт потребует доработки.

---

## 📄 Лицензия

MIT