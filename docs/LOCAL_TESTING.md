# Local Testing Before VPS

## 1. Подготовка

- Убедитесь, что установлен Docker Desktop.
- Проверьте, что заполнен `.env`:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_WEBHOOK_SECRET`
  - `OPENAI_API_KEY`

## 2. Автоматический прогон

В PowerShell из корня проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local_integration_check.ps1
```

Если нужно пропустить pytest:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local_integration_check.ps1 -SkipTests
```

## 3. Ручной smoke в Telegram

Проверьте сценарии:

1. Создание одного напоминания с точным временем.
2. Создание нескольких напоминаний одним сообщением.
3. Создание без времени:
   - "сегодня" -> ближайший час,
   - "завтра/послезавтра/день недели" -> 08:00.
4. Списки:
   - все,
   - на сегодня,
   - статус,
   - поиск,
   - интервал.
5. Удаление:
   - по фильтру,
   - последние `N`.
6. Повторяющиеся напоминания (`recurrence_rule`).

## 4. Проверка логов

```powershell
docker compose logs -f app
```

В логах должны быть:
- старт приложения,
- обработка webhook,
- строки учета LLM usage.

